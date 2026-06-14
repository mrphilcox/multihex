# Copyright (c) 2026 Philip Cox
# SPDX-License-Identifier: Apache-2.0

"""multihex.gui - read-only PySide6/Qt desktop frontend for fixed-offset compare.

A viewer only: no editing, no inference, no resynchronization, no offset-changing
byte filtering. All comparison meaning lives in :mod:`multihex.core` so this
frontend stays in lockstep with the batch ``multihex`` CLI and the ``multihex-tui``
interactive frontend.

Usage:
    multihex-gui file1.bin file2.bin file3.bin
    multihex-gui --offset 0x400 --width 16 *.bin
    multihex-gui --ref 0 --only-diff file*.bin
    multihex-gui                      # empty window; open files from the File menu

PySide6 is an *optional* dependency (the ``[gui]`` extra). Importing this module,
parsing args, and ``--help`` all work without PySide6 installed; only actually
launching the window needs it.
"""

from __future__ import annotations

import argparse
import bisect
import ctypes
import os
import sys
from typing import List, Optional, Sequence, Tuple, Union

from multihex.core import (
    OFFSET_LABEL_WIDTH,
    ByteClass,
    HexModel,
    Marker,
    SearchError,
    SearchMatch,
    SearchQuery,
    classify_byte,
    first_match_index,
    format_ascii_char,
    format_byte,
    format_marker,
    load_files,
    make_hex_query,
    make_text_query,
    marker_prefix_width,
    name_column_width,
    next_match_index,
    offset_label,
    parse_hex_pattern,
    parse_int,
    prev_match_index,
    search_files,
)
from multihex.overlay import OverlayState
from multihex.shortcuts import (
    gui_help_text,
    gui_key_names,
    gui_shortcuts,
    gui_text_map,
)

# --------------------------------------------------------------------------- #
# Pure-Python helpers (no Qt). Defined unconditionally so they import and unit-
# test even when PySide6 is not installed.
# --------------------------------------------------------------------------- #


class ViewState:
    """Navigation + only-diff filter state over a :class:`HexModel`.

    Qt-free on purpose: this owns "which global rows are visible", the mapping
    between a visible *position* and a global row index, and the scroll ``top``
    position. The Qt widget keeps its scrollbar in sync with ``top`` and renders;
    all the index math lives here so it can be tested without a display.

    A "position" indexes the *visible* set (0 .. visible_count-1); a "row index"
    indexes the model's full fixed grid (0 .. model.row_count-1). They coincide
    unless only-diff filtering is on.
    """

    def __init__(self, model: HexModel, *, only_diff: bool = False) -> None:
        self.model = model
        self.only_diff = only_diff
        self.top = 0
        self._visible: Optional[Union[range, List[int]]] = None

    # -- visible-index (only-diff) management ------------------------------- #
    def visible_indices(self) -> Union[range, List[int]]:
        """Visible global row indices: all rows, or only differing rows.

        Cached until :meth:`invalidate` (called on ref / only-diff changes).
        """
        if self._visible is None:
            if self.only_diff:
                # TODO(perf, GUI Phase 8): this builds every row to find the diff
                # rows, which is O(file size) and not scalable to multi-GB files.
                # It is correct and fine for the first pass; optimize later (e.g.
                # a lazily-extended / cached differing-row index) without changing
                # the comparison semantics.
                self._visible = [
                    i
                    for i in range(self.model.row_count)
                    if self.model.build_row(i).has_diff
                ]
            else:
                self._visible = range(self.model.row_count)
        return self._visible

    def invalidate(self) -> None:
        """Drop the cached visible set (after ref / only-diff changes)."""
        self._visible = None

    @property
    def visible_count(self) -> int:
        return len(self.visible_indices())

    # -- position <-> row-index mapping ------------------------------------- #
    def row_index_at(self, pos: int) -> int:
        """Global row index at visible ``pos`` (clamped). 0 when nothing visible."""
        vis = self.visible_indices()
        if not vis:
            return 0
        pos = max(0, min(pos, len(vis) - 1))
        return vis[pos]

    def offset_at(self, pos: int) -> int:
        """Absolute start offset of the row at visible ``pos``."""
        return self.model.row_offset(self.row_index_at(pos))

    def position_for_row(self, row_index: int) -> int:
        """Visible position for a global ``row_index``.

        In only-diff mode a non-visible row snaps *forward* to the next visible
        (differing) row, matching the TUI's behaviour.
        """
        vis = self.visible_indices()
        if not vis:
            return 0
        if isinstance(vis, range):
            return min(max(0, row_index), len(vis) - 1)
        pos = bisect.bisect_left(vis, row_index)
        if pos >= len(vis):
            pos = len(vis) - 1
        return pos

    def index_for_offset(self, offset: int) -> int:
        return self.model.index_for_offset(offset)

    def position_for_offset(self, offset: int) -> int:
        return self.position_for_row(self.index_for_offset(offset))

    # -- top / clamping ----------------------------------------------------- #
    def max_top(self, page_rows: int) -> int:
        return max(0, self.visible_count - max(1, page_rows))

    def clamp_top(self, page_rows: int) -> None:
        self.top = max(0, min(self.top, self.max_top(page_rows)))

    # -- filter / reference changes (re-anchor the top row) ----------------- #
    def set_only_diff(self, value: bool, *, page_rows: int = 1) -> None:
        keep = self.row_index_at(self.top)
        self.only_diff = value
        self.invalidate()
        self.top = self.position_for_row(keep)
        self.clamp_top(page_rows)

    def set_ref(self, ref: Optional[int], *, page_rows: int = 1) -> None:
        keep = self.row_index_at(self.top)
        self.model.ref = ref
        # Marker set changed -> the only-diff filter must be rebuilt.
        self.invalidate()
        self.top = self.position_for_row(keep)
        self.clamp_top(page_rows)


def format_status_parts(
    *,
    offset_start: int,
    offset_end: int,
    row_pos: int,
    row_count: int,
    ref_label: str,
    ascii_on: bool,
    only_diff: bool,
    markers: str,
    color_on: bool = True,
    byte_classes_on: bool = False,
    layout: str = "stacked",
    sizes: Sequence[Tuple[str, int]],
) -> List[str]:
    """Build the status-bar segments from primitives (pure; testable without Qt).

    Mirrors the TUI status line content: visible offset range, row
    position/count, reference mode, the display toggles (including the layout and
    the marker mode), and per-file sizes. One string per status-bar segment, in
    display order.
    """
    if row_count <= 0:
        where = "no rows"
    else:
        where = f"0x{offset_start:08x}-0x{offset_end:08x} | row {row_pos}/{row_count}"
    toggles = "ascii:%s diff:%s markers:%s color:%s classes:%s layout:%s" % (
        "on" if ascii_on else "off",
        "on" if only_diff else "off",
        markers,
        "on" if color_on else "off",
        "on" if byte_classes_on else "off",
        layout,
    )
    sizes_s = "sizes: " + "  ".join(f"{name}={size}" for name, size in sizes)
    return [where, f"ref={ref_label}", toggles, sizes_s]


def format_status(
    *,
    offset_start: int,
    offset_end: int,
    row_pos: int,
    row_count: int,
    ref_label: str,
    ascii_on: bool,
    only_diff: bool,
    markers: str,
    color_on: bool = True,
    byte_classes_on: bool = False,
    layout: str = "stacked",
    sizes: Sequence[Tuple[str, int]],
) -> str:
    """The status segments joined into one line (see format_status_parts)."""
    return " | ".join(
        format_status_parts(
            offset_start=offset_start,
            offset_end=offset_end,
            row_pos=row_pos,
            row_count=row_count,
            ref_label=ref_label,
            ascii_on=ascii_on,
            only_diff=only_diff,
            markers=markers,
            color_on=color_on,
            byte_classes_on=byte_classes_on,
            layout=layout,
            sizes=sizes,
        )
    )


def format_search_status(query, matches, index, error) -> Optional[str]:
    """Persistent search-segment text, or None when no search is active (pure).

    Mirrors the TUI's dedicated search status line: the query (with a "(ci)"
    mark for case-insensitive text), match position/count with the current
    match's file and offset, "no matches", or the search error.
    """
    if error is not None:
        return f"Search error: {error}"
    if query is None:
        return None
    label = f'{query.mode} "{query.pattern}"'
    if query.mode == "text" and not query.case_sensitive:
        label += " (ci)"
    if not matches:
        return f"Search: {label} | no matches"
    cur = index or 0
    m = matches[cur]
    return (
        f"Search: {label} | match {cur + 1}/{len(matches)} "
        f"| file {m.file_index} | offset 0x{m.offset:08x}"
    )


