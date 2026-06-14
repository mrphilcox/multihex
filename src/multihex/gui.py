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
    parse_int,
    prev_match_index,
    search_files,
)
from multihex.overlay import OverlayState
from multihex.shortcuts import gui_help_text, gui_key_names, gui_text_map

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


def format_status(
    *,
    offset_start: int,
    offset_end: int,
    row_pos: int,
    row_count: int,
    ref_label: str,
    ascii_on: bool,
    only_diff: bool,
    markers_on: bool,
    sizes: Sequence[Tuple[str, int]],
) -> str:
    """Build the status-bar string from primitives (pure; testable without Qt).

    Mirrors the TUI status line: visible offset range, row position/count,
    reference mode, the display toggles, and per-file sizes.
    """
    if row_count <= 0:
        where = "no rows"
    else:
        where = f"0x{offset_start:08x}-0x{offset_end:08x} | row {row_pos}/{row_count}"
    toggles = "ascii:%s diff:%s markers:%s" % (
        "on" if ascii_on else "off",
        "on" if only_diff else "off",
        "on" if markers_on else "off",
    )
    sizes_s = "  ".join(f"{name}={size}" for name, size in sizes)
    return f"{where} | ref={ref_label} | {toggles} | sizes: {sizes_s}"


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
    p.add_argument("--markers", choices=["single", "none"], default="single",
                   help="show the marker strip (default single) or hide it (none)")
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
        QVBoxLayout,
    )

    _PYSIDE6_IMPORT_ERROR: Optional[BaseException] = None
except ImportError as exc:  # pragma: no cover - depends on environment
    _PYSIDE6_IMPORT_ERROR = exc


