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
    g             jump to offset
    r             choose reference file
    a             toggle ASCII gutter
    d             toggle only-diff rows
    c             toggle color/highlighting
    t             toggle byte-class highlighting
    v             cycle layout (stacked / side-by-side)
    left / right  scroll horizontally (side-by-side)
    /             text search
    x             hex search
    n             next match
    N / p         previous match
    h / ?         help
"""

from __future__ import annotations

import argparse
import bisect
import os
import sys
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
    from textual.widgets import Footer, Header, Input, Label, Static

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
        ) -> None:
            super().__init__()
            self.model = model
            self.ascii_on = ascii_on
            self.only_diff = only_diff
            self.color_on = color_on
            self.byte_classes_on = byte_classes_on
            self.name_mode = name_mode
            self.name_width = name_column_width(model.files, name_mode)
            # Stored as ``layout_mode`` (not ``layout``) to avoid clashing with
            # Textual's Widget.layout property.
            self.layout_mode = layout
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
            # offset line + one line per file + marker line + blank separator
            return 1 + len(self.model.files) + 1 + 1

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
            keep = self.current_top_row()
            self.only_diff = not self.only_diff
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
            > diff/stability marker > byte class. Byte-class color is the lowest
            tier: it applies only to present, non-diff cells, so search and diff
            highlighting stay the most visible.
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

        def _render_block(self, text: "Text", row: Row) -> None:
            model = self.model
            diff = self._style(_DIFF_STYLE)

            text.append(f"0x{row.offset:08x}\n", style=self._style(_OFFSET_STYLE))

            if self.layout_mode == "side-by-side":
                for fi, (f, row_bytes) in enumerate(zip(model.files, row.cells)):
                    text.append("   " if fi else "  ")
                    self._append_file_segment(text, row, fi, f, row_bytes)
                text.append("\n")
            else:
                for fi, (f, row_bytes) in enumerate(zip(model.files, row.cells)):
                    text.append("  ")
                    self._append_file_segment(text, row, fi, f, row_bytes)
                    text.append("\n")

            text.append(" " * marker_prefix_width(self.name_width))
            for ci in range(model.width):
                marker = row.markers[ci]
                cell_style = diff if marker is not Marker.SAME else ""
                text.append(format_marker(marker), style=cell_style)
                if ci != model.width - 1:
                    text.append(" ")
            text.append("\n\n")

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

    class HelpScreen(ModalScreen[None]):
        DEFAULT_CSS = """
        HelpScreen { align: center middle; }
        HelpScreen > Vertical {
            width: 60; height: auto; padding: 1 2;
            border: round $accent; background: $panel;
        }
        """

        _HELP = (
            "multihex-tui - keys\n\n"
            "  q             quit\n"
            "  j / down      next row\n"
            "  k / up        previous row\n"
            "  PageDown      next page\n"
            "  PageUp        previous page\n"
            "  g             jump to offset\n"
            "  r             choose reference file\n"
            "  a             toggle ASCII gutter\n"
            "  d             toggle only-diff rows\n"
            "  c             toggle color\n"
            "  t             toggle byte-class highlighting\n"
            "  v             cycle layout (stacked / side-by-side)\n"
            "  left / right  scroll horizontally (side-by-side)\n"
            "  /             text search\n"
            "  x             hex search\n"
            "  n             next match\n"
            "  N / p         previous match\n"
            "  h / ?         this help\n\n"
            "  (any key to close)"
        )

        def compose(self) -> "ComposeResult":
            with Vertical():
                yield Static(self._HELP)

        def on_key(self, event) -> None:
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
            Binding("g", "jump", "Goto"),
            Binding("r", "choose_ref", "Ref"),
            Binding("a", "toggle_ascii", "ASCII"),
            Binding("d", "toggle_diff", "Only-diff"),
            Binding("c", "toggle_color", "Color"),
            Binding("t", "toggle_byte_classes", "Classes"),
            Binding("v", "cycle_layout", "Layout"),
            Binding("left", "scroll_left", "Scroll left", show=False),
            Binding("right", "scroll_right", "Scroll right", show=False),
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
            )
            # Search state lives on the app; the view only renders highlights.
            self.search_query = None
            self.search_matches: List[SearchMatch] = []
            self.search_index: Optional[int] = None
            self.search_error: Optional[str] = None

        def compose(self) -> "ComposeResult":
            yield Header()
            yield self.view
            yield Static(id="search_status")
            yield Static(id="status")
            yield Footer()

        def on_mount(self) -> None:
            self.update_status()
            self.update_search_status()

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
            toggles = "ascii:%s diff:%s color:%s classes:%s layout:%s" % (
                "on" if v.ascii_on else "off",
                "on" if v.only_diff else "off",
                "on" if v.color_on else "off",
                "on" if v.byte_classes_on else "off",
                v.layout_mode,
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

        def action_scroll_left(self) -> None:
            self.view.scroll_h(-8)

        def action_scroll_right(self) -> None:
            self.view.scroll_h(8)

        def action_toggle_diff(self) -> None:
            self.view.toggle_only_diff()
            self.update_status()

        def action_help(self) -> None:
            self.push_screen(HelpScreen())

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
                _PromptScreen("Search text (UTF-8):"),
                lambda v: self._run_search("text", v),
            )

        def action_search_hex(self) -> None:
            self.push_screen(
                _PromptScreen("Search hex (e.g. DE AD BE EF):"),
                lambda v: self._run_search("hex", v),
            )

        def _run_search(self, mode: str, value: Optional[str]) -> None:
            """Build a query, replace search state, and jump to the first match.

            Invalid input sets an error status and never crashes; an empty/
            cancelled prompt leaves the previous search untouched.
            """
            if value is None or not value.strip():
                return
            text = value.strip()
            try:
                if mode == "text":
                    query = make_text_query(text)
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
    p.add_argument("--color", choices=["auto", "always", "never"],
                   default="auto", help="highlighting (default auto)")
    p.add_argument("--byte-classes", dest="byte_classes", action="store_true",
                   help="start with byte-class highlighting on (toggle with 't'). "
                        "Visual-only; needs color on. Default off.")
    p.add_argument("--layout", choices=["stacked", "side-by-side"], default="stacked",
                   help="initial layout: stacked (default) or side-by-side "
                        "(cycle with 'v'; scroll horizontally with left/right).")
    return p.parse_args(argv)


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

    try:
        files = load_files(args.files)
    except OSError as exc:
        sys.stderr.write(f"multihex-tui: {exc}\n")
        return 2

    try:
        model = HexModel(
            files,
            start_offset=args.offset,
            width=args.width,
            ref=args.ref,
        )
    except ValueError as exc:
        sys.stderr.write(f"multihex-tui: {exc}\n")
        return 2

    app = MultiHexApp(
        model,
        ascii_on=not args.no_ascii,
        only_diff=args.only_diff,
        color_on=_resolve_color(args.color),
        name_mode=args.names,
        byte_classes_on=args.byte_classes,
        layout=args.layout,
    )
    app.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