def format_overlay_status(
    *,
    name: Optional[str],
    applicable: bool,
    range_count: int,
    warning_count: int,
    error_count: int,
) -> str:
    """Short persistent status-bar label for a loaded layout overlay (pure).

    The severities/counts come straight from the validator via OverlayState;
    this only words them (never re-derives the ok/applicable contract).
    """
    label = f" {name!r}" if name else ""
    if not applicable:
        noun = "error" if error_count == 1 else "errors"
        return f"overlay{label}: not applied ({error_count} {noun})"
    noun = "range" if range_count == 1 else "ranges"
    text = f"overlay{label}: {range_count} {noun}"
    if warning_count:
        noun = "warning" if warning_count == 1 else "warnings"
        text += f", {warning_count} {noun}"
    return text


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="multihex-gui",
        description="Read-only desktop GUI for fixed-offset comparison of multiple "
        "binary files (viewer only).",
    )
    # nargs="*" so launching with no files opens an empty window (open via the menu).
    p.add_argument("files", nargs="*", help="binary files to compare (optional)")
    p.add_argument("--offset", type=parse_int, default=0, metavar="N",
                   help="start offset (int, 0x.. ok)")
    p.add_argument("--width", type=parse_int, default=16, metavar="N",
                   help="bytes per row (default 16)")
    p.add_argument("--ref", type=parse_int, default=None, metavar="INDEX",
                   help="compare every file against this 0-based index")
    p.add_argument("--names", choices=["basename", "path"], default="basename",
                   help="how to label files (default basename)")
    p.add_argument("--only-diff", action="store_true", dest="only_diff",
                   help="start with only differing rows shown")
    p.add_argument("--no-ascii", action="store_true", dest="no_ascii",
                   help="start with the ASCII gutter hidden")
    p.add_argument("--markers", choices=["single", "repeat", "none"],
                   default="single",
                   help="initial marker text display: single (default), repeat "
                        "(repeat the strip under each segment in side-by-side; "
                        "same as single when stacked), or none (hidden). Cycle "
                        "with 'm'. Display-only.")
    p.add_argument("--layout", choices=["stacked", "side-by-side"],
                   default="stacked",
                   help="initial layout: stacked (default) or side-by-side "
                        "(cycle with 'v'; scroll horizontally with left/right). "
                        "Display-only.")
    p.add_argument("--overlay", metavar="PATH", default=None,
                   help="load a bintools.layout-overlay v1 JSON file (a read-only "
                        "annotation layer) and highlight its byte ranges. Manage "
                        "from the Overlay menu. Not saved in config.")
    return p


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    return build_parser().parse_args(argv)


def clamp_ref(ref: Optional[int], nfiles: int) -> Optional[int]:
    """Validate a reference file index against the loaded file count.

    Returns ``ref`` when it is a valid 0-based index into ``nfiles`` files,
    otherwise ``None`` ("all agree" — no reference). Qt-free so the GUI's
    reference-selection validation is unit-testable without a display.
    """
    if ref is not None and 0 <= ref < nfiles:
        return ref
    return None


def _qt_platforms(env: Optional[dict] = None) -> List[str]:
    """Return requested Qt platform names from QT_QPA_PLATFORM, if any."""
    value = (env or os.environ).get("QT_QPA_PLATFORM", "")
    platforms = []
    for part in value.split(";"):
        name = part.split(":", 1)[0].strip()
        if name:
            platforms.append(name)
    return platforms


def _needs_xcb_cursor_preflight(env: Optional[dict] = None) -> bool:
    """Whether Qt is likely to initialize through the Linux xcb plugin."""
    if not sys.platform.startswith("linux"):
        return False
    env = env or os.environ
    platforms = _qt_platforms(env)
    if platforms:
        return platforms[0] == "xcb"
    # With no explicit platform, Qt commonly chooses xcb for X11 sessions.
    # Wayland users can still run through the wayland plugin without libxcb-cursor.
    return bool(env.get("DISPLAY")) and not bool(env.get("WAYLAND_DISPLAY"))


def _missing_xcb_cursor_message(loader=ctypes.CDLL, env: Optional[dict] = None) -> Optional[str]:
    """Return a startup diagnostic when Qt's xcb cursor dependency is missing."""
    if not _needs_xcb_cursor_preflight(env):
        return None
    try:
        loader("libxcb-cursor.so.0")
    except OSError:
        return (
            "multihex-gui: Qt's xcb platform plugin requires libxcb-cursor.so.0.\n"
            "Install the native dependency, for example on Debian/Ubuntu:\n"
            "  sudo apt install libxcb-cursor0\n"
            "If you are running a Wayland session, you can also try:\n"
            "  QT_QPA_PLATFORM=wayland multihex-gui ...\n"
        )
    return None


# --------------------------------------------------------------------------- #
# PySide6 import guard. Like the TUI's textual guard, keep imports working (and
# --help functional) when PySide6 is absent; only main() needs it to actually run.
# --------------------------------------------------------------------------- #
try:
    from PySide6.QtCore import Qt, Signal
    from PySide6.QtGui import (
        QAction,
        QActionGroup,
        QColor,
        QFont,
        QFontDatabase,
        QFontMetrics,
        QPainter,
        QPalette,
    )
    from PySide6.QtWidgets import (
        QAbstractScrollArea,
        QApplication,
        QCheckBox,
        QComboBox,
        QDialog,
        QDialogButtonBox,
        QFileDialog,
        QFormLayout,
        QInputDialog,
        QLabel,
        QLineEdit,
        QMainWindow,
        QMessageBox,
        QPlainTextEdit,
        QSpinBox,
        QVBoxLayout,
    )

    _PYSIDE6_IMPORT_ERROR: Optional[BaseException] = None
except ImportError as exc:  # pragma: no cover - depends on environment
    _PYSIDE6_IMPORT_ERROR = exc