if _PYSIDE6_IMPORT_ERROR is None:

    # Accent colours used only when colour is on. Base text/background come from
    # the widget palette so the view stays legible on light or dark themes.
    _COLOR_OFFSET = QColor(0x1F, 0x6F, 0xEB)   # offset address line
    _COLOR_DIFF = QColor(0xD7, 0x3A, 0x49)     # differing / DIFF marker
    _COLOR_SAME = QColor(0x2D, 0xA0, 0x44)     # SAME marker
    _COLOR_DIM = QColor(0x99, 0x99, 0x99)      # missing ("--") / MISSING marker
    _COLOR_REF = QColor(0x8A, 0x63, 0xD2)      # reference file's name
    _COLOR_OVERLAY = QColor(0x12, 0x8E, 0x9E)  # bytes inside a layout-overlay range
    # Search-match highlight: a filled background behind the matched cell (the
    # current match stronger than the others), with dark glyphs drawn on top.
    _COLOR_SEARCH_BG = QColor(0xF2, 0xCC, 0x3D)      # other matches
    _COLOR_SEARCH_CUR_BG = QColor(0xFF, 0xA5, 0x00)  # current match
    _COLOR_SEARCH_FG = QColor(0x10, 0x10, 0x10)      # glyphs on a match highlight
    # Byte-class foreground (the lowest-priority tier; display-only, needs colour
    # on). OTHER/MISSING get no byte-class colour, mirroring the core/TUI.
    _BYTE_CLASS_COLOR = {
        ByteClass.ZERO: QColor(0x99, 0x99, 0x99),
        ByteClass.WHITESPACE: QColor(0x12, 0x8E, 0x9E),
        ByteClass.PRINTABLE_ASCII: QColor(0x2D, 0xA0, 0x44),
    }

    class HexCompareView(QAbstractScrollArea):
        """Custom-painted, lazily-rendered comparison view.

        Renders only the visible blocks in :meth:`paintEvent` (never the whole
        range into one buffer). Block layout matches the shared text model:

            0x00000000
              fileA  00 01 02 ...  |....|
              fileB  00 ff 02 ...  |....|
                     == != == ...          (omitted when markers are hidden)

        Cell colouring is the GUI's own scheme, anchored on the core markers:
        a column whose marker is not SAME is reddened, missing bytes are dimmed,
        and the reference file's name is emphasised. Geometry mirrors
        ``core.render_row_text`` (same columns), so it is semantically identical
        to the CLI/TUI even though it is painted, not printed.
        """

        viewChanged = Signal()

        def __init__(self, parent=None) -> None:
            super().__init__(parent)
            self.view: Optional[ViewState] = None
            self.files: List = []
            self.name_mode = "basename"
            self.name_width = 0
            self.ascii_on = True
            self.markers_on = True
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
            # TODO(GUI usability): horizontal scrolling is not implemented, so a
            # wide --width (rows wider than the viewport) is silently clipped on
            # the right. Add a horizontal scrollbar / overflow handling later.
            self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
            self.viewport().setAutoFillBackground(True)
            self._init_font()

        def _init_font(self) -> None:
            font = QFont("monospace")
            font.setStyleHint(QFont.StyleHint.Monospace)
            font.setPointSize(11)
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
            self._sync_scrollbar()
            self.viewport().update()

        # -- geometry ------------------------------------------------------- #
        def _lines_per_block(self) -> int:
            # offset line + one line per file + optional marker line + blank gap
            nfiles = len(self.files) if self.files else 1
            return 1 + nfiles + (1 if self.markers_on else 0) + 1

        def _block_px(self) -> int:
            return self._lines_per_block() * self._line_h

        def _page_rows(self) -> int:
            block = self._block_px()
            height = self.viewport().height()
            return max(1, height // block) if block else 1

        # -- scrollbar wiring ----------------------------------------------- #
        def _sync_scrollbar(self) -> None:
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

        def scrollContentsBy(self, dx: int, dy: int) -> None:
            # Custom paint: never bit-blt; just track the new top and repaint.
            if self.view is not None:
                self.view.top = self.verticalScrollBar().value()
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

        def set_markers_on(self, on: bool) -> None:
            self.markers_on = on
            self._sync_scrollbar()  # block height changed -> page size changed
            self.viewport().update()

        def set_name_mode(self, mode: str) -> None:
            self.name_mode = mode
            self.name_width = name_column_width(self.files, mode) if self.files else 0
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
            # visible. The match *background* is painted separately (_cell_search_bg).
            if not self.color_on:
                return self._text_color()
            if value is None:
                return _COLOR_DIM
            if fi is not None and offset is not None and self._is_match(fi, offset):
                return _COLOR_SEARCH_FG
            if marker is not Marker.SAME:
                return _COLOR_DIFF
            if offset is not None and self.overlay is not None and self.overlay.covers(offset):
                return _COLOR_OVERLAY
            if self.byte_classes_on:
                bc = _BYTE_CLASS_COLOR.get(classify_byte(value))
                if bc is not None:
                    return bc
            return self._text_color()

        def _is_match(self, fi: int, offset: int) -> bool:
            return (fi, offset) in self._search_covered

        def _cell_search_bg(self, fi: int, offset: int) -> Optional["QColor"]:
            """Background fill for a matched cell (current match stronger), or None."""
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
            return None

        def _marker_color(self, marker: Marker) -> "QColor":
            if not self.color_on:
                return self._text_color()
            if marker is Marker.MISSING:
                return _COLOR_DIM
            if marker is Marker.DIFF:
                return _COLOR_DIFF
            return _COLOR_SAME

        def paintEvent(self, event) -> None:
            painter = QPainter(self.viewport())
            painter.setFont(self.font())
            pal = self.palette()
            painter.fillRect(self.viewport().rect(), pal.color(QPalette.ColorRole.Base))

            if self.view is None or not self.files:
                painter.setPen(_COLOR_DIM)
                painter.drawText(
                    self.viewport().rect(),
                    Qt.AlignmentFlag.AlignCenter,
                    "No files loaded — use File ▸ Open…",
                )
                painter.end()
                return

            view = self.view
            model = view.model
            count = view.visible_count
            block_px = self._block_px()
            hex_start = marker_prefix_width(self.name_width)
            # One extra block so a partially-visible bottom block still draws.
            nblocks = self._page_rows() + 1
            for b in range(nblocks):
                pos = view.top + b
                if pos >= count:
                    break
                row = model.build_row(view.row_index_at(pos))
                self._paint_block(painter, row, model, b * block_px, hex_start)
            painter.end()

        def _paint_block(self, painter, row, model, top: int, hex_start: int) -> None:
            cw = self._char_w
            line_h = self._line_h
            ascent = self._ascent
            width = model.width
            text_color = self._text_color()

            def draw(col: int, line: int, s: str, color) -> None:
                painter.setPen(color)
                painter.drawText(int(col * cw), int(top + line * line_h + ascent), s)

            def fill(col: int, line: int, ncols: int, color) -> None:
                painter.fillRect(
                    int(col * cw), int(top + line * line_h),
                    int(ncols * cw), int(line_h), color,
                )

            # offset address line
            draw(0, 0, f"0x{row.offset:08x}",
                 _COLOR_OFFSET if self.color_on else text_color)

            # one line per file
            for fi, (f, row_bytes) in enumerate(zip(model.files, row.cells)):
                line = 1 + fi
                name = f.display_name(self.name_mode).ljust(self.name_width)
                name_color = _COLOR_REF if (self.color_on and model.ref == fi) else text_color
                draw(2, line, name, name_color)
                for c in range(width):
                    marker = row.markers[c]
                    off = row.offset + c
                    bg = self._cell_search_bg(fi, off)
                    if bg is not None:
                        fill(hex_start + c * 3, line, 2, bg)
                    draw(hex_start + c * 3, line, format_byte(row_bytes[c]),
                         self._cell_color(row_bytes[c], marker, off, fi))
                if self.ascii_on:
                    acol = hex_start + width * 3 + 1  # past hex + "  |"
                    draw(acol, line, "|", text_color)
                    for c in range(width):
                        marker = row.markers[c]
                        off = row.offset + c
                        bg = self._cell_search_bg(fi, off)
                        if bg is not None:
                            fill(acol + 1 + c, line, 1, bg)
                        draw(acol + 1 + c, line, format_ascii_char(row_bytes[c]),
                             self._cell_color(row_bytes[c], marker, off, fi))
                    draw(acol + 1 + width, line, "|", text_color)

            # marker strip
            if self.markers_on:
                line = 1 + len(model.files)
                for c in range(width):
                    marker = row.markers[c]
                    draw(hex_start + c * 3, line, format_marker(marker),
                         self._marker_color(marker))

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
            markers_on: bool = True,
        ) -> None:
            super().__init__()
            self.setWindowTitle("multihex-gui")
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
            self.view_widget.markers_on = markers_on
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
            self.statusBar()
            self.resize(960, 640)
            self._update_status()

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
                "cycle_markers": self._cycle_markers,
                "load_overlay": self._overlay_load_dialog,
                "view_overlay": self._overlay_view,
                "open_settings": self._open_settings_dialog,
                "search_text": self._search_text_dialog,
                "search_hex": self._search_hex_dialog,
                "next_match": self.search_next,
                "prev_match": self.search_prev,
                "help": self._show_help_dialog,
            }
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
            self.act_ascii = QAction("&ASCII gutter", self)
            self.act_ascii.setCheckable(True)
            self.act_ascii.setChecked(self.view_widget.ascii_on)
            self.act_ascii.toggled.connect(self._on_toggle_ascii)
            viewm.addAction(self.act_ascii)
            self.act_diff = QAction("Only &differing rows", self)
            self.act_diff.setCheckable(True)
            self.act_diff.setChecked(self._start_only_diff)
            self.act_diff.toggled.connect(self._on_toggle_diff)
            viewm.addAction(self.act_diff)
            self.act_markers = QAction("Show &markers", self)
            self.act_markers.setCheckable(True)
            self.act_markers.setChecked(self.view_widget.markers_on)
            self.act_markers.toggled.connect(self._on_toggle_markers)
            viewm.addAction(self.act_markers)
            self.act_color = QAction("&Color highlighting", self)
            self.act_color.setCheckable(True)
            self.act_color.setChecked(self.view_widget.color_on)
            self.act_color.toggled.connect(self._on_toggle_color)
            viewm.addAction(self.act_color)
            self.act_byte_classes = QAction("&Byte-class highlighting", self)
            self.act_byte_classes.setCheckable(True)
            self.act_byte_classes.setChecked(self.view_widget.byte_classes_on)
            self.act_byte_classes.toggled.connect(self._on_toggle_byte_classes)
            viewm.addAction(self.act_byte_classes)
            viewm.addSeparator()
            act_options = QAction("&Options…", self)
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

            self.comparem = mb.addMenu("&Compare")
            self.ref_group = QActionGroup(self)
            self.ref_group.setExclusive(True)
            self.ref_group.triggered.connect(self._on_ref_changed)
            self._rebuild_ref_menu()

            overlaym = mb.addMenu("&Overlay")
            act_ov_load = QAction("&Load/change layout overlay…", self)
            act_ov_load.triggered.connect(self._overlay_load_dialog)
            overlaym.addAction(act_ov_load)
            self.act_overlay_clear = QAction("&Clear overlay", self)
            self.act_overlay_clear.triggered.connect(self._overlay_clear)
            overlaym.addAction(self.act_overlay_clear)
            overlaym.addSeparator()
            act_ov_view = QAction("&View current overlay…", self)
            act_ov_view.triggered.connect(self._overlay_view)
            overlaym.addAction(act_ov_view)

            searchm = mb.addMenu("&Search")
            act_find = QAction("Find &text…", self)
            act_find.setShortcut("Ctrl+F")
            act_find.triggered.connect(self._search_text_dialog)
            searchm.addAction(act_find)
            act_find_hex = QAction("Find &hex…", self)
            act_find_hex.triggered.connect(self._search_hex_dialog)
            searchm.addAction(act_find_hex)
            searchm.addSeparator()
            act_next = QAction("&Next match", self)
            act_next.triggered.connect(self.search_next)
            searchm.addAction(act_next)
            act_prev = QAction("&Previous match", self)
            act_prev.triggered.connect(self.search_prev)
            searchm.addAction(act_prev)

            helpm = mb.addMenu("&Help")
            act_keys = QAction("&Keyboard shortcuts…", self)
            act_keys.triggered.connect(self._show_help_dialog)
            helpm.addAction(act_keys)

        def _rebuild_ref_menu(self) -> None:
            """(Re)populate the Compare menu with the reference radio choices."""
            for a in list(self.ref_group.actions()):
                self.ref_group.removeAction(a)
            self.comparem.clear()
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

        def _on_toggle_markers(self, checked: bool) -> None:
            self.view_widget.set_markers_on(checked)
            self._update_status()

        def _on_toggle_color(self, checked: bool) -> None:
            self.view_widget.set_color_on(checked)
            self._update_status()

        def _on_toggle_byte_classes(self, checked: bool) -> None:
            self.view_widget.set_byte_classes(checked)
            self._update_status()

        def _cycle_markers(self) -> None:
            # The GUI has no side-by-side layout, so there is no "repeat" mode;
            # the marker cycle is a strip on/off toggle (reuses the menu action).
            self.act_markers.toggle()

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
            text, ok = QInputDialog.getText(
                self, "Jump to offset", "Offset (e.g. 0x400, 1024):"
            )
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
            text, ok = QInputDialog.getText(
                self, "Hex search", "Search hex (e.g. DE AD BE EF):"
            )
            if ok and text.strip():
                self.run_search("hex", text)

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
                self.statusBar().showMessage(f"Search error: {exc}")
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
            else:
                self.statusBar().showMessage(f'No matches for {mode} "{text}"')

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

        def _jump_to_current_match(self) -> None:
            if self.search_index is None:
                return
            match = self.search_matches[self.search_index]
            self.view_widget.jump_to_offset(match.offset)
            self.statusBar().showMessage(
                f"Match {self.search_index + 1}/{len(self.search_matches)} "
                f"| file {match.file_index} | offset 0x{match.offset:08x}"
            )

        # -- options / help ------------------------------------------------- #
        def _open_settings_dialog(self) -> None:
            """Open the minimal GUI-native options pane (the 'o' key).

            Apply-immediately: the dialog's controls drive the existing menu
            actions, so changes show at once and the menu stays in sync. No
            persistence -- the GUI has no config file (unlike the TUI).
            """
            _SettingsDialog(self).exec()

        def _show_help_dialog(self):
            """Show the keyboard-shortcut help (generated from the registry)."""
            box = QMessageBox(self)
            box.setIcon(QMessageBox.Icon.Information)
            box.setWindowTitle("multihex-gui - keys")
            font = QFont("monospace")
            font.setStyleHint(QFont.StyleHint.Monospace)
            box.setFont(font)
            box.setText(gui_help_text())
            box.setStandardButtons(QMessageBox.StandardButton.Ok)
            box.setModal(False)
            box.show()
            self._message_boxes.append(box)
            return box

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
                self._show_message(
                    "Layout overlay",
                    overlay.summary() + "\n\n" + "\n".join(overlay.diagnostic_lines()),
                    warn=True,
                )
            elif overlay.warning_count():
                self._show_message("Layout overlay", overlay.details_text())
            # Leave the overlay summary on the status bar; it persists until the
            # next navigation refreshes the standard status line.
            self.statusBar().showMessage(overlay.summary())
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
            self.statusBar().showMessage("Cleared layout overlay")
            self._update_status()

        def _overlay_view(self) -> None:
            if self.overlay is None:
                self._show_message("Layout overlay", "No layout overlay loaded.")
                return
            cursor = None
            v = self.view_widget.view
            if v is not None and v.visible_count:
                cursor = self.model.row_offset(v.row_index_at(v.top))
            self._show_message(
                "Layout overlay", self.overlay.details_text(cursor)
            )

        # -- status bar ----------------------------------------------------- #
        def _ref_label(self) -> str:
            if self.model is None or self.model.ref is None:
                return "all-agree"
            return self.model.files[self.model.ref].display_name(self.name_mode)

        def _sizes(self) -> List[Tuple[str, int]]:
            return [(f.display_name(self.name_mode), f.size) for f in self.files]

        def _update_status(self) -> None:
            if self.model is None or not self.files or self.view_widget.view is None:
                self.statusBar().showMessage("No files loaded — use File ▸ Open…")
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
            self.statusBar().showMessage(
                format_status(
                    offset_start=start,
                    offset_end=end,
                    row_pos=row_pos,
                    row_count=count,
                    ref_label=self._ref_label(),
                    ascii_on=self.view_widget.ascii_on,
                    only_diff=v.only_diff,
                    markers_on=self.view_widget.markers_on,
                    sizes=self._sizes(),
                )
            )

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
            layout = QVBoxLayout(self)
            layout.addWidget(QLabel("Search text (UTF-8):"))
            self._edit = QLineEdit(self)
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
                ("Marker strip", window.act_markers),
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

            self._names = QComboBox(self)
            self._names.addItem("Basename", "basename")
            self._names.addItem("Full path", "path")
            self._names.setCurrentIndex(0 if window.name_mode == "basename" else 1)
            self._names.currentIndexChanged.connect(self._on_names)
            form.addRow("File names", self._names)

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
        markers_on=(args.markers != "none"),
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
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
