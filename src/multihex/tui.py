"""multihex.tui - interactive TUI for fixed-offset multi-file hex compare.

A viewer only: no editing, no inference, no resynchronization, no offset-
changing byte filtering. All comparison meaning lives in multihex.core so
this frontend and the batch multihex.cli stay in lockstep.

Usage:
    multihex-tui file1.bin file2.bin file3.bin
    multihex-tui --offset 0x400 --width 16 *.bin
    multihex-tui --ref 0 file*.bin

Keys:
    q             quit
    j / down      next row
    k / up        previous row
    PageDown      next page
    PageUp        previous page
    Home          jump to start of range
    End           jump to end (last page)
    g             jump to offset
    r             choose reference file
    a             toggle ASCII gutter
    d             toggle only-diff rows
    c             toggle color/highlighting
    t             toggle byte-class highlighting
    v             cycle layout (stacked / side-by-side)
    m             cycle markers (single / repeat / none)
    l             load/change layout overlay (blank path clears)
    L             view current layout overlay
    left / right  scroll horizontally (side-by-side)
    o             open settings / options pane
    /             text search (panel has an ASCII case-insensitive toggle)
    x             hex search (matches byte values, not ASCII text)
    n             next match
    N / p         previous match
    h / ?         help
"""

from __future__ import annotations

import argparse
import bisect
import os
import sys
from pathlib import Path
from typing import List, Optional, Sequence, Union

