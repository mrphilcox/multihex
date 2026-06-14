# Copyright (c) 2026 Philip Cox
# SPDX-License-Identifier: Apache-2.0

"""TUI layout: default/start state, the 'v' cycle key, status/help, search
preservation, and horizontal scrolling (any row wider than the viewport).

Driven headless through Textual's test harness, mirroring test_tui_search.
"""

import asyncio
import os
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import multihex.tui as tui  # noqa: E402
from multihex.core import HexFile, HexModel  # noqa: E402

pytestmark = pytest.mark.skipif(
    tui._TEXTUAL_IMPORT_ERROR is not None, reason="textual not installed"
)


def _make_app(layout="stacked", files=None):
    if files is None:
        files = [HexFile("a.bin", b"..RIFF.."), HexFile("b.bin", b"....RIFF")]
    model = HexModel(files, width=16)
    return tui.MultiHexApp(
        model, ascii_on=True, only_diff=False, color_on=True,
        name_mode="basename", layout=layout,
    )


def _status_text(app):
    return str(app.query_one("#status").render())


def test_default_layout_is_stacked():
    async def go():
        app = _make_app()
        async with app.run_test() as pilot:
            await pilot.pause()
            assert app.view.layout_mode == "stacked"
            assert "layout:stacked" in _status_text(app)

    asyncio.run(go())


def test_starts_side_by_side_with_flag():
    async def go():
        app = _make_app(layout="side-by-side")
        async with app.run_test() as pilot:
            await pilot.pause()
            assert app.view.layout_mode == "side-by-side"
            assert "layout:side-by-side" in _status_text(app)

    asyncio.run(go())


def test_cycle_layout_toggles():
    async def go():
        app = _make_app()
        async with app.run_test() as pilot:
            await pilot.pause()
            app.action_cycle_layout()
            await pilot.pause()
            assert app.view.layout_mode == "side-by-side"
            assert "layout:side-by-side" in _status_text(app)
            app.action_cycle_layout()
            await pilot.pause()
            assert app.view.layout_mode == "stacked"

    asyncio.run(go())


def test_help_and_bindings_list_v():
    assert "  v " in tui.HelpScreen._HELP
    assert any(b.key == "v" for b in tui.MultiHexApp.BINDINGS)


def test_search_state_survives_layout_cycle():
    async def go():
        app = _make_app()
        async with app.run_test() as pilot:
            app._run_search("text", "RIFF")
            await pilot.pause()
            matches = app.search_matches
            index = app.search_index
            current = app.view.search_current
            assert matches and index == 0 and current is not None
            app.action_cycle_layout()
            await pilot.pause()
            # Cycling layout must not disturb the search.
            assert app.search_matches is matches
            assert app.search_index == index
            assert app.view.search_current is current

    asyncio.run(go())


def test_horizontal_scroll_in_side_by_side():
    async def go():
        # Three 16-byte files -> a side-by-side row far wider than the viewport.
        files = [
            HexFile("a.bin", bytes(range(16))),
            HexFile("b.bin", bytes(range(16, 32))),
            HexFile("c.bin", bytes(range(32, 48))),
        ]
        app = _make_app(layout="side-by-side", files=files)
        async with app.run_test(size=(40, 24)) as pilot:
            await pilot.pause()
            assert app.view.h_scroll == 0
            app.action_scroll_right()
            await pilot.pause()
            assert app.view.h_scroll > 0
            # Renders without error while scrolled.
            assert app.view.render().plain
            app.action_scroll_left()
            await pilot.pause()
            assert app.view.h_scroll == 0
            # Switching layout resets the horizontal scroll.
            app.action_cycle_layout()
            await pilot.pause()
            assert app.view.layout_mode == "stacked"
            assert app.view.h_scroll == 0

    asyncio.run(go())


def test_horizontal_scroll_in_stacked_when_row_overflows():
    async def go():
        # A wide stacked row (16-byte file + name + ASCII) far exceeds a 40-col
        # viewport, so horizontal scroll now engages in stacked too.
        files = [
            HexFile("a.bin", bytes(range(16))),
            HexFile("b.bin", bytes(range(16, 32))),
        ]
        app = _make_app(layout="stacked", files=files)
        async with app.run_test(size=(40, 24)) as pilot:
            await pilot.pause()
            assert app.view.layout_mode == "stacked"
            assert app.view.h_scroll == 0
            app.action_scroll_right()
            await pilot.pause()
            assert app.view.h_scroll > 0          # a wide row scrolls
            assert app.view.render().plain        # renders while scrolled
            app.action_scroll_left()
            await pilot.pause()
            assert app.view.h_scroll == 0

    asyncio.run(go())


def test_horizontal_scroll_noop_when_row_fits():
    async def go():
        # Tiny files in a wide viewport: the row fits, so scroll is a clamped
        # no-op (max_scroll is 0) in both layouts.
        files = [HexFile("a.bin", b"\x00\x01"), HexFile("b.bin", b"\x00\x02")]
        app = _make_app(layout="stacked", files=files)
        # Wide enough that even a width-16 side-by-side row fits with room.
        async with app.run_test(size=(260, 24)) as pilot:
            await pilot.pause()
            app.action_scroll_right()
            await pilot.pause()
            assert app.view.h_scroll == 0
            app.action_cycle_layout()
            await pilot.pause()
            app.action_scroll_right()
            await pilot.pause()
            assert app.view.h_scroll == 0

    asyncio.run(go())


def test_layout_does_not_change_offsets_or_markers():
    async def go():
        files = [HexFile("a.bin", b"AAAA"), HexFile("b.bin", b"AABA")]
        model = HexModel(files, width=16)
        app = tui.MultiHexApp(
            model, ascii_on=True, only_diff=False, color_on=False,
            name_mode="basename",
        )
        async with app.run_test() as pilot:
            await pilot.pause()
            stacked = app.view.render().plain
            app.action_cycle_layout()
            await pilot.pause()
            side = app.view.render().plain
            # Same offset header and same marker tokens in both layouts.
            assert "0x00000000" in stacked and "0x00000000" in side
            for tok in ("==", "!="):
                assert (tok in stacked) == (tok in side)

    asyncio.run(go())


def _no_offset_only_line(plain):
    """No rendered line is just the bare offset label (offset rides its data)."""
    return all(ln.strip() != "0x00000000" for ln in plain.splitlines())


def test_offset_attached_in_both_layouts():
    async def go():
        app = _make_app()
        async with app.run_test() as pilot:
            await pilot.pause()
            stacked = app.view.render().plain
            app.action_cycle_layout()
            await pilot.pause()
            side = app.view.render().plain
            # Neither layout emits a standalone offset line.
            assert _no_offset_only_line(stacked)
            assert _no_offset_only_line(side)
            # The offset sits at the start of a line that also carries data
            # (the first file's name appears on the offset's line).
            for plain in (stacked, side):
                off_line = next(
                    ln for ln in plain.splitlines() if "0x00000000" in ln
                )
                assert off_line.lstrip().startswith("0x00000000")
                assert "a.bin" in off_line

    asyncio.run(go())


def test_lines_per_block_drops_the_offset_line():
    async def go():
        app = _make_app()
        async with app.run_test() as pilot:
            await pilot.pause()
            view = app.view
            # Stacked: one line per file + a marker line + blank gap (no
            # separate offset line). Two files, markers on -> 2 + 1 + 1 = 4.
            assert view.layout_mode == "stacked"
            assert view._lines_per_block() == 4
            app.action_cycle_layout()
            await pilot.pause()
            # Side-by-side single: one combined data line + blank gap = 2.
            assert view._lines_per_block() == 2

    asyncio.run(go())