if _PYSIDE6_IMPORT_ERROR is None:

    class _AccentColors:
        """Accent colours for one background flavour (light or dark base).

        Base text/background always come from the widget palette; these are
        only the highlight accents, picked per use from the palette's base
        lightness (see ``_accents_for``) so the view stays legible under both
        light and dark system themes. Colours apply only when colour is on.
        """

        def __init__(
            self, *, offset, diff, dim, ref, warn, overlay_bg,
            zero, whitespace, printable,
        ) -> None:
            self.offset = offset          # offset address gutter
            self.diff = diff              # differing cells / DIFF marker
            self.dim = dim                # missing ("--") / SAME+MISSING markers
            self.ref = ref                # reference file's name
            self.warn = warn              # warning-state status text
            self.overlay_bg = overlay_bg  # layout-overlay background fill
            # Byte-class foreground (the lowest-priority tier; display-only).
            # OTHER/MISSING get no byte-class colour, mirroring the core/TUI.
            self.byte_class = {
                ByteClass.ZERO: zero,
                ByteClass.WHITESPACE: whitespace,
                ByteClass.PRINTABLE_ASCII: printable,
            }

    _ACCENTS_LIGHT = _AccentColors(
        offset=QColor(0x1F, 0x6F, 0xEB),
        diff=QColor(0xD7, 0x3A, 0x49),
        dim=QColor(0x8A, 0x91, 0x99),
        ref=QColor(0x8A, 0x63, 0xD2),
        warn=QColor(0x9A, 0x67, 0x00),
        overlay_bg=QColor(0xD2, 0xE3, 0xFC),
        zero=QColor(0x9A, 0xA0, 0xA6),
        whitespace=QColor(0x0F, 0x85, 0x96),
        printable=QColor(0x1A, 0x7F, 0x37),
    )
    _ACCENTS_DARK = _AccentColors(
        offset=QColor(0x58, 0xA6, 0xFF),
        diff=QColor(0xF8, 0x51, 0x49),
        dim=QColor(0x76, 0x7E, 0x87),
        ref=QColor(0xBC, 0x8C, 0xFF),
        warn=QColor(0xD2, 0x99, 0x22),
        overlay_bg=QColor(0x1F, 0x3A, 0x5C),
        zero=QColor(0x6E, 0x76, 0x81),
        whitespace=QColor(0x39, 0xC5, 0xCF),
        printable=QColor(0x3F, 0xB9, 0x50),
    )

    def _accents_for(palette) -> "_AccentColors":
        """The accent set matching a palette's base (light or dark) background."""
        dark = palette.color(QPalette.ColorRole.Base).lightness() < 128
        return _ACCENTS_DARK if dark else _ACCENTS_LIGHT

    # Search-match highlight: a filled background behind the matched cell (the
    # current match stronger than the others), with dark glyphs drawn on top.
    # Bright enough to read identically on light and dark bases, so it is not
    # part of the per-theme accent tables.
    _COLOR_SEARCH_BG = QColor(0xF2, 0xCC, 0x3D)      # other matches
    _COLOR_SEARCH_CUR_BG = QColor(0xFF, 0xA5, 0x00)  # current match
    _COLOR_SEARCH_FG = QColor(0x10, 0x10, 0x10)      # glyphs on a match highlight

    def _fixed_font() -> "QFont":
        """The platform's fixed-pitch font, sized just above the UI font.

        Used for the hex view and the text-report dialogs; UI chrome (labels,
        menus, buttons, status bar) stays in the proportional system font.
        """
        font = QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont)
        font.setStyleHint(QFont.StyleHint.Monospace)
        app_pt = QApplication.font().pointSize()
        font.setPointSize(app_pt + 1 if app_pt > 0 else 11)
        return font

    def _menu_key_hint(action_id: str) -> str:
        """Shortcut-column hint ("\\tkey") for a registry single-key action.

        Rendered through Qt's tab-in-text convention so the key shows in the
        menu's shortcut column WITHOUT registering a competing QShortcut --
        the central MainWindow.keyPressEvent dispatch stays the only handler
        for the registry keys.
        """
        for s in gui_shortcuts():
            if s.action_id != action_id:
                continue
            for key in s.gui_keys:
                if key.startswith("t:"):
                    return "\t" + key[2:]
            for key in s.gui_keys:
                if key.startswith("k:"):
                    return "\t" + key[2:]
        return ""

    class HexCompareView(QAbstractScrollArea):
        """Custom-painted, lazily-rendered comparison view.

        Renders only the visible blocks in :meth:`paintEvent` (never the whole
        range into one buffer). Block layout matches the shared text model: the
        offset rides the first file's row as a fixed-width left gutter, and the
        block's other rows are indented under it.

            0x00000000  fileA  00 01 02 ...  |....|
                        fileB  00 ff 02 ...  |....|
                               == != == ...          (omitted when markers are hidden)

        Cell colouring is the GUI's own scheme, anchored on the core markers:
        a column whose marker is not SAME is reddened, missing bytes are dimmed,
        and the reference file's name is emphasised. Geometry mirrors
        ``core.render_row_text`` (same columns), so it is semantically identical
        to the CLI/TUI even though it is painted, not printed.
        """

        viewChanged = Signal()

        # Breathing room between the viewport edge and the painted content.
        _MARGIN = 8

        def __init__(self, parent=None) -> None:
            super().__init__(parent)
            self.view: Optional[ViewState] = None
            self.files: List = []
            self.name_mode = "basename"
            self.name_width = 0
            self.ascii_on = True
            # Marker-text display mode: "single" / "repeat" / "none" (parity with
            # the TUI/CLI). Display-only; never affects marker computation,
            # only-diff, or search. "repeat" only differs from "single" in
            # side-by-side layout (see _paint_block).
            self.markers_mode = "single"
            # Display layout: "stacked" (one file per line) or "side-by-side"
            # (the per-file segments joined horizontally). Visual-only.
            self.layout_mode = "stacked"
            self.color_on = True
            self.byte_classes_on = False
            # Loaded layout overlay (None = none). Highlighting is gated on the
            # overlay being applicable, so a loaded-but-erroring overlay is kept
            # for "view current overlay" without ever highlighting.
            self.overlay: Optional[OverlayState] = None
            # Search-highlight state (driven by MainWindow; the view only renders).
            # ``search_current`` is the strongly-highlighted match; _search_covered
            # is the set of every matched (file_index, absolute_offset).
            self.search_matches: List[SearchMatch] = []
            self.search_current: Optional[SearchMatch] = None
            self._search_covered: set = set()
            self._char_w = 8
            self._line_h = 16
            self._ascent = 12
            # Horizontal scroll offset in *pixels* (the horizontal scrollbar's
            # value; the painter is translated left by it). Engaged whenever the
            # rendered content is wider than the viewport, in either layout -- so
            # a wide --width (stacked) or a side-by-side row no longer clips.
            self.h_offset_px = 0
            self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
            self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
            self.viewport().setAutoFillBackground(True)
            self._init_font()

        def _init_font(self) -> None:
            font = _fixed_font()
            self.setFont(font)
            fm = QFontMetrics(font)
            self._char_w = max(1, fm.horizontalAdvance("0"))
            self._line_h = max(1, fm.height())
            self._ascent = fm.ascent()

        # -- model binding -------------------------------------------------- #
        def set_model(
            self, model: HexModel, files: List, name_mode: str, *, only_diff: bool
        ) -> None:
            self.files = files
            self.name_mode = name_mode
            self.name_width = name_column_width(files, name_mode) if files else 0
            self.view = ViewState(model, only_diff=only_diff)
            self.h_offset_px = 0  # a freshly loaded set starts un-scrolled
            self._sync_scrollbar()
            self.viewport().update()

        # -- geometry ------------------------------------------------------- #
        def _lines_per_block(self) -> int:
            # Mirrors tui.HexView._lines_per_block so the page math matches the
            # other interactive frontend. The offset rides the first content line
            # as a left gutter; a trailing blank line separates blocks.
            nfiles = len(self.files) if self.files else 1
            if self.layout_mode == "side-by-side":
                # All files share one content line; "repeat" adds a marker line
                # ("single" draws its strip inline on the content line).
                content = 1
                marker = 1 if self.markers_mode == "repeat" else 0
            else:
                content = nfiles
                marker = 0 if self.markers_mode == "none" else 1
            return content + marker + 1

        def _block_px(self) -> int:
            return self._lines_per_block() * self._line_h

        # -- horizontal geometry (character units; mirrors core.render_row_text) - #
        def _seg_width_chars(self) -> int:
            """Width in characters of one file's segment (name + hex + ASCII)."""
            width = self.view.model.width if self.view is not None else 16
            chars = self.name_width + 2 + (3 * width - 1)
            if self.ascii_on:
                chars += width + 4  # "  |" + ascii + "|"
            return chars

        def _content_width_chars(self) -> int:
            """Width in characters of the widest line a block paints.

            Deterministic from the layout, width, name width, ASCII/marker state,
            and file count (the model uses length=None, so every row is full
            width). Drives the horizontal scrollbar range.
            """
            if self.view is None or not self.files:
                return 0
            width = self.view.model.width
            nfiles = len(self.files)
            seg = self._seg_width_chars()
            if self.layout_mode == "side-by-side":
                base = OFFSET_LABEL_WIDTH + 2  # gutter + leading gap
                if self.markers_mode == "single":
                    base += (3 * width - 1) + 2  # inline marker strip + gap
                return base + nfiles * seg + 3 * (nfiles - 1)
            # Stacked: a file line is the widest (the marker line is shorter).
            return OFFSET_LABEL_WIDTH + 2 + seg

        def _content_width_px(self) -> int:
            chars = self._content_width_chars()
            if chars <= 0:
                return 0
            return chars * self._char_w + 2 * self._MARGIN

        def _page_rows(self) -> int:
            block = self._block_px()
            height = max(0, self.viewport().height() - self._MARGIN)
            return max(1, height // block) if block else 1

        # -- scrollbar wiring ----------------------------------------------- #
        def _sync_scrollbar(self) -> None:
            self._sync_h_scrollbar()
            sb = self.verticalScrollBar()
            if self.view is None:
                sb.setRange(0, 0)
                sb.setPageStep(1)
                return
            page = self._page_rows()
            self.view.clamp_top(page)
            sb.setRange(0, self.view.max_top(page))
            sb.setPageStep(page)
            sb.setSingleStep(1)
            sb.setValue(self.view.top)

        def _sync_h_scrollbar(self) -> None:
            """Configure the horizontal bar from the content vs viewport width.

            Range is the pixel overflow; a press of the bar moves one character,
            a page moves a viewport. ``h_offset_px`` is re-clamped so a layout or
            width change that shrinks the content cannot leave it scrolled past
            the end.
            """
            sb = self.horizontalScrollBar()
            viewport_w = self.viewport().width()
            overflow = max(0, self._content_width_px() - viewport_w)
            sb.setRange(0, overflow)
            sb.setPageStep(max(1, viewport_w))
            sb.setSingleStep(self._char_w)
            self.h_offset_px = max(0, min(self.h_offset_px, overflow))
            sb.setValue(self.h_offset_px)

        def scrollContentsBy(self, dx: int, dy: int) -> None:
            # Custom paint: never bit-blt; just track the new scroll positions and
            # repaint. Both bars feed the painter (top row + horizontal pixels).
            if self.view is not None:
                self.view.top = self.verticalScrollBar().value()
            self.h_offset_px = self.horizontalScrollBar().value()
            self.viewport().update()
            self.viewChanged.emit()

        def resizeEvent(self, event) -> None:
            super().resizeEvent(event)
            self._sync_scrollbar()
            self.viewport().update()

        # -- navigation ----------------------------------------------------- #
        def scroll_rows(self, delta: int) -> None:
            if self.view is None:
                return
            page = self._page_rows()
            self.view.top = max(0, min(self.view.top + delta, self.view.max_top(page)))
            self._sync_scrollbar()
            self.viewport().update()
            self.viewChanged.emit()

        def page_by(self, direction: int) -> None:
            self.scroll_rows(direction * self._page_rows())

        def scroll_h(self, delta_chars: int) -> None:
            """Scroll horizontally by ``delta_chars`` characters (left/right keys).

            Moves the horizontal scrollbar (which drives the painter); a no-op
            when the content fits, since the bar's range is then 0. Matches the
            TUI's 8-characters-per-press step.
            """
            sb = self.horizontalScrollBar()
            sb.setValue(sb.value() + delta_chars * self._char_w)
            # setValue clamps to the bar range; scrollContentsBy tracks the result.

        def to_home(self) -> None:
            if self.view is None:
                return
            self.view.top = 0
            self._sync_scrollbar()
            self.viewport().update()
            self.viewChanged.emit()

        def to_end(self) -> None:
            if self.view is None:
                return
            self.view.top = self.view.max_top(self._page_rows())
            self._sync_scrollbar()
            self.viewport().update()
            self.viewChanged.emit()

        def jump_to_offset(self, offset: int) -> None:
            if self.view is None:
                return
            self.view.top = self.view.position_for_offset(offset)
            self._sync_scrollbar()
            self.viewport().update()
            self.viewChanged.emit()

        def keyPressEvent(self, event) -> None:
            # Single-key shortcuts are dispatched centrally from the shared
            # registry in MainWindow.keyPressEvent. Ignore here so every key
            # bubbles up to the parent window (do NOT call super(), which would
            # let QAbstractScrollArea consume arrows/page keys for its scrollbar).
            event.ignore()

        def wheelEvent(self, event) -> None:
            # Custom row-based paint: map the wheel delta to whole rows so mouse
            # (120-unit notches) and trackpad (pixel-delta) wheels both scroll
            # predictably, instead of QAbstractScrollArea's pixel-oriented default.
            if self.view is None:
                super().wheelEvent(event)
                return
            delta = event.angleDelta().y()
            if delta == 0:
                return
            notches = delta / 120.0           # one mouse notch == 120 units
            rows = int(notches * 3)           # ~3 rows per notch
            if rows == 0:                     # tiny/high-res deltas still move a row
                rows = 1 if notches > 0 else -1
            self.scroll_rows(-rows)           # wheel-up (positive delta) -> earlier rows
            event.accept()

        # -- display toggles ------------------------------------------------ #
        def set_ascii(self, on: bool) -> None:
            self.ascii_on = on
            self._sync_scrollbar()  # segment (content) width changed
            self.viewport().update()

        def set_color_on(self, on: bool) -> None:
            self.color_on = on
            self.viewport().update()

        def set_byte_classes(self, on: bool) -> None:
            self.byte_classes_on = on
            self.viewport().update()

        def set_search(
            self, matches: List[SearchMatch], current_index: Optional[int]
        ) -> None:
            """Install a result set and recompute the highlight coverage."""
            self.search_matches = matches
            covered: set = set()
            for m in matches:
                for off in range(m.offset, m.offset + m.length):
                    covered.add((m.file_index, off))
            self._search_covered = covered
            self.set_current_match(current_index)

        def set_current_match(self, index: Optional[int]) -> None:
            """Point the strong highlight at result ``index`` (or clear it)."""
            if self.search_matches and index is not None:
                self.search_current = self.search_matches[index]
            else:
                self.search_current = None
            self.viewport().update()

        def set_markers_mode(self, mode: str) -> None:
            self.markers_mode = mode
            # Block height and content width both depend on the marker mode.
            self._sync_scrollbar()
            self.viewport().update()

        def set_layout(self, mode: str) -> None:
            self.layout_mode = mode
            self.h_offset_px = 0  # a fresh layout starts un-scrolled
            self._sync_scrollbar()
            self.viewport().update()

        def cycle_layout(self) -> None:
            self.set_layout(
                "side-by-side" if self.layout_mode == "stacked" else "stacked"
            )

        def set_name_mode(self, mode: str) -> None:
            self.name_mode = mode
            self.name_width = name_column_width(self.files, mode) if self.files else 0
            self._sync_scrollbar()  # name column width changed -> content width
            self.viewport().update()

        def set_overlay(self, overlay: Optional[OverlayState]) -> None:
            self.overlay = overlay
            self.viewport().update()

        def set_only_diff(self, on: bool) -> None:
            if self.view is None:
                return
            self.view.set_only_diff(on, page_rows=self._page_rows())
            self._sync_scrollbar()
            self.viewport().update()

        def set_ref(self, ref: Optional[int]) -> None:
            if self.view is None:
                return
            self.view.set_ref(ref, page_rows=self._page_rows())
            self._sync_scrollbar()
            self.viewport().update()

        # -- rendering ------------------------------------------------------ #
        def _text_color(self) -> "QColor":
            return self.palette().color(QPalette.ColorRole.Text)

        def _accents(self) -> "_AccentColors":
            """The accent set matching the current (light or dark) palette."""
            return _accents_for(self.palette())

        def _cell_color(
            self,
            value: Optional[int],
            marker: Marker,
            offset: Optional[int] = None,
            fi: Optional[int] = None,
        ) -> "QColor":
            # Priority mirrors the CLI/TUI: missing > current match > other match
            # > diff > layout overlay > byte class > normal text. A missing byte is
            # never part of a match, so it short-circuits before any search branch.
            # Search/overlay/byte-class tiers apply only to present cells; overlay
            # and byte class only to non-diff cells, so search and diff stay most
            # visible. The overlay tier shows as a cell *background* (_cell_bg);
            # a covered cell keeps the plain foreground so the fill is the one
            # overlay signal (and never collides with a byte-class colour).
            if not self.color_on:
                return self._text_color()
            acc = self._accents()
            if value is None:
                return acc.dim
            if fi is not None and offset is not None and self._is_match(fi, offset):
                return _COLOR_SEARCH_FG
            if marker is not Marker.SAME:
                return acc.diff
            if offset is not None and self.overlay is not None and self.overlay.covers(offset):
                return self._text_color()
            if self.byte_classes_on:
                bc = acc.byte_class.get(classify_byte(value))
                if bc is not None:
                    return bc
            return self._text_color()

        def _is_match(self, fi: int, offset: int) -> bool:
            return (fi, offset) in self._search_covered

        def _cell_bg(self, fi: int, offset: int, marker: Marker) -> Optional["QColor"]:
            """Background fill for one cell, or None.

            Search matches win (current match strongest); below them a layout-
            overlay range fills covered SAME cells only, so diff/missing
            emphasis stays untouched -- the same tier order the CLI/TUI use.
            """
            if not self.color_on:
                return None
            cur = self.search_current
            if (
                cur is not None
                and fi == cur.file_index
                and cur.offset <= offset < cur.offset + cur.length
            ):
                return _COLOR_SEARCH_CUR_BG
            if (fi, offset) in self._search_covered:
                return _COLOR_SEARCH_BG
            if (
                marker is Marker.SAME
                and self.overlay is not None
                and self.overlay.covers(offset)
            ):
                return self._accents().overlay_bg
            return None

        def _marker_color(self, marker: Marker) -> "QColor":
            if not self.color_on:
                return self._text_color()
            if marker is Marker.DIFF:
                return self._accents().diff
            # SAME recedes (the TUI leaves it unstyled); MISSING is dim too --
            # the "--" glyph itself already tells the two apart.
            return self._accents().dim

        def paintEvent(self, event) -> None:
            painter = QPainter(self.viewport())
            painter.setFont(self.font())
            pal = self.palette()
            painter.fillRect(self.viewport().rect(), pal.color(QPalette.ColorRole.Base))

            if self.view is None or not self.files:
                # UI text, not data: the proportional system font, in the
                # palette's muted placeholder colour.
                painter.setFont(QFont())
                painter.setPen(pal.color(QPalette.ColorRole.PlaceholderText))
                painter.drawText(
                    self.viewport().rect(),
                    Qt.AlignmentFlag.AlignCenter,
                    "No files loaded — use File ▸ Open…",
                )
                painter.end()
                return

            # Shift left by the horizontal scroll offset so a wide row (a large
            # --width in stacked, or a side-by-side row) scrolls instead of
            # clipping. h_offset_px is 0 (and the bar hidden) when content fits.
            painter.translate(self._MARGIN - self.h_offset_px, self._MARGIN)
            view = self.view
            model = view.model
            count = view.visible_count
            block_px = self._block_px()
            # One extra block so a partially-visible bottom block still draws.
            nblocks = self._page_rows() + 1
            for b in range(nblocks):
                pos = view.top + b
                if pos >= count:
                    break
                row = model.build_row(view.row_index_at(pos))
                self._paint_block(painter, row, model, b * block_px)
            painter.end()

        def _paint_block(self, painter, row, model, top: int) -> None:
            cw = self._char_w
            line_h = self._line_h
            ascent = self._ascent
            width = model.width
            text_color = self._text_color()
            acc = self._accents()

            def draw(col: int, line: int, s: str, color) -> None:
                painter.setPen(color)
                painter.drawText(int(col * cw), int(top + line * line_h + ascent), s)

            def fill(col: int, line: int, ncols: int, color) -> None:
                painter.fillRect(
                    int(col * cw), int(top + line * line_h),
                    int(ncols * cw), int(line_h), color,
                )

            def paint_segment(line: int, name_col: int, fi: int, f, row_bytes) -> None:
                """Paint one file's name + hex + optional ASCII at ``name_col``.

                Layout-agnostic: stacked passes ``line=fi, name_col`` after the
                gutter; side-by-side passes ``line=0`` and each segment's column.
                Cell styling flows through _cell_bg / _cell_color, so diff /
                search / overlay / byte-class priority is identical in both.
                """
                name = f.display_name(self.name_mode).ljust(self.name_width)
                name_color = (
                    acc.ref if (self.color_on and model.ref == fi) else text_color
                )
                draw(name_col, line, name, name_color)
                hex_col = name_col + self.name_width + 2
                for c in range(width):
                    marker = row.markers[c]
                    off = row.offset + c
                    bg = self._cell_bg(fi, off, marker)
                    if bg is not None:
                        fill(hex_col + c * 3, line, 2, bg)
                    draw(hex_col + c * 3, line, format_byte(row_bytes[c]),
                         self._cell_color(row_bytes[c], marker, off, fi))
                if self.ascii_on:
                    acol = hex_col + width * 3 + 1  # past hex + "  |"
                    draw(acol, line, "|", text_color)
                    for c in range(width):
                        marker = row.markers[c]
                        off = row.offset + c
                        bg = self._cell_bg(fi, off, marker)
                        if bg is not None:
                            fill(acol + 1 + c, line, 1, bg)
                        draw(acol + 1 + c, line, format_ascii_char(row_bytes[c]),
                             self._cell_color(row_bytes[c], marker, off, fi))
                    draw(acol + 1 + width, line, "|", text_color)

            def paint_strip(line: int, col: int) -> None:
                for c in range(width):
                    marker = row.markers[c]
                    draw(col + c * 3, line, format_marker(marker),
                         self._marker_color(marker))

            # The offset rides the first content line as a fixed-width left gutter.
            draw(0, 0, offset_label(row.offset),
                 acc.offset if self.color_on else text_color)

            if self.layout_mode == "side-by-side":
                # Geometry mirrors core.render_row_text(layout="side-by-side"):
                # "single" draws one strip as a left prefix column on the content
                # line; "repeat" repeats it under each segment's hex; "none" hides
                # it. Segments join with a 3-space gap.
                strip_col = OFFSET_LABEL_WIDTH + 2
                seg_w = self._seg_width_chars()
                first_col = strip_col + (
                    (3 * width - 1) + 2 if self.markers_mode == "single" else 0
                )
                seg_cols = [
                    first_col + i * (seg_w + 3) for i in range(len(model.files))
                ]
                if self.markers_mode == "single":
                    paint_strip(0, strip_col)
                for fi, (f, row_bytes) in enumerate(zip(model.files, row.cells)):
                    paint_segment(0, seg_cols[fi], fi, f, row_bytes)
                if self.markers_mode == "repeat":
                    for fi in range(len(model.files)):
                        paint_strip(1, seg_cols[fi] + self.name_width + 2)
            else:
                for fi, (f, row_bytes) in enumerate(zip(model.files, row.cells)):
                    paint_segment(fi, OFFSET_LABEL_WIDTH + 2, fi, f, row_bytes)
                # In stacked, "single" and "repeat" both draw the one strip
                # (repeat == single when stacked); only "none" hides it.
                if self.markers_mode != "none":
                    paint_strip(
                        len(model.files),
                        OFFSET_LABEL_WIDTH + marker_prefix_width(self.name_width),
                    )

    class MainWindow(QMainWindow):
        """Top-level window: menus, status bar, and the comparison view."""

        def __init__(
            self,
            *,
            offset: int = 0,
            width: int = 16,
            ref: Optional[int] = None,
            name_mode: str = "basename",
            ascii_on: bool = True,
            only_diff: bool = False,
            markers: str = "single",
            layout: str = "stacked",
        ) -> None:
            super().__init__()
            self.setWindowTitle("multihex-gui")
            self.setMinimumSize(640, 400)
            self._offset = offset
            self._width = width
            self._start_ref = ref
            self.name_mode = name_mode
            self.files: List = []
            self.model: Optional[HexModel] = None
            # Loaded layout overlay (None = none). Session-only; overlay paths are
            # never persisted. Kept even when not applicable so "View current
            # overlay" can show its diagnostics.
            self.overlay: Optional[OverlayState] = None
            self._message_boxes: List = []  # keep non-modal dialogs alive

            self.view_widget = HexCompareView(self)
            self.view_widget.ascii_on = ascii_on
            self.view_widget.markers_mode = markers
            self.view_widget.layout_mode = layout
            self.view_widget.name_mode = name_mode
            self.setCentralWidget(self.view_widget)
            self.view_widget.viewChanged.connect(self._update_status)

            self._start_only_diff = only_diff
            # Search state mirrors the TUI app; the view only renders highlights.
            self.search_query: Optional["SearchQuery"] = None
            self.search_matches: List[SearchMatch] = []
            self.search_index: Optional[int] = None
            self.search_error: Optional[str] = None
            self.text_search_ignore_case = False
            self._build_menus()
            self._build_key_dispatch()
            self._build_status_bar()
            self.resize(960, 640)
            self._update_status()
            self._update_search_status()

        # -- single-key shortcut dispatch (shared registry) ----------------- #
        def _build_key_dispatch(self) -> None:
            """Wire the shared registry to GUI slots.

            ``_action_slots`` maps every GUI-applicable ``action_id`` to a bound
            zero-arg callable; ``trigger_action`` is the testable seam. The key
            lookups are built straight from the registry so the GUI keymap cannot
            drift from the TUI's. Checkable toggles map to ``QAction.toggle`` so a
            keypress flips the menu item *and* fires its slot.
            """
            vw = self.view_widget
            self._action_slots: dict = {
                "quit": self.close,
                "next_row": lambda: vw.scroll_rows(1),
                "prev_row": lambda: vw.scroll_rows(-1),
                "next_page": lambda: vw.page_by(1),
                "prev_page": lambda: vw.page_by(-1),
                "home": self._go_home,
                "end": self._go_end,
                "jump": self._jump_dialog,
                "choose_ref": self._choose_ref_dialog,
                "toggle_ascii": self.act_ascii.toggle,
                "toggle_diff": self.act_diff.toggle,
                "toggle_color": self.act_color.toggle,
                "toggle_byte_classes": self.act_byte_classes.toggle,
                "cycle_layout": self._cycle_layout,
                "cycle_markers": self._cycle_markers,
                "scroll_horizontal": lambda: vw.scroll_h(self._h_dir * 8),
                "load_overlay": self._overlay_load_dialog,
                "view_overlay": self._overlay_view,
                "open_settings": self._open_settings_dialog,
                "search_text": self._search_text_dialog,
                "search_hex": self._search_hex_dialog,
                "next_match": self.search_next,
                "prev_match": self.search_prev,
                "help": self._show_help_dialog,
            }
            # Direction for the single ``scroll_horizontal`` action: the registry
            # maps both Left and Right to it (one entry, like the TUI), so
            # keyPressEvent sets this before dispatch. Default right.
            self._h_dir = 1
            self._key_text_actions: dict = gui_text_map()
            self._key_code_actions: dict = {
                getattr(Qt.Key, f"Key_{name}"): aid
                for name, aid in gui_key_names().items()
            }

        def trigger_action(self, action_id: str) -> bool:
            """Invoke the slot for ``action_id`` (the registry-driven seam)."""
            slot = self._action_slots.get(action_id)
            if slot is None:
                return False
            slot()
            return True

        def keyPressEvent(self, event) -> None:
            # Central single-key dispatch. Named keys (Down/PageUp/Home/End) have an
            # empty .text(), so resolve by key-code first, then by character. Modal
            # dialogs grab focus, so typing in a search box never reaches here.
            # Left/Right share the one scroll_horizontal action; record direction.
            if event.key() == Qt.Key.Key_Left:
                self._h_dir = -1
            elif event.key() == Qt.Key.Key_Right:
                self._h_dir = 1
            aid = self._key_code_actions.get(event.key())
            if aid is None:
                ch = event.text()
                if ch:
                    aid = self._key_text_actions.get(ch)
            if aid is not None and self.trigger_action(aid):
                event.accept()
                return
            super().keyPressEvent(event)

        # -- menus ---------------------------------------------------------- #
        def _build_menus(self) -> None:
            mb = self.menuBar()

            filem = mb.addMenu("&File")
            act_open = QAction("&Open…", self)
            act_open.setShortcut("Ctrl+O")
            act_open.triggered.connect(self._open_dialog)
            filem.addAction(act_open)
            filem.addSeparator()
            act_quit = QAction("&Quit", self)
            act_quit.setShortcut("Ctrl+Q")
            act_quit.triggered.connect(self.close)
            filem.addAction(act_quit)

            viewm = mb.addMenu("&View")
            self.act_ascii = QAction(
                "&ASCII gutter" + _menu_key_hint("toggle_ascii"), self
            )
            self.act_ascii.setCheckable(True)
            self.act_ascii.setChecked(self.view_widget.ascii_on)
            self.act_ascii.toggled.connect(self._on_toggle_ascii)
            viewm.addAction(self.act_ascii)
            self.act_diff = QAction(
                "Only &differing rows" + _menu_key_hint("toggle_diff"), self
            )
            self.act_diff.setCheckable(True)
            self.act_diff.setChecked(self._start_only_diff)
            self.act_diff.toggled.connect(self._on_toggle_diff)
            viewm.addAction(self.act_diff)
            self.act_layout = QAction(
                "Side-by-side &layout" + _menu_key_hint("cycle_layout"), self
            )
            self.act_layout.setCheckable(True)
            self.act_layout.setChecked(self.view_widget.layout_mode == "side-by-side")
            self.act_layout.toggled.connect(self._on_toggle_layout)
            viewm.addAction(self.act_layout)
            # Markers are tri-state (single / repeat / none), matching the TUI/CLI;
            # the 'm' key cycles them and keeps this radio group in sync.
            self.markers_menu = viewm.addMenu(
                "&Markers" + _menu_key_hint("cycle_markers")
            )
            markerm = self.markers_menu
            self.markers_group = QActionGroup(self)
            self.markers_group.setExclusive(True)
            for label, mode in (
                ("Single", "single"), ("Repeat", "repeat"), ("None", "none"),
            ):
                a = QAction(label, self)
                a.setCheckable(True)
                a.setData(mode)
                a.setChecked(self.view_widget.markers_mode == mode)
                self.markers_group.addAction(a)
                markerm.addAction(a)
            self.markers_group.triggered.connect(self._on_markers_changed)
            self.act_color = QAction(
                "&Color highlighting" + _menu_key_hint("toggle_color"), self
            )
            self.act_color.setCheckable(True)
            self.act_color.setChecked(self.view_widget.color_on)
            self.act_color.toggled.connect(self._on_toggle_color)
            viewm.addAction(self.act_color)
            self.act_byte_classes = QAction(
                "&Byte-class highlighting" + _menu_key_hint("toggle_byte_classes"),
                self,
            )
            self.act_byte_classes.setCheckable(True)
            self.act_byte_classes.setChecked(self.view_widget.byte_classes_on)
            self.act_byte_classes.toggled.connect(self._on_toggle_byte_classes)
            viewm.addAction(self.act_byte_classes)
            viewm.addSeparator()
            act_options = QAction("&Options…" + _menu_key_hint("open_settings"), self)
            act_options.triggered.connect(self._open_settings_dialog)
            viewm.addAction(act_options)
            viewm.addSeparator()
            namem = viewm.addMenu("File &names")
            self.names_group = QActionGroup(self)
            self.names_group.setExclusive(True)
            for label, mode in (("Basename", "basename"), ("Full path", "path")):
                a = QAction(label, self)
                a.setCheckable(True)
                a.setData(mode)
                a.setChecked(self.name_mode == mode)
                self.names_group.addAction(a)
                namem.addAction(a)
            self.names_group.triggered.connect(self._on_names_changed)

            navm = mb.addMenu("&Navigate")
            act_jump = QAction("&Jump to offset…", self)
            act_jump.setShortcut("Ctrl+G")
            act_jump.triggered.connect(self._jump_dialog)
            navm.addAction(act_jump)
            navm.addSeparator()
            act_home = QAction("Go to &start", self)
            act_home.setShortcut("Ctrl+Home")
            act_home.triggered.connect(self._go_home)
            navm.addAction(act_home)
            act_end = QAction("Go to &end", self)
            act_end.setShortcut("Ctrl+End")
            act_end.triggered.connect(self._go_end)
            navm.addAction(act_end)

            searchm = mb.addMenu("&Search")
            act_find = QAction("Find &text…", self)
            act_find.setShortcut("Ctrl+F")
            act_find.triggered.connect(self._search_text_dialog)
            searchm.addAction(act_find)
            act_find_hex = QAction("Find &hex…" + _menu_key_hint("search_hex"), self)
            act_find_hex.triggered.connect(self._search_hex_dialog)
            searchm.addAction(act_find_hex)
            searchm.addSeparator()
            act_next = QAction("&Next match" + _menu_key_hint("next_match"), self)
            act_next.triggered.connect(self.search_next)
            searchm.addAction(act_next)
            act_prev = QAction("&Previous match" + _menu_key_hint("prev_match"), self)
            act_prev.triggered.connect(self.search_prev)
            searchm.addAction(act_prev)

            self.comparem = mb.addMenu("&Compare")
            self.ref_group = QActionGroup(self)
            self.ref_group.setExclusive(True)
            self.ref_group.triggered.connect(self._on_ref_changed)
            self._rebuild_ref_menu()

            overlaym = mb.addMenu("&Overlay")
            act_ov_load = QAction(
                "&Load/change layout overlay…" + _menu_key_hint("load_overlay"), self
            )
            act_ov_load.triggered.connect(self._overlay_load_dialog)
            overlaym.addAction(act_ov_load)
            self.act_overlay_clear = QAction("&Clear overlay", self)
            self.act_overlay_clear.triggered.connect(self._overlay_clear)
            overlaym.addAction(self.act_overlay_clear)
            overlaym.addSeparator()
            act_ov_view = QAction(
                "&View current overlay…" + _menu_key_hint("view_overlay"), self
            )
            act_ov_view.triggered.connect(self._overlay_view)
            overlaym.addAction(act_ov_view)

            helpm = mb.addMenu("&Help")
            act_keys = QAction(
                "&Keyboard shortcuts…" + _menu_key_hint("help"), self
            )
            act_keys.triggered.connect(self._show_help_dialog)
            helpm.addAction(act_keys)

        def _rebuild_ref_menu(self) -> None:
            """(Re)populate the Compare menu with the reference radio choices."""
            for a in list(self.ref_group.actions()):
                self.ref_group.removeAction(a)
            self.comparem.clear()
            act_pick = QAction(
                "Choose &reference…" + _menu_key_hint("choose_ref"), self.comparem
            )
            act_pick.triggered.connect(self._choose_ref_dialog)
            self.comparem.addAction(act_pick)
            self.comparem.addSeparator()
            cur_ref = self.model.ref if self.model is not None else None
            # Parent the radio actions to the menu so comparem.clear() reclaims
            # them on every rebuild (parenting to MainWindow would leak them).
            a_all = QAction("All agree (no reference)", self.comparem)
            a_all.setCheckable(True)
            a_all.setData(None)
            a_all.setChecked(cur_ref is None)
            self.ref_group.addAction(a_all)
            self.comparem.addAction(a_all)
            if self.files:
                self.comparem.addSeparator()
                for i, f in enumerate(self.files):
                    a = QAction(f"[{i}] {f.display_name(self.name_mode)}", self.comparem)
                    a.setCheckable(True)
                    a.setData(i)
                    a.setChecked(cur_ref == i)
                    self.ref_group.addAction(a)
                    self.comparem.addAction(a)

        # -- file loading --------------------------------------------------- #
        def load_paths(self, paths: Sequence[str]) -> bool:
            try:
                files = load_files(list(paths))
            except OSError as exc:
                sys.stderr.write(f"multihex-gui: {exc}\n")
                QMessageBox.warning(self, "Open files", f"Could not open files:\n{exc}")
                return False
            ref = clamp_ref(self._start_ref, len(files))
            # Mirror the CLI/TUI: don't silently swallow a bad --ref. clamp_ref
            # coerces an out-of-range index to None ("no reference") so the GUI
            # keeps running; warn so a typo (e.g. --ref 9) isn't lost.
            if self._start_ref is not None and ref is None:
                sys.stderr.write(
                    f"multihex-gui: --ref {self._start_ref} out of range "
                    f"(have {len(files)} files); ignoring (no reference)\n"
                )
            try:
                model = HexModel(
                    files,
                    start_offset=self._offset,
                    width=self._width,
                    ref=ref,
                    length=None,
                )
            except ValueError as exc:
                sys.stderr.write(f"multihex-gui: {exc}\n")
                QMessageBox.warning(self, "Open files", str(exc))
                return False
            self.files = files
            self.model = model
            # A previously loaded overlay was validated against the old files;
            # drop it rather than silently re-applying it to a different binary.
            self.overlay = None
            self.view_widget.set_overlay(None)
            # Likewise drop any search results computed against the old files.
            self._reset_search()
            self.view_widget.set_model(
                model, files, self.name_mode, only_diff=self.act_diff.isChecked()
            )
            self._rebuild_ref_menu()
            self._update_title()
            self._update_status()
            return True

        # -- menu handlers -------------------------------------------------- #
        def _open_dialog(self) -> None:
            paths, _ = QFileDialog.getOpenFileNames(self, "Open files to compare")
            if paths:
                self.load_paths(paths)

        def _on_toggle_ascii(self, checked: bool) -> None:
            self.view_widget.set_ascii(checked)
            self._update_status()

        def _on_toggle_diff(self, checked: bool) -> None:
            self.view_widget.set_only_diff(checked)
            self._update_status()

        def _on_markers_changed(self, action) -> None:
            self.view_widget.set_markers_mode(action.data())
            self._update_status()

        def _on_toggle_layout(self, checked: bool) -> None:
            self.view_widget.set_layout("side-by-side" if checked else "stacked")
            self._update_status()

        def _on_toggle_color(self, checked: bool) -> None:
            self.view_widget.set_color_on(checked)
            self._update_status()

        def _on_toggle_byte_classes(self, checked: bool) -> None:
            self.view_widget.set_byte_classes(checked)
            self._update_status()

        def _cycle_markers(self) -> None:
            """Rotate the marker mode single -> repeat -> none (the 'm' key).

            Drives the Markers radio group so the menu and view stay in sync.
            """
            order = ("single", "repeat", "none")
            cur = self.view_widget.markers_mode
            nxt = order[(order.index(cur) + 1) % len(order)]
            target = next(
                (a for a in self.markers_group.actions() if a.data() == nxt), None
            )
            if target is not None:
                target.trigger()  # checks it and fires _on_markers_changed

        def _cycle_layout(self) -> None:
            """Flip stacked <-> side-by-side (the 'v' key); keep the menu in sync."""
            self.act_layout.toggle()

        def _on_names_changed(self, action) -> None:
            self.name_mode = action.data()
            self.view_widget.set_name_mode(self.name_mode)
            self._rebuild_ref_menu()  # labels depend on the name mode
            self._update_status()

        def _on_ref_changed(self, action) -> None:
            if self.model is None:
                return
            data = action.data()
            self.view_widget.set_ref(None if data is None else int(data))
            self._update_status()

        def _go_home(self) -> None:
            self.view_widget.to_home()
            self._update_status()

        def _go_end(self) -> None:
            self.view_widget.to_end()
            self._update_status()

        def _jump_dialog(self) -> None:
            if self.model is None:
                return
            m = self.model
            if m.row_count:
                last = m.row_offset(m.row_count - 1) + m.width - 1
                prompt = f"Offset (0x{m.start_offset:x} - 0x{last:x}, e.g. 0x400):"
            else:
                prompt = "Offset (e.g. 0x400, 1024):"
            text, ok = QInputDialog.getText(self, "Jump to offset", prompt)
            if not ok or not text.strip():
                return
            try:
                offset = parse_int(text.strip())
            except ValueError:
                QMessageBox.warning(self, "Jump to offset", f"Invalid offset: {text!r}")
                return
            self.view_widget.jump_to_offset(offset)
            self._update_status()

        def _choose_ref_dialog(self) -> None:
            """Pick the reference file (the GUI-native equivalent of the TUI 'r')."""
            if self.model is None or not self.files:
                return
            labels = ["All agree (no reference)"]
            labels += [
                f"[{i}] {f.display_name(self.name_mode)}"
                for i, f in enumerate(self.files)
            ]
            cur = self.model.ref
            current_row = 0 if cur is None else cur + 1
            choice, ok = QInputDialog.getItem(
                self, "Reference file", "Compare every file against:",
                labels, current_row, editable=False,
            )
            if not ok:
                return
            idx = labels.index(choice)
            ref = None if idx == 0 else idx - 1
            self.view_widget.set_ref(ref)
            self._rebuild_ref_menu()  # keep the Compare radio group in sync
            self._update_status()

        # -- search (reuses the core engine; the GUI renders/navigates only) - #
        def _reset_search(self) -> None:
            self.search_query = None
            self.search_matches = []
            self.search_index = None
            self.search_error = None
            self.view_widget.set_search([], None)
            self._update_search_status()

        def _search_text_dialog(self) -> None:
            if self.model is None:
                return
            dlg = _TextSearchDialog(self.text_search_ignore_case, self)
            if dlg.exec():
                text, ignore_case = dlg.result_value()
                self.text_search_ignore_case = bool(ignore_case)
                self.run_search("text", text, ignore_case=ignore_case)

        def _search_hex_dialog(self) -> None:
            if self.model is None:
                return
            dlg = _HexSearchDialog(self)
            if dlg.exec():
                self.run_search("hex", dlg.result_value())

        def run_search(
            self, mode: str, value: Optional[str], *, ignore_case: bool = False
        ) -> None:
            """Build a query, replace search state, and jump to the first match.

            Mirrors ``tui._run_search``: invalid input sets an error status and
            never crashes; an empty/cancelled value leaves the previous search
            untouched. Factored out of the dialog so tests drive it directly.
            """
            if self.model is None or value is None:
                return
            if mode == "text":
                text = value
                if text == "":
                    return
            else:
                text = value.strip()
                if not text:
                    return
            try:
                if mode == "text":
                    query = make_text_query(text, case_sensitive=not ignore_case)
                else:
                    query = make_hex_query(text)
            except SearchError as exc:
                self.search_error = str(exc)
                self.search_query = None
                self.search_matches = []
                self.search_index = None
                self.view_widget.set_search([], None)
                self._update_search_status()
                return
            self.search_error = None
            self.search_query = query
            self.search_matches = search_files(
                self.model.files, query, model=self.model
            )
            self.search_index = first_match_index(self.search_matches)
            self.view_widget.set_search(self.search_matches, self.search_index)
            if self.search_index is not None:
                self._jump_to_current_match()
            self._update_search_status()

        def search_next(self) -> None:
            self._step_match(next_match_index)

        def search_prev(self) -> None:
            self._step_match(prev_match_index)

        def _step_match(self, picker) -> None:
            if not self.search_matches:
                return
            self.search_index = picker(self.search_matches, self.search_index or 0)
            self.view_widget.set_current_match(self.search_index)
            self._jump_to_current_match()
            self._update_search_status()

        def _jump_to_current_match(self) -> None:
            if self.search_index is None:
                return
            match = self.search_matches[self.search_index]
            self.view_widget.jump_to_offset(match.offset)

        # -- options / help ------------------------------------------------- #
        def set_row_width(self, width: int) -> None:
            """Change bytes-per-row live (TUI settings-pane parity).

            Keeps the top row anchored at (roughly) the same offset, exactly
            like the TUI's ``set_width``: the model's fixed grid is rebuilt
            from the new width, never realigned or inferred.
            """
            if self.model is None or width < 1 or width == self.model.width:
                return
            vw = self.view_widget
            v = vw.view
            keep = v.offset_at(v.top)
            self.model.width = width
            self._width = width  # future File > Open reloads keep this width
            v.invalidate()
            v.top = v.position_for_offset(keep)
            v.clamp_top(vw._page_rows())
            vw._sync_scrollbar()
            vw.viewport().update()
            self._update_status()

        def _open_settings_dialog(self) -> None:
            """Open the minimal GUI-native options pane (the 'o' key).

            Apply-immediately: the dialog's controls drive the existing menu
            actions, so changes show at once and the menu stays in sync. No
            persistence -- the GUI has no config file (unlike the TUI).
            """
            _SettingsDialog(self).exec()

        def _show_help_dialog(self):
            """Show the keyboard-shortcut help (generated from the registry)."""
            return self._show_report("multihex-gui - keys", gui_help_text())

        # -- layout overlay (load / change / clear / view) ------------------ #
        def _show_message(self, title: str, text: str, *, warn: bool = False):
            """Show a non-blocking message box (safe under headless tests).

            Static QMessageBox helpers spin a modal event loop, which would hang
            unattended tests; ``.show()`` returns immediately. A reference is kept
            so the dialog is not garbage-collected before it is displayed.
            """
            box = QMessageBox(self)
            box.setIcon(
                QMessageBox.Icon.Warning if warn else QMessageBox.Icon.Information
            )
            box.setWindowTitle(title)
            box.setText(text)
            box.setStandardButtons(QMessageBox.StandardButton.Ok)
            box.setModal(False)
            box.show()
            self._message_boxes.append(box)
            return box

        def _show_report(self, title: str, text: str) -> "_TextReportDialog":
            """Show a long monospace text report in a scrollable, non-modal
            dialog (help, overlay details/diagnostics). Short one-line notices
            keep using :meth:`_show_message`. A reference is kept so the dialog
            is not garbage-collected while shown.
            """
            dlg = _TextReportDialog(title, text, self)
            dlg.show()
            self._message_boxes.append(dlg)
            return dlg

        def load_overlay(self, path: str) -> "OverlayState":
            """Load + validate an overlay and apply it when loadable.

            Diagnostics are always surfaced (status bar summary plus a dialog with
            full detail when there are warnings or errors). An overlay with any
            error-severity diagnostic is reported but not applied. Returns the
            :class:`OverlayState` so callers/tests can inspect it.
            """
            overlay = OverlayState.load(path, self.files)
            self.overlay = overlay
            self.view_widget.set_overlay(overlay)
            if not overlay.applicable:
                self._show_report(
                    "Layout overlay",
                    overlay.summary() + "\n\n" + "\n".join(overlay.diagnostic_lines()),
                )
            elif overlay.warning_count():
                self._show_report("Layout overlay", overlay.details_text())
            # Transient summary toast; the persistent overlay status segment
            # keeps the state visible afterwards.
            self.statusBar().showMessage(overlay.summary(), 5000)
            self._update_overlay_status()
            return overlay

        def _overlay_load_dialog(self) -> None:
            if self.model is None:
                self._show_message(
                    "Layout overlay", "Open files first, then load an overlay."
                )
                return
            path, _ = QFileDialog.getOpenFileName(
                self, "Load layout overlay", "",
                "Overlay JSON (*.json);;All files (*)",
            )
            if path:
                self.load_overlay(path)

        def _overlay_clear(self) -> None:
            self.overlay = None
            self.view_widget.set_overlay(None)
            self.statusBar().showMessage("Cleared layout overlay", 3000)
            self._update_status()

        def _overlay_view(self) -> None:
            if self.overlay is None:
                self._show_message("Layout overlay", "No layout overlay loaded.")
                return
            cursor = None
            v = self.view_widget.view
            if v is not None and v.visible_count:
                cursor = self.model.row_offset(v.row_index_at(v.top))
            self._show_report(
                "Layout overlay", self.overlay.details_text(cursor)
            )

        # -- status bar ----------------------------------------------------- #
        def _build_status_bar(self) -> None:
            """Segmented status bar instead of one concatenated message string.

            The left (message) area holds the persistent search segment plus
            any transient one-shot notices (always shown with a timeout, so
            they never permanently cover the search segment). The permanent
            segments on the right are position, reference, display toggles,
            overlay state, and file sizes -- they survive transient messages.
            """
            bar = self.statusBar()
            self.status_search = QLabel(self)
            self.status_search.setVisible(False)
            bar.addWidget(self.status_search)
            self.status_pos = QLabel(self)
            self.status_ref = QLabel(self)
            self.status_toggles = QLabel(self)
            self.status_overlay = QLabel(self)
            self.status_overlay.setVisible(False)
            self.status_sizes = QLabel(self)
            for lbl in (
                self.status_pos, self.status_ref, self.status_toggles,
                self.status_overlay, self.status_sizes,
            ):
                lbl.setContentsMargins(6, 0, 6, 0)
                bar.addPermanentWidget(lbl)

        def _ref_label(self) -> str:
            if self.model is None or self.model.ref is None:
                return "all-agree"
            return self.model.files[self.model.ref].display_name(self.name_mode)

        def _sizes(self) -> List[Tuple[str, int]]:
            return [(f.display_name(self.name_mode), f.size) for f in self.files]

        def _update_title(self) -> None:
            if not self.files:
                self.setWindowTitle("multihex-gui")
                return
            names = [f.display_name("basename") for f in self.files]
            label = ", ".join(names[:4])
            if len(names) > 4:
                label += f" (+{len(names) - 4})"
            self.setWindowTitle(f"{label} - multihex-gui")

        def _update_status(self) -> None:
            if self.model is None or not self.files or self.view_widget.view is None:
                self.status_pos.setText("No files loaded — use File ▸ Open…")
                self.status_ref.setText("")
                self.status_toggles.setText("")
                self.status_sizes.setText("")
                self._update_overlay_status()
                return
            v = self.view_widget.view
            model = self.model
            count = v.visible_count
            if count == 0:
                start = end = 0
                row_pos = 0
            else:
                page = self.view_widget._page_rows()
                top = min(v.top, count - 1)
                bot = min(top + page - 1, count - 1)
                start = model.row_offset(v.row_index_at(top))
                end = model.row_offset(v.row_index_at(bot)) + model.width - 1
                row_pos = top + 1
            parts = format_status_parts(
                offset_start=start,
                offset_end=end,
                row_pos=row_pos,
                row_count=count,
                ref_label=self._ref_label(),
                ascii_on=self.view_widget.ascii_on,
                only_diff=v.only_diff,
                markers=self.view_widget.markers_mode,
                color_on=self.view_widget.color_on,
                byte_classes_on=self.view_widget.byte_classes_on,
                layout=self.view_widget.layout_mode,
                sizes=self._sizes(),
            )
            self.status_pos.setText(parts[0])
            self.status_ref.setText(parts[1])
            self.status_toggles.setText(parts[2])
            self.status_sizes.setText(parts[3])
            self._update_overlay_status()

        def _update_search_status(self) -> None:
            """Refresh the persistent search segment (hidden when no search)."""
            text = format_search_status(
                self.search_query, self.search_matches,
                self.search_index, self.search_error,
            )
            self.status_search.setText(text or "")
            self.status_search.setVisible(text is not None)

        def _update_overlay_status(self) -> None:
            """Refresh the persistent overlay segment (hidden when none loaded).

            Warning and not-applied states are tinted so a degraded overlay is
            visible at a glance, not only in the load-time dialog.
            """
            ov = self.overlay
            if ov is None:
                self.status_overlay.setText("")
                self.status_overlay.setStyleSheet("")
                self.status_overlay.setVisible(False)
                return
            self.status_overlay.setText(
                format_overlay_status(
                    name=ov.name,
                    applicable=ov.applicable,
                    range_count=ov.range_count,
                    warning_count=ov.warning_count(),
                    error_count=ov.error_count(),
                )
            )
            acc = self.view_widget._accents()
            if not ov.applicable:
                tint = acc.diff
            elif ov.warning_count():
                tint = acc.warn
            else:
                tint = None
            self.status_overlay.setStyleSheet(
                f"color: {tint.name()};" if tint is not None else ""
            )
            self.status_overlay.setVisible(True)

    class _TextSearchDialog(QDialog):
        """Modal text-search prompt with a case-insensitive (ASCII) checkbox.

        Being modal, it owns keyboard focus while open, so the viewer's single-key
        shortcuts never fire while typing. Dismisses with ``(text, ignore_case)``
        via :meth:`result_value`; mirrors the TUI ``TextSearchScreen``.
        """

        def __init__(self, ignore_case: bool, parent=None) -> None:
            super().__init__(parent)
            self.setWindowTitle("Find text")
            self.setModal(True)
            self.setMinimumWidth(420)
            layout = QVBoxLayout(self)
            layout.addWidget(QLabel("Search text (UTF-8):"))
            self._edit = QLineEdit(self)
            self._edit.setPlaceholderText("e.g. RIFF")
            layout.addWidget(self._edit)
            self._ci = QCheckBox("Case-insensitive (ASCII)", self)
            self._ci.setChecked(bool(ignore_case))
            layout.addWidget(self._ci)
            buttons = QDialogButtonBox(
                QDialogButtonBox.StandardButton.Ok
                | QDialogButtonBox.StandardButton.Cancel,
                parent=self,
            )
            buttons.accepted.connect(self.accept)
            buttons.rejected.connect(self.reject)
            layout.addWidget(buttons)
            self._edit.setFocus()

        def result_value(self) -> tuple:
            return self._edit.text(), self._ci.isChecked()

    class _HexSearchDialog(QDialog):
        """Modal hex-search prompt with live pattern validation.

        OK stays disabled (with an inline hint) until the pattern parses via
        ``core.parse_hex_pattern``, so invalid hex is rejected before the
        search runs rather than after the dialog closes. Hex search is always
        exact byte matching -- deliberately no case control, mirroring the
        TUI/CLI.
        """

        def __init__(self, parent=None) -> None:
            super().__init__(parent)
            self.setWindowTitle("Find hex bytes")
            self.setModal(True)
            self.setMinimumWidth(420)
            layout = QVBoxLayout(self)
            layout.addWidget(QLabel("Hex byte pattern:"))
            self._edit = QLineEdit(self)
            self._edit.setPlaceholderText("e.g. DE AD BE EF")
            layout.addWidget(self._edit)
            self._hint = QLabel("", self)
            self._hint.setStyleSheet("color: palette(mid);")
            layout.addWidget(self._hint)
            buttons = QDialogButtonBox(
                QDialogButtonBox.StandardButton.Ok
                | QDialogButtonBox.StandardButton.Cancel,
                parent=self,
            )
            self._ok = buttons.button(QDialogButtonBox.StandardButton.Ok)
            buttons.accepted.connect(self.accept)
            buttons.rejected.connect(self.reject)
            layout.addWidget(buttons)
            self._edit.textChanged.connect(self._validate)
            self._validate()
            self._edit.setFocus()

        def _validate(self, _text: str = "") -> None:
            text = self._edit.text().strip()
            ok = False
            hint = ""
            if text:
                try:
                    parse_hex_pattern(text)
                    ok = True
                except SearchError as exc:
                    hint = str(exc)
            self._ok.setEnabled(ok)
            self._hint.setText(hint)

        def result_value(self) -> str:
            return self._edit.text()

    class _TextReportDialog(QDialog):
        """Scrollable read-only text report (help, overlay details).

        The monospace font applies only to the text area; buttons and chrome
        stay in the proportional UI font. Non-modal so it never blocks the
        viewer (or hangs unattended tests); callers keep a reference alive.
        """

        def __init__(self, title: str, text: str, parent=None) -> None:
            super().__init__(parent)
            self.setWindowTitle(title)
            layout = QVBoxLayout(self)
            self._view = QPlainTextEdit(self)
            self._view.setReadOnly(True)
            self._view.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
            self._view.setFont(_fixed_font())
            self._view.setPlainText(text)
            layout.addWidget(self._view)
            buttons = QDialogButtonBox(
                QDialogButtonBox.StandardButton.Close, parent=self
            )
            buttons.rejected.connect(self.reject)
            layout.addWidget(buttons)
            self.resize(640, 480)

        def text(self) -> str:
            """The report body (mirrors QMessageBox.text() for callers/tests)."""
            return self._view.toPlainText()

    class _SettingsDialog(QDialog):
        """Minimal options pane: controls that drive the View-menu QActions.

        Apply-immediately with no persistence (the GUI has no config file). Each
        control flips the matching MainWindow action, which fires its slot and
        keeps the menu in sync, so the dialog and menus never disagree.
        """

        def __init__(self, window: "MainWindow") -> None:
            super().__init__(window)
            self.setWindowTitle("Options")
            self.setModal(True)
            self._window = window
            form = QFormLayout(self)
            self._checks = {}
            for label, action in (
                ("ASCII gutter", window.act_ascii),
                ("Only differing rows", window.act_diff),
                ("Side-by-side layout", window.act_layout),
                ("Color highlighting", window.act_color),
                ("Byte-class highlighting", window.act_byte_classes),
            ):
                box = QCheckBox(self)
                box.setChecked(action.isChecked())
                # Two-way: the checkbox drives the action (applies + fires its
                # slot); the action's state mirrors back so the box stays correct.
                box.toggled.connect(action.setChecked)
                action.toggled.connect(box.setChecked)
                form.addRow(label, box)
                self._checks[label] = box

            self._markers = QComboBox(self)
            for label, mode in (
                ("Single", "single"), ("Repeat", "repeat"), ("None", "none"),
            ):
                self._markers.addItem(label, mode)
            self._markers.setCurrentIndex(
                ["single", "repeat", "none"].index(window.view_widget.markers_mode)
            )
            self._markers.currentIndexChanged.connect(self._on_markers)
            form.addRow("Markers", self._markers)

            self._names = QComboBox(self)
            self._names.addItem("Basename", "basename")
            self._names.addItem("Full path", "path")
            self._names.setCurrentIndex(0 if window.name_mode == "basename" else 1)
            self._names.currentIndexChanged.connect(self._on_names)
            form.addRow("File names", self._names)

            self._width_spin = QSpinBox(self)
            self._width_spin.setRange(1, 256)
            self._width_spin.setValue(
                window.model.width if window.model is not None else window._width
            )
            self._width_spin.setEnabled(window.model is not None)
            self._width_spin.valueChanged.connect(window.set_row_width)
            form.addRow("Bytes per row", self._width_spin)

            buttons = QDialogButtonBox(
                QDialogButtonBox.StandardButton.Close, parent=self
            )
            buttons.rejected.connect(self.reject)
            form.addRow(buttons)

        def _on_names(self, index: int) -> None:
            mode = self._names.itemData(index)
            target = next(
                (a for a in self._window.names_group.actions() if a.data() == mode),
                None,
            )
            if target is not None:
                target.setChecked(True)
                self._window._on_names_changed(target)

        def _on_markers(self, index: int) -> None:
            mode = self._markers.itemData(index)
            target = next(
                (a for a in self._window.markers_group.actions() if a.data() == mode),
                None,
            )
            if target is not None and not target.isChecked():
                target.trigger()  # checks it and fires _on_markers_changed


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)  # before the guard, so --help works without PySide6

    if _PYSIDE6_IMPORT_ERROR is not None:
        sys.stderr.write(
            "multihex-gui requires PySide6.\n"
            "Install it with: pip install 'multihex[gui]'\n"
            f"(import error: {_PYSIDE6_IMPORT_ERROR})\n"
        )
        return 2

    if args.width < 1:
        sys.stderr.write("multihex-gui: --width must be >= 1\n")
        return 2
    if args.offset < 0:
        sys.stderr.write("multihex-gui: --offset must be >= 0\n")
        return 2

    missing_xcb = _missing_xcb_cursor_message()
    if missing_xcb is not None:
        sys.stderr.write(missing_xcb)
        return 2

    app = QApplication.instance() or QApplication(sys.argv[:1])
    window = MainWindow(
        offset=args.offset,
        width=args.width,
        ref=args.ref,
        name_mode=args.names,
        ascii_on=not args.no_ascii,
        only_diff=args.only_diff,
        markers=args.markers,
        layout=args.layout,
    )
    if args.files:
        window.load_paths(args.files)
        if args.overlay is not None:
            window.load_overlay(args.overlay)
    elif args.overlay is not None:
        sys.stderr.write(
            "multihex-gui: --overlay needs files; open files then load it from "
            "the Overlay menu.\n"
        )
    window.show()
    return app.exec()  # pragma: no cover - live Qt event loop, not the default lane


if __name__ == "__main__":
    raise SystemExit(main())