from multihex.core import (
    ByteClass,
    HexModel,
    Marker,
    Row,
    SearchError,
    SearchMatch,
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
from multihex.shortcuts import tui_help_text
from multihex.tui_config import (
    TuiSettings,
    default_config_path,
    load_settings,
    save_settings,
)

# Textual is only required to *run* the TUI. Import lazily-ish so that
# argument parsing / --help still work (and give a clean message) when the
# package is not installed.
try:
    from rich.text import Text
    from textual.app import App, ComposeResult
    from textual.binding import Binding
    from textual.containers import Vertical
    from textual.screen import ModalScreen
    from textual.widget import Widget
    from textual.widgets import Checkbox, Footer, Header, Input, Label, Static

    _TEXTUAL_IMPORT_ERROR: Optional[BaseException] = None
except ImportError as exc:  # pragma: no cover - depends on environment
    _TEXTUAL_IMPORT_ERROR = exc


# Styles used only when color is enabled.
_DIFF_STYLE = "bold red"
_OFFSET_STYLE = "bold cyan"
_REF_STYLE = "bold yellow"
# Search highlight: the current match stands out more strongly than the others.
_SEARCH_STYLE = "black on yellow"
_SEARCH_CUR_STYLE = "bold black on bright_yellow"
# Byte-class foreground for --byte-classes / the 't' toggle (display-only, the
# lowest-priority tier). OTHER/MISSING get no byte-class color.
_BYTE_CLASS_STYLE = {
    ByteClass.ZERO: "grey50",
    ByteClass.WHITESPACE: "cyan",
    ByteClass.PRINTABLE_ASCII: "green",
}
# Layout-overlay highlight: a neutral background so an annotated byte is
# distinguishable, sitting just above byte class and below diff/search.
_OVERLAY_STYLE = "on blue"


if _TEXTUAL_IMPORT_ERROR is None:

    class HexView(Widget):
        """Scrollable, paginated view over a HexModel.

        Owns the navigation/filter state (top row, only-diff set, toggles).
        Renders exactly as many blocks as fit the current height.
        """

        DEFAULT_CSS = """
        HexView { height: 1fr; overflow: hidden; }
        """

        def __init__(
            self,
            model: HexModel,
            *,
            ascii_on: bool,
            only_diff: bool,
            color_on: bool,
            name_mode: str,
            byte_classes_on: bool = False,
            layout: str = "stacked",
            markers: str = "single",
            overlay: Optional[OverlayState] = None,
        ) -> None:
            super().__init__()
            self.model = model
            self.ascii_on = ascii_on
            self.only_diff = only_diff
            self.color_on = color_on
            self.byte_classes_on = byte_classes_on
            # Loaded layout overlay (None = none). Highlighting is gated on the
            # overlay being applicable, so a loaded-but-erroring overlay can be
            # kept for "view current overlay" without ever highlighting.
            self.overlay = overlay
            self.name_mode = name_mode
            self.name_width = name_column_width(model.files, name_mode)
            # Stored as ``layout_mode`` (not ``layout``) to avoid clashing with
            # Textual's Widget.layout property.
            self.layout_mode = layout
            # Marker-text display mode: "single" / "repeat" / "none". Display-only
            # (see _render_block); never affects markers, only-diff, or search.
            self.markers_mode = markers
            # Horizontal scroll offset (characters) for side-by-side rows that
            # exceed the viewport width. Always 0 in stacked mode.
            self.h_scroll = 0
            self._content_width = 0  # widest rendered line on the last page
            self.top = 0  # position into visible_indices()
            self._visible: Optional[Union[range, List[int]]] = None
            self._page_rows = 1
            # Search highlight state (driven by the app). ``search_current`` is
            # the strongly-highlighted match; ``_search_covered`` is the set of
            # every matched (file_index, absolute_offset) for the milder
            # "other matches" highlight. Empty when no search is active.
            self.search_matches: List[SearchMatch] = []
            self.search_current: Optional[SearchMatch] = None
            self._search_covered: set = set()

        # -- visible-index (only-diff) management --------------------------- #
        def visible_indices(self) -> Union[range, List[int]]:
            if self._visible is None:
                if self.only_diff:
                    self._visible = [
                        i
                        for i in range(self.model.row_count)
                        if self.model.build_row(i).has_diff
                    ]
                else:
                    self._visible = range(self.model.row_count)
            return self._visible

        def invalidate(self) -> None:
            """Drop the cached visible set (after ref/only-diff changes)."""
            self._visible = None

        @property
        def visible_count(self) -> int:
            return len(self.visible_indices())

        def _lines_per_block(self) -> int:
            # offset line + content lines + optional marker line + blank separator
            if self.layout_mode == "side-by-side":
                content = 1
                marker = 1 if self.markers_mode == "repeat" else 0
            else:
                content = len(self.model.files)
                marker = 0 if self.markers_mode == "none" else 1
            return 1 + content + marker + 1

        def _max_top(self) -> int:
            return max(0, self.visible_count - self._page_rows)

        def _clamp_top(self) -> None:
            self.top = max(0, min(self.top, self._max_top()))

        def _position_for_row(self, row_index: int) -> int:
            """Map a global row index to a position in the visible set.

            In only-diff mode, snap forward to the next visible (diff) row.
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

        def current_top_row(self) -> int:
            vis = self.visible_indices()
            if not vis:
                return self.model.start_offset
            return vis[min(self.top, len(vis) - 1)]

        # -- navigation ----------------------------------------------------- #
        def scroll_rows(self, delta: int) -> None:
            self.top = max(0, min(self.top + delta, self._max_top()))
            self.refresh()

        def page(self, direction: int) -> None:
            self.scroll_rows(direction * max(1, self._page_rows))

        def jump_to_offset(self, offset: int) -> None:
            target = self.model.index_for_offset(offset)
            self.top = self._position_for_row(target)
            self._clamp_top()
            self.refresh()

        def set_ref(self, ref: Optional[int]) -> None:
            self.model.ref = ref
            # Marker set changed -> the only-diff filter must be rebuilt.
            keep = self.current_top_row()
            self.invalidate()
            self.top = self._position_for_row(keep)
            self._clamp_top()
            self.refresh()

        def toggle_ascii(self) -> None:
            self.ascii_on = not self.ascii_on
            self.refresh()

        def toggle_color(self) -> None:
            self.color_on = not self.color_on
            self.refresh()

        def toggle_byte_classes(self) -> None:
            self.byte_classes_on = not self.byte_classes_on
            self.refresh()

        def cycle_layout(self) -> None:
            self.layout_mode = (
                "side-by-side" if self.layout_mode == "stacked" else "stacked"
            )
            # Horizontal scroll only applies to side-by-side; reset on switch.
            self.h_scroll = 0
            self.refresh()

        def cycle_markers(self) -> None:
            order = ("single", "repeat", "none")
            self.markers_mode = order[(order.index(self.markers_mode) + 1) % len(order)]
            self.refresh()

        def scroll_h(self, delta: int) -> None:
            """Scroll the side-by-side view horizontally by ``delta`` chars.

            A no-op in stacked mode, where rows are not meant to exceed the
            viewport and the existing (clip-only) behavior is preserved.
            """
            if self.layout_mode != "side-by-side":
                return
            viewport = self.size.width or 0
            max_scroll = max(0, self._content_width - viewport)
            self.h_scroll = max(0, min(self.h_scroll + delta, max_scroll))
            self.refresh()

        def toggle_only_diff(self) -> None:
            self.set_only_diff(not self.only_diff)

        # -- explicit setters (used by the settings pane; apply immediately) - #
        def set_ascii(self, value: bool) -> None:
            self.ascii_on = value
            self.refresh()

        def set_color_on(self, value: bool) -> None:
            self.color_on = value
            self.refresh()

        def set_byte_classes(self, value: bool) -> None:
            self.byte_classes_on = value
            self.refresh()

        def set_layout(self, value: str) -> None:
            self.layout_mode = value
            self.h_scroll = 0
            self.refresh()

        def set_markers(self, value: str) -> None:
            self.markers_mode = value
            self.refresh()

        def set_names(self, mode: str) -> None:
            self.name_mode = mode
            self.name_width = name_column_width(self.model.files, mode)
            self.refresh()

        def set_width(self, width: int) -> None:
            """Change bytes-per-row, keeping the top row roughly in place."""
            if width < 1:
                return
            keep = self.current_top_row()
            self.model.width = width
            self.invalidate()
            self.top = self._position_for_row(keep)
            self._clamp_top()
            self.refresh()

        def set_only_diff(self, value: bool) -> None:
            keep = self.current_top_row()
            self.only_diff = value
            self.invalidate()
            self.top = self._position_for_row(keep)
            self._clamp_top()
            self.refresh()

        # -- search highlight ----------------------------------------------- #
        def set_search(
            self,
            matches: List[SearchMatch],
            current_index: Optional[int],
        ) -> None:
            """Install a new result set and recompute the highlight coverage."""
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
            self.refresh()

        def _cell_style(
            self, fi: int, abs_off: int, marker: Marker, value: Optional[int] = None
        ) -> str:
            """Style for one file's byte cell.

            Display priority (only matters when colour is on): a missing byte is
            never part of a match, so it never reaches a search branch; among
            present bytes the order is current search match > other search match
            > diff/stability marker > layout overlay > byte class. Overlay and
            byte-class color are the lowest tiers: they apply only to present,
            non-diff cells, so search and diff highlighting stay the most visible.
            """
            if self.color_on:
                cur = self.search_current
                if (
                    cur is not None
                    and fi == cur.file_index
                    and cur.offset <= abs_off < cur.offset + cur.length
                ):
                    return _SEARCH_CUR_STYLE
                if (fi, abs_off) in self._search_covered:
                    return _SEARCH_STYLE
            if marker is not Marker.SAME:
                return self._style(_DIFF_STYLE)
            if self.color_on and self.overlay is not None and self.overlay.covers(abs_off):
                return _OVERLAY_STYLE
            if self.color_on and self.byte_classes_on and value is not None:
                return _BYTE_CLASS_STYLE.get(classify_byte(value), "")
            return ""

        # -- rendering ------------------------------------------------------ #
        def render(self) -> "Text":
            height = self.size.height or 24
            self._page_rows = max(1, height // self._lines_per_block())
            self._clamp_top()

            if self.visible_count == 0:
                if self.model.row_count == 0:
                    return Text("(no data at offset 0x%x)" % self.model.start_offset)
                return Text("(no differing rows - press 'd' to show all)")

            vis = self.visible_indices()
            end = min(self.top + self._page_rows, self.visible_count)
            text = Text()
            for pos in range(self.top, end):
                self._render_block(text, self.model.build_row(vis[pos]))

            # Track the widest line so scroll_h() can clamp. Only apply the
            # horizontal crop when actually scrolled, so stacked (and unscrolled
            # side-by-side) rendering stays byte-for-byte as before.
            lines = text.split("\n")
            self._content_width = max((len(ln.plain) for ln in lines), default=0)
            if self.h_scroll:
                viewport = self.size.width or 0
                self.h_scroll = min(self.h_scroll, max(0, self._content_width - viewport))
                if self.h_scroll:
                    return Text("\n").join(ln[self.h_scroll:] for ln in lines)
            return text

        def _style(self, style: str) -> str:
            return style if self.color_on else ""

        def _append_file_segment(
            self, text: "Text", row: Row, fi: int, f, row_bytes
        ) -> None:
            """Append one file's segment (name + hex + optional ASCII gutter).

            No leading indent and no trailing newline: the caller positions the
            segment (stacked = one per line, side-by-side = joined horizontally).
            All cell styling flows through ``_cell_style`` so diff/search/missing/
            byte-class highlighting is identical in both layouts.
            """
            model = self.model
            name = f.display_name(self.name_mode).ljust(self.name_width)
            name_style = self._style(_REF_STYLE) if model.ref == fi else ""
            text.append(name, style=name_style)
            text.append("  ")
            for ci in range(model.width):
                cell_style = self._cell_style(
                    fi, row.offset + ci, row.markers[ci], row_bytes[ci]
                )
                text.append(format_byte(row_bytes[ci]), style=cell_style)
                if ci != model.width - 1:
                    text.append(" ")
            if self.ascii_on:
                text.append("  |")
                for ci in range(model.width):
                    cell_style = self._cell_style(
                        fi, row.offset + ci, row.markers[ci], row_bytes[ci]
                    )
                    text.append(format_ascii_char(row_bytes[ci]), style=cell_style)
                text.append("|")

        def _append_marker_strip(self, text: "Text", row: Row, diff: str) -> None:
            """Append the colored marker tokens (no leading prefix/newline)."""
            model = self.model
            for ci in range(model.width):
                marker = row.markers[ci]
                cell_style = diff if marker is not Marker.SAME else ""
                text.append(format_marker(marker), style=cell_style)
                if ci != model.width - 1:
                    text.append(" ")

        def _render_block(self, text: "Text", row: Row) -> None:
            model = self.model
            diff = self._style(_DIFF_STYLE)
            mode = self.markers_mode

            text.append(f"0x{row.offset:08x}\n", style=self._style(_OFFSET_STYLE))

            if self.layout_mode == "side-by-side":
                if mode == "single":
                    # The marker strip is its own left prefix column, not
                    # attached to the first file segment.
                    text.append("  ")
                    self._append_marker_strip(text, row, diff)
                    text.append("  ")
                    for fi, (f, row_bytes) in enumerate(zip(model.files, row.cells)):
                        if fi:
                            text.append("   ")
                        self._append_file_segment(text, row, fi, f, row_bytes)
                    text.append("\n")
                else:
                    for fi, (f, row_bytes) in enumerate(zip(model.files, row.cells)):
                        text.append("   " if fi else "  ")
                        self._append_file_segment(text, row, fi, f, row_bytes)
                    text.append("\n")
                    if mode == "repeat":
                        gap = " " * (self.name_width + 2)
                        # Pad each strip to the segment width so the repeated
                        # strips line up under each segment's hex columns.
                        tail = " " * (model.width + 4 if self.ascii_on else 0)
                        nfiles = len(model.files)
                        for fi in range(nfiles):
                            text.append("   " if fi else "  ")
                            text.append(gap)
                            self._append_marker_strip(text, row, diff)
                            if fi != nfiles - 1:
                                text.append(tail)
                        text.append("\n")
            else:
                for fi, (f, row_bytes) in enumerate(zip(model.files, row.cells)):
                    text.append("  ")
                    self._append_file_segment(text, row, fi, f, row_bytes)
                    text.append("\n")
                if mode != "none":
                    text.append(" " * marker_prefix_width(self.name_width))
                    self._append_marker_strip(text, row, diff)
                    text.append("\n")
            text.append("\n")

    class _PromptScreen(ModalScreen[Optional[str]]):
        """A small modal asking for one line of input."""

        DEFAULT_CSS = """
        _PromptScreen { align: center middle; }
        _PromptScreen > Vertical {
            width: 70; height: auto; padding: 1 2;
            border: round $accent; background: $panel;
        }
        _PromptScreen Label { margin-bottom: 1; }
        """

        def __init__(self, prompt: str, body: str = "") -> None:
            super().__init__()
            self._prompt = prompt
            self._body = body

        def compose(self) -> "ComposeResult":
            with Vertical():
                if self._body:
                    yield Label(self._body)
                yield Label(self._prompt)
                yield Input(id="prompt_input")

        def on_mount(self) -> None:
            self.query_one(Input).focus()

        def on_input_submitted(self, event: "Input.Submitted") -> None:
            self.dismiss(event.value)

        def on_key(self, event) -> None:
            if event.key == "escape":
                self.dismiss(None)

    class TextSearchScreen(ModalScreen[Optional[tuple]]):
        """Text-search prompt with a case-insensitive toggle.

        Dismisses with ``(text, ignore_case)`` on submit, or ``None`` when
        cancelled. The checkbox is seeded from the app's remembered (session-only)
        preference so the last choice sticks for the session. This is the *text*
        panel only -- the hex panel deliberately has no case control (hex search
        is always exact byte matching).
        """

        DEFAULT_CSS = """
        TextSearchScreen { align: center middle; }
        TextSearchScreen > Vertical {
            width: 70; height: auto; padding: 1 2;
            border: round $accent; background: $panel;
        }
        TextSearchScreen Label { margin-bottom: 1; }
        """

        def __init__(self, ignore_case: bool = False) -> None:
            super().__init__()
            self._ignore_case = ignore_case

        def compose(self) -> "ComposeResult":
            with Vertical():
                yield Label("Search text (UTF-8):")
                yield Input(id="search_input")
                yield Checkbox(
                    "Case-insensitive (ASCII)",
                    value=self._ignore_case,
                    id="ci",
                )

        def on_mount(self) -> None:
            self.query_one(Input).focus()

        def on_input_submitted(self, event: "Input.Submitted") -> None:
            self.dismiss((event.value, self.query_one(Checkbox).value))

        def on_key(self, event) -> None:
            if event.key == "escape":
                self.dismiss(None)

    class HelpScreen(ModalScreen[None]):
        DEFAULT_CSS = """
        HelpScreen { align: center middle; }
        HelpScreen > Vertical {
            width: 60; height: auto; padding: 1 2;
            border: round $accent; background: $panel;
        }
        """

        # Generated from the shared shortcut registry (the single source of truth
        # for both frontends' help). Never hand-edit -- change multihex.shortcuts.
        _HELP = tui_help_text()

        def compose(self) -> "ComposeResult":
            with Vertical():
                yield Static(self._HELP)

        def on_key(self, event) -> None:
            self.dismiss(None)

    class OverlayScreen(ModalScreen[Optional[str]]):
        """Read-only "view current overlay" panel.

        Shows the overlay's path, schema, name, source_* fields, range count,
        applied/not-applied status, diagnostics, range list, and the ranges under
        the cursor (the top visible offset). Press ``c`` to clear the overlay,
        any other key to close. Editing is out of scope.
        """

        DEFAULT_CSS = """
        OverlayScreen { align: center middle; }
        OverlayScreen > Vertical {
            width: 84; height: auto; max-height: 90%; padding: 1 2;
            border: round $accent; background: $panel;
        }
        """

        def __init__(self, text: str) -> None:
            super().__init__()
            self._text = text

        def compose(self) -> "ComposeResult":
            with Vertical():
                yield Static(self._text)
                yield Static("(c clear overlay - any other key closes)")

        def on_key(self, event) -> None:
            if event.key == "c":
                self.dismiss("clear")
            else:
                self.dismiss(None)

    class SettingsScreen(ModalScreen[None]):
        """Interactive settings/options pane (the 'o' key).

        Shows the current effective TUI preferences and the active config path.
        Changes apply to the running view *immediately* (matching the rest of the
        TUI's toggles); ``s`` saves to the active path, ``S`` saves to a prompted
        path, ``esc`` closes. Persisting is explicit -- closing alone never writes.
        """

        DEFAULT_CSS = """
        SettingsScreen { align: center middle; }
        SettingsScreen > Vertical {
            width: 64; height: auto; padding: 1 2;
            border: round $accent; background: $panel;
        }
        """

        # Editable rows, in display order: (attribute-key, label).
        _FIELDS = [
            ("layout", "layout"),
            ("ascii", "ascii gutter"),
            ("byte_classes", "byte classes"),
            ("color", "color"),
            ("names", "names"),
            ("markers", "markers"),
            ("width", "width"),
            ("only_diff", "only-diff"),
        ]
        _LABEL_W = 14

        def __init__(self) -> None:
            super().__init__()
            self._sel = 0

        def compose(self) -> "ComposeResult":
            with Vertical():
                yield Static(id="settings_body")

        def on_mount(self) -> None:
            self._redraw()

        def _values(self) -> dict:
            app = self.app
            v = app.view
            return {
                "layout": v.layout_mode,
                "ascii": "on" if v.ascii_on else "off",
                "byte_classes": "on" if v.byte_classes_on else "off",
                "color": app.color_mode,
                "names": v.name_mode,
                "markers": v.markers_mode,
                "width": str(app.model.width),
                "only_diff": "on" if v.only_diff else "off",
            }

        def _redraw(self) -> None:
            values = self._values()
            lines = [
                "multihex-tui settings",
                "",
                f"config: {self.app.config_path}",
                "",
            ]
            for i, (key, label) in enumerate(self._FIELDS):
                cursor = ">" if i == self._sel else " "
                lines.append(
                    f"  {cursor} {label.ljust(self._LABEL_W)} {values[key]}"
                )
            lines += [
                "",
                "  up/down select   left/right change",
                "  s save   S save-as   esc close",
            ]
            self.query_one("#settings_body", Static).update("\n".join(lines))

        def _change(self, direction: int) -> None:
            key, _ = self._FIELDS[self._sel]
            app = self.app
            v = app.view
            if key == "layout":
                v.set_layout(
                    "side-by-side" if v.layout_mode == "stacked" else "stacked"
                )
            elif key == "ascii":
                v.set_ascii(not v.ascii_on)
            elif key == "byte_classes":
                v.set_byte_classes(not v.byte_classes_on)
            elif key == "color":
                modes = ["auto", "always", "never"]
                idx = (modes.index(app.color_mode) + direction) % len(modes)
                app.set_color_mode(modes[idx])
            elif key == "names":
                v.set_names("path" if v.name_mode == "basename" else "basename")
            elif key == "markers":
                modes = ["single", "repeat", "none"]
                idx = (modes.index(v.markers_mode) + direction) % len(modes)
                v.set_markers(modes[idx])
            elif key == "width":
                v.set_width(max(1, app.model.width + direction))
            elif key == "only_diff":
                v.set_only_diff(not v.only_diff)
            app.update_status()
            self._redraw()

        def _save_as(self) -> None:
            def handle(value: Optional[str]) -> None:
                if value is None or not value.strip():
                    return
                self.app.save_config(Path(value.strip()))
                self._redraw()

            self.app.push_screen(
                _PromptScreen("Save settings to path:", str(self.app.config_path)),
                handle,
            )

        def on_key(self, event) -> None:
            key = event.key
            if key in ("up", "k"):
                self._sel = (self._sel - 1) % len(self._FIELDS)
                self._redraw()
            elif key in ("down", "j"):
                self._sel = (self._sel + 1) % len(self._FIELDS)
                self._redraw()
            elif key == "left":
                self._change(-1)
            elif key == "right":
                self._change(+1)
            elif key == "s":
                self.app.save_config()
                self._redraw()
            elif key == "S":
                self._save_as()
            elif key == "escape":
                self.dismiss(None)

    class MultiHexApp(App):
        TITLE = "multihex-tui"

        CSS = """
        #status {
            height: 1; dock: bottom;
            color: $text-muted; background: $panel;
            padding: 0 1;
        }
        #search_status {
            height: 1; dock: bottom;
            color: $text; background: $panel;
            padding: 0 1;
            display: none;
        }
        """

        BINDINGS = [
            Binding("q", "quit", "Quit"),
            Binding("j", "next_row", "Down", show=False),
            Binding("down", "next_row", "Down"),
            Binding("k", "prev_row", "Up", show=False),
            Binding("up", "prev_row", "Up"),
            Binding("pagedown", "next_page", "PgDn"),
            Binding("pageup", "prev_page", "PgUp"),
            Binding("home", "home", "Home", show=False),
            Binding("end", "end", "End", show=False),
            Binding("g", "jump", "Goto"),
            Binding("r", "choose_ref", "Ref"),
            Binding("a", "toggle_ascii", "ASCII"),
            Binding("d", "toggle_diff", "Only-diff"),
            Binding("c", "toggle_color", "Color"),
            Binding("t", "toggle_byte_classes", "Classes"),
            Binding("v", "cycle_layout", "Layout"),
            Binding("m", "cycle_markers", "Markers"),
            Binding("l", "load_overlay", "Overlay"),
            Binding("L", "view_overlay", "View overlay", show=False),
            Binding("left", "scroll_left", "Scroll left", show=False),
            Binding("right", "scroll_right", "Scroll right", show=False),
            Binding("o", "open_settings", "Options"),
            Binding("slash", "search_text", "Search"),
            Binding("x", "search_hex", "Hex search"),
            Binding("n", "next_match", "Next", show=False),
            Binding("N", "prev_match", "Prev", show=False),
            Binding("p", "prev_match", "Prev", show=False),
            Binding("h", "help", "Help", show=False),
            Binding("question_mark", "help", "Help"),
        ]

        def __init__(
            self,
            model: HexModel,
            *,
            ascii_on: bool,
            only_diff: bool,
            color_on: bool,
            name_mode: str,
            byte_classes_on: bool = False,
            layout: str = "stacked",
            markers: str = "single",
            color_mode: str = "auto",
            overlay: Optional[OverlayState] = None,
            config_path: Optional[Path] = None,
            config_warnings: Optional[List[str]] = None,
        ) -> None:
            super().__init__()
            self.model = model
            self.view = HexView(
                model,
                ascii_on=ascii_on,
                only_diff=only_diff,
                color_on=color_on,
                name_mode=name_mode,
                byte_classes_on=byte_classes_on,
                layout=layout,
                markers=markers,
                overlay=overlay,
            )
            # Loaded layout overlay (None = none). Kept on the app so the load/
            # clear/view actions and the status line can reach it; the view holds
            # the same reference for highlighting.
            self.overlay = overlay
            # Search state lives on the app; the view only renders highlights.
            self.search_query = None
            self.search_matches: List[SearchMatch] = []
            self.search_index: Optional[int] = None
            self.search_error: Optional[str] = None
            # Session-only text-search preference (seeds the panel checkbox; not
            # persisted to config and never a startup flag).
            self.text_search_ignore_case = False
            # Persisted-settings state (TUI-only). ``color_mode`` is the ternary
            # auto/always/never preference saved to config; the runtime ``c``
            # toggle flips the render bool (view.color_on) independently.
            self.color_mode = color_mode
            self.config_path = Path(config_path) if config_path else default_config_path()
            self.config_warnings = list(config_warnings or [])

        def compose(self) -> "ComposeResult":
            yield Header()
            yield self.view
            yield Static(id="search_status")
            yield Static(id="status")
            yield Footer()

        def on_mount(self) -> None:
            self.update_status()
            self.update_search_status()
            # Surface any config-load warnings as toasts (also printed to stderr
            # before launch). A missing config file is normal and warns nothing.
            for warning in self.config_warnings:
                try:
                    self.notify(warning, title="config", severity="warning")
                except Exception:
                    pass

        def current_settings(self) -> TuiSettings:
            """Snapshot the live display state as persistable settings."""
            v = self.view
            return TuiSettings(
                layout=v.layout_mode,
                ascii=v.ascii_on,
                byte_classes=v.byte_classes_on,
                color=self.color_mode,
                names=v.name_mode,
                markers=v.markers_mode,
                width=self.model.width,
                only_diff=v.only_diff,
            )

        def on_resize(self, event) -> None:
            self.update_status()

        # -- status line ---------------------------------------------------- #
        def _page_rows_estimate(self) -> int:
            height = getattr(self.view.size, "height", 0) or 0
            if height:
                return max(1, height // self.view._lines_per_block())
            return self.view._page_rows

        def update_status(self) -> None:
            v = self.view
            m = self.model
            try:
                status = self.query_one("#status", Static)
            except Exception:
                return

            ref_label = "all-agree" if m.ref is None else (
                m.files[m.ref].display_name(v.name_mode)
            )
            toggles = "ascii:%s diff:%s color:%s classes:%s layout:%s markers:%s" % (
                "on" if v.ascii_on else "off",
                "on" if v.only_diff else "off",
                "on" if v.color_on else "off",
                "on" if v.byte_classes_on else "off",
                v.layout_mode,
                v.markers_mode,
            )
            if self.overlay is not None:
                toggles += " overlay:%s" % (
                    "on" if self.overlay.applicable else "err"
                )
            sizes = "  ".join(
                f"{f.display_name(v.name_mode)}={f.size}" for f in m.files
            )

            count = v.visible_count
            if count == 0:
                where = "no rows"
            else:
                page = self._page_rows_estimate()
                vis = v.visible_indices()
                top_pos = min(v.top, count - 1)
                bot_pos = min(top_pos + page - 1, count - 1)
                start = m.row_offset(vis[top_pos])
                end = m.row_offset(vis[bot_pos]) + m.width - 1
                where = (
                    f"0x{start:08x}-0x{end:08x}  "
                    f"row {top_pos + 1}/{count}"
                )

            status.update(
                f"{where} | ref={ref_label} | {toggles} | sizes: {sizes}"
            )

        def update_search_status(self) -> None:
            """Refresh the dedicated search line (hidden when no search runs)."""
            try:
                widget = self.query_one("#search_status", Static)
            except Exception:
                return

            if self.search_error is not None:
                widget.update(f"Search error: {self.search_error}")
                widget.display = True
                return

            q = self.search_query
            if q is None:
                widget.update("")
                widget.display = False
                return

            label = f'{q.mode} "{q.pattern}"'
            if q.mode == "text" and not q.case_sensitive:
                label += " (ci)"
            if not self.search_matches:
                widget.update(f"Search: {label} | no matches")
            else:
                cur = self.search_index or 0
                m = self.search_matches[cur]
                widget.update(
                    f"Search: {label} | match {cur + 1}/{len(self.search_matches)} "
                    f"| file {m.file_index} | offset 0x{m.offset:08x}"
                )
            widget.display = True

        # -- actions -------------------------------------------------------- #
        def action_next_row(self) -> None:
            self.view.scroll_rows(1)
            self.update_status()

        def action_prev_row(self) -> None:
            self.view.scroll_rows(-1)
            self.update_status()

        def action_next_page(self) -> None:
            self.view.page(1)
            self.update_status()

        def action_prev_page(self) -> None:
            self.view.page(-1)
            self.update_status()

        def action_home(self) -> None:
            # Navigation only: jump to the first displayable row (the start of the
            # compared range, honouring --offset). Touches no comparison/search
            # state; render()'s _clamp_top keeps an out-of-range top safe.
            self.view.top = 0
            self.view.refresh()
            self.update_status()

        def action_end(self) -> None:
            # Navigation only: bottom-anchored final page (the last displayable row
            # is the last fully visible row). With no rows / zero diff rows in
            # only-diff mode, _max_top() is 0, so this is a stable no-op.
            self.view.top = self.view._max_top()
            self.view.refresh()
            self.update_status()

        def action_toggle_ascii(self) -> None:
            self.view.toggle_ascii()
            self.update_status()

        def action_toggle_color(self) -> None:
            self.view.toggle_color()
            self.update_status()

        def action_toggle_byte_classes(self) -> None:
            self.view.toggle_byte_classes()
            self.update_status()

        def action_cycle_layout(self) -> None:
            self.view.cycle_layout()
            self.update_status()

        def action_cycle_markers(self) -> None:
            self.view.cycle_markers()
            self.update_status()

        def action_scroll_left(self) -> None:
            self.view.scroll_h(-8)

        def action_scroll_right(self) -> None:
            self.view.scroll_h(8)

        def action_toggle_diff(self) -> None:
            self.view.toggle_only_diff()
            self.update_status()

        def action_help(self) -> None:
            self.push_screen(HelpScreen())

        def action_open_settings(self) -> None:
            self.push_screen(SettingsScreen())

        # -- layout overlay (load / change / clear / view) ------------------ #
        def _apply_overlay(self, value: Optional[str]) -> None:
            """Handle the load-overlay prompt result.

            ``None`` (escape) leaves the current overlay untouched; an empty/blank
            path clears it; otherwise the overlay is loaded, validated, and kept
            for viewing. It only highlights when applicable (no error-severity
            diagnostic), so an erroring overlay is reported but not applied.
            """
            if value is None:
                return
            text = value.strip()
            if not text:
                self.overlay = None
                self.view.overlay = None
                self.view.refresh()
                self.update_status()
                self.notify("Cleared layout overlay", title="overlay")
                return
            overlay = OverlayState.load(text, self.model.files)
            self.overlay = overlay
            self.view.overlay = overlay
            self.view.refresh()
            self.update_status()
            self.notify(
                overlay.summary(),
                title="overlay",
                severity="information" if overlay.applicable else "error",
            )

        def action_load_overlay(self) -> None:
            body = (
                f"current: {self.overlay.path}"
                if self.overlay is not None
                else "none loaded"
            )
            self.push_screen(
                _PromptScreen("Layout overlay path (blank to clear):", body),
                self._apply_overlay,
            )

        def action_view_overlay(self) -> None:
            if self.overlay is None:
                self.notify("No layout overlay loaded (press 'l').", title="overlay")
                return
            cursor = self.model.start_offset
            if self.view.visible_count:
                cursor = self.model.row_offset(self.view.current_top_row())

            def handle(result: Optional[str]) -> None:
                if result == "clear":
                    self._apply_overlay("")

            self.push_screen(
                OverlayScreen(self.overlay.details_text(cursor)), handle
            )

        # -- settings (apply immediately + save) ---------------------------- #
        def set_color_mode(self, mode: str) -> None:
            """Set the persisted color mode and re-derive the render bool."""
            self.color_mode = mode
            self.view.set_color_on(_resolve_color(mode))
            self.update_status()

        def save_config(self, path: Optional[Path] = None) -> None:
            """Write the current settings to ``path`` (or the active path).

            Surfaces success/failure as a toast and never raises out of the UI.
            """
            target = Path(path) if path else self.config_path
            try:
                save_settings(self.current_settings(), target)
            except OSError as exc:
                self.notify(f"Save failed: {exc}", title="config", severity="error")
                return
            self.config_path = target
            self.notify(f"Saved {target}", title="config")

        def action_jump(self) -> None:
            def handle(value: Optional[str]) -> None:
                if value is None or not value.strip():
                    return
                try:
                    offset = parse_int(value.strip())
                except ValueError:
                    self.bell()
                    return
                self.view.jump_to_offset(offset)
                self.update_status()

            self.push_screen(
                _PromptScreen("Jump to offset (e.g. 0x400, 1024):"), handle
            )

        def action_choose_ref(self) -> None:
            listing = "\n".join(
                f"  [{i}] {f.display_name(self.view.name_mode)}"
                for i, f in enumerate(self.model.files)
            )
            body = (
                "Reference file. Enter an index, or 'a' for all-agree.\n"
                + listing
            )

            def handle(value: Optional[str]) -> None:
                if value is None:
                    return
                choice = value.strip().lower()
                if choice in ("", "a", "all"):
                    self.view.set_ref(None)
                    self.update_status()
                    return
                try:
                    idx = parse_int(choice)
                except ValueError:
                    self.bell()
                    return
                if not (0 <= idx < len(self.model.files)):
                    self.bell()
                    return
                self.view.set_ref(idx)
                self.update_status()

            self.push_screen(_PromptScreen("Index or 'a':", body), handle)

        # -- search --------------------------------------------------------- #
        def action_search_text(self) -> None:
            self.push_screen(
                TextSearchScreen(self.text_search_ignore_case),
                self._run_text_search,
            )

        def action_search_hex(self) -> None:
            self.push_screen(
                _PromptScreen("Search hex (e.g. DE AD BE EF):"),
                lambda v: self._run_search("hex", v),
            )

        def _run_text_search(self, result: Optional[tuple]) -> None:
            """Handle the text-search panel result: ``(text, ignore_case)``.

            ``None`` (cancelled prompt) leaves the previous search untouched. The
            chosen case mode is remembered for the session and re-seeds the panel.
            """
            if result is None:
                return
            value, ignore_case = result
            self.text_search_ignore_case = bool(ignore_case)
            self._run_search("text", value, ignore_case=self.text_search_ignore_case)

        def _run_search(
            self, mode: str, value: Optional[str], *, ignore_case: bool = False
        ) -> None:
            """Build a query, replace search state, and jump to the first match.

            Invalid input sets an error status and never crashes; an empty/
            cancelled prompt leaves the previous search untouched.
            """
            if value is None or not value.strip():
                return
            text = value.strip()
            try:
                if mode == "text":
                    query = make_text_query(
                        text, case_sensitive=not ignore_case
                    )
                else:
                    query = make_hex_query(text)
            except SearchError as exc:
                self.search_error = str(exc)
                self.search_query = None
                self.search_matches = []
                self.search_index = None
                self.view.set_search([], None)
                self.update_search_status()
                return

            self.search_error = None
            self.search_query = query
            self.search_matches = search_files(
                self.model.files, query, model=self.model
            )
            self.search_index = first_match_index(self.search_matches)
            self.view.set_search(self.search_matches, self.search_index)
            if self.search_index is not None:
                self._jump_to_current_match()
            self.update_status()
            self.update_search_status()

        def action_next_match(self) -> None:
            self._step_match(next_match_index)

        def action_prev_match(self) -> None:
            self._step_match(prev_match_index)

        def _step_match(self, picker) -> None:
            if not self.search_matches:
                self.bell()
                return
            self.search_index = picker(self.search_matches, self.search_index or 0)
            self.view.set_current_match(self.search_index)
            self._jump_to_current_match()
            self.update_search_status()

        def _jump_to_current_match(self) -> None:
            if self.search_index is None:
                return
            match = self.search_matches[self.search_index]
            # Navigate the view to the match's offset. If only-diff is on and the
            # match's row isn't a diff row, jump_to_offset snaps to the nearest
            # visible row (the offset is still shown in the search status line).
            self.view.jump_to_offset(match.offset)
            self.update_status()


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="multihex-tui",
        description="Interactive fixed-offset comparison of multiple binary "
        "files (viewer only).",
    )
    p.add_argument("files", nargs="+", help="binary files to compare")
    p.add_argument("--offset", type=parse_int, default=0, metavar="N",
                   help="start offset (int, 0x.. ok)")
    # The display preferences below default to None so an explicitly-passed flag
    # can be told apart from "not given"; the effective default comes from the
    # config file or the built-in TuiSettings (see build_startup_settings).
    p.add_argument("--width", type=parse_int, default=None, metavar="N",
                   help="bytes per row (default 16)")
    p.add_argument("--ref", type=parse_int, default=None, metavar="INDEX",
                   help="compare every file against this 0-based index")
    p.add_argument("--names", choices=["basename", "path"], default=None,
                   help="how to label files (default basename)")
    p.add_argument("--only-diff", action="store_true", dest="only_diff",
                   help="start with only differing rows shown")
    p.add_argument("--no-ascii", action="store_true", dest="no_ascii",
                   help="start with the ASCII gutter hidden")
    p.add_argument("--color", choices=["auto", "always", "never"],
                   default=None, help="highlighting (default auto)")
    p.add_argument("--byte-classes", dest="byte_classes", action="store_true",
                   help="start with byte-class highlighting on (toggle with 't'). "
                        "Visual-only; needs color on. Default off.")
    p.add_argument("--layout", choices=["stacked", "side-by-side"], default=None,
                   help="initial layout: stacked (default) or side-by-side "
                        "(cycle with 'v'; scroll horizontally with left/right).")
    p.add_argument("--markers", choices=["single", "repeat", "none"], default=None,
                   help="initial marker text display: single (default), repeat "
                        "(repeat the strip under each segment in side-by-side; "
                        "same as single when stacked), or none (hidden). Cycle "
                        "with 'm'. Display-only.")
    p.add_argument("--overlay", metavar="PATH", default=None,
                   help="load a bintools.layout-overlay v1 JSON file (a read-only "
                        "annotation layer) and highlight its byte ranges. Change "
                        "with 'l', view with 'L'. Not saved in config.")

    # -- TUI-only persistent config (the batch CLI never reads any config) ---- #
    cfg = p.add_mutually_exclusive_group()
    cfg.add_argument("--config", metavar="PATH", default=None,
                     help="load TUI settings from PATH and make it the save "
                          "target (default: $XDG_CONFIG_HOME/multihex/tui.toml "
                          "or ~/.config/multihex/tui.toml)")
    cfg.add_argument("--no-config", action="store_true", dest="no_config",
                     help="ignore any config file; start from built-in defaults "
                          "plus CLI args (saving still uses the default path)")
    return p.parse_args(argv)


def build_startup_settings(
    args: argparse.Namespace,
) -> "tuple[TuiSettings, Path, List[str]]":
    """Resolve effective TUI settings and the active save path.

    Applies the precedence chain *built-in defaults -> config file -> CLI args*
    (interactive changes come later, in the running app). ``--no-config`` skips
    the file but still honors CLI args; the save target is the ``--config`` path
    when given, else the default path. Returns ``(settings, active_path,
    warnings)``; warnings are non-fatal config-load notes for the caller to show.
    """
    settings = TuiSettings()
    warnings: List[str] = []
    active_path = Path(args.config) if args.config else default_config_path()

    if not args.no_config:
        settings, warnings = load_settings(active_path, settings)

    # CLI args override the config (and defaults). Value flags use None to mean
    # "not given"; the one-way bool flags only ever *force* their value on.
    if args.layout is not None:
        settings.layout = args.layout
    if args.markers is not None:
        settings.markers = args.markers
    if args.width is not None:
        settings.width = args.width
    if args.names is not None:
        settings.names = args.names
    if args.color is not None:
        settings.color = args.color
    if args.no_ascii:
        settings.ascii = False
    if args.only_diff:
        settings.only_diff = True
    if args.byte_classes:
        settings.byte_classes = True

    return settings, active_path, warnings


def _resolve_color(mode: str) -> bool:
    if mode == "never":
        return False
    if mode == "always":
        return True
    return not os.environ.get("NO_COLOR")  # auto


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)

    if _TEXTUAL_IMPORT_ERROR is not None:
        sys.stderr.write(
            "multihex-tui requires the 'textual' package to run.\n"
            "Install it with:  pip install 'multihex[tui]'\n"
            f"(import error: {_TEXTUAL_IMPORT_ERROR})\n"
        )
        return 2

    settings, config_path, config_warnings = build_startup_settings(args)

    # Surface config-load problems before launching (also shown in-app as toasts).
    for warning in config_warnings:
        sys.stderr.write(f"multihex-tui: {warning}\n")

    try:
        files = load_files(args.files)
    except OSError as exc:
        sys.stderr.write(f"multihex-tui: {exc}\n")
        return 2

    try:
        model = HexModel(
            files,
            start_offset=args.offset,
            width=settings.width,
            ref=args.ref,
        )
    except ValueError as exc:
        sys.stderr.write(f"multihex-tui: {exc}\n")
        return 2

    # A startup overlay is loaded and reported up front; like the runtime 'l'
    # action it is kept even when not applicable (so 'L' can show why), and only
    # highlights when applicable. Overlay paths are never persisted to config.
    overlay = None
    if args.overlay is not None:
        overlay = OverlayState.load(args.overlay, files)
        sys.stderr.write(f"multihex-tui: {overlay.summary()}\n")
        for line in overlay.diagnostic_lines():
            sys.stderr.write(f"multihex-tui:   {line}\n")

    app = MultiHexApp(
        model,
        ascii_on=settings.ascii,
        only_diff=settings.only_diff,
        color_on=_resolve_color(settings.color),
        name_mode=settings.names,
        byte_classes_on=settings.byte_classes,
        layout=settings.layout,
        markers=settings.markers,
        color_mode=settings.color,
        overlay=overlay,
        config_path=config_path,
        config_warnings=config_warnings,
    )
    app.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
