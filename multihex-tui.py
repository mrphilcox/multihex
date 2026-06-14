#!/usr/bin/env python3
"""multihex-tui.py - interactive TUI for fixed-offset multi-file hex compare.

A viewer only: no editing, no inference, no resynchronization, no offset-
changing byte filtering. All comparison meaning lives in multihex_core so
this frontend and the batch multihex.py stay in lockstep.

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
    h / ?         help
"""

from __future__ import annotations

import argparse
import bisect
import os
import sys
from typing import List, Optional, Sequence, Union

from multihex_core import (
    HexModel,
    Marker,
    Row,
    format_ascii_char,
    format_byte,
    format_marker,
    load_files,
    marker_prefix_width,
    name_column_width,
    parse_int,
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
        ) -> None:
            super().__init__()
            self.model = model
            self.ascii_on = ascii_on
            self.only_diff = only_diff
            self.color_on = color_on
            self.name_mode = name_mode
            self.name_width = name_column_width(model.files, name_mode)
            self.top = 0  # position into visible_indices()
            self._visible: Optional[Union[range, List[int]]] = None
            self._page_rows = 1

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

        def toggle_only_diff(self) -> None:
            keep = self.current_top_row()
            self.only_diff = not self.only_diff
            self.invalidate()
            self.top = self._position_for_row(keep)
            self._clamp_top()
            self.refresh()

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
            return text

        def _style(self, style: str) -> str:
            return style if self.color_on else ""

        def _render_block(self, text: "Text", row: Row) -> None:
            model = self.model
            diff = self._style(_DIFF_STYLE)

            text.append(f"0x{row.offset:08x}\n", style=self._style(_OFFSET_STYLE))

            for fi, (f, row_bytes) in enumerate(zip(model.files, row.cells)):
                name = f.display_name(self.name_mode).ljust(self.name_width)
                name_style = self._style(_REF_STYLE) if model.ref == fi else ""
                text.append("  ")
                text.append(name, style=name_style)
                text.append("  ")
                for ci in range(model.width):
                    cell_style = diff if row.markers[ci] is not Marker.SAME else ""
                    text.append(format_byte(row_bytes[ci]), style=cell_style)
                    if ci != model.width - 1:
                        text.append(" ")
                if self.ascii_on:
                    text.append("  |")
                    for ci in range(model.width):
                        cell_style = diff if row.markers[ci] is not Marker.SAME else ""
                        text.append(format_ascii_char(row_bytes[ci]), style=cell_style)
                    text.append("|")
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
        ) -> None:
            super().__init__()
            self.model = model
            self.view = HexView(
                model,
                ascii_on=ascii_on,
                only_diff=only_diff,
                color_on=color_on,
                name_mode=name_mode,
            )

        def compose(self) -> "ComposeResult":
            yield Header()
            yield self.view
            yield Static(id="status")
            yield Footer()

        def on_mount(self) -> None:
            self.update_status()

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
            toggles = "ascii:%s diff:%s color:%s" % (
                "on" if v.ascii_on else "off",
                "on" if v.only_diff else "off",
                "on" if v.color_on else "off",
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
            "Install it with:  pip install textual\n"
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
    )
    app.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
