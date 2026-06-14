# Copyright (c) 2026 Philip Cox
# SPDX-License-Identifier: Apache-2.0

"""TUI --markers: default/start state, the 'm' cycle key, status/help, and the
display-only guarantee (cycling never disturbs markers, search, or filtering).

Driven headless through Textual's test harness, mirroring test_tui_layout.
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


def _make_app(markers="single", layout="stacked", files=None):
    if files is None:
        files = [HexFile("a.bin", b"AAAA"), HexFile("b.bin", b"AABA")]
    model = HexModel(files, width=16)
    return tui.MultiHexApp(
        model, ascii_on=True, only_diff=False, color_on=True,
        name_mode="basename", layout=layout, markers=markers,
    )


def _status_text(app):
    return str(app.query_one("#status").render())


def _has_strip(plain):
    # "==" / "!=" only ever appear in a marker strip (byte cells are hex).
    return "==" in plain or "!=" in plain


def test_default_markers_is_single():
    async def go():
        app = _make_app()
        async with app.run_test() as pilot:
            await pilot.pause()
            assert app.view.markers_mode == "single"
            assert "markers:single" in _status_text(app)

    asyncio.run(go())


def test_starts_repeat_with_flag():
    async def go():
        app = _make_app(markers="repeat")
        async with app.run_test() as pilot:
            await pilot.pause()
            assert app.view.markers_mode == "repeat"
            assert "markers:repeat" in _status_text(app)

    asyncio.run(go())


def test_starts_none_with_flag_hides_text():
    async def go():
        app = _make_app(markers="none")
        async with app.run_test() as pilot:
            await pilot.pause()
            assert app.view.markers_mode == "none"
            assert "markers:none" in _status_text(app)
            assert not _has_strip(app.view.render().plain)

    asyncio.run(go())


def test_cycle_markers_order_and_status_and_redraw():
    async def go():
        app = _make_app()
        async with app.run_test() as pilot:
            await pilot.pause()
            before = app.view.render().plain
            app.action_cycle_markers()
            await pilot.pause()
            assert app.view.markers_mode == "repeat"
            assert "markers:repeat" in _status_text(app)
            app.action_cycle_markers()
            await pilot.pause()
            assert app.view.markers_mode == "none"
            assert "markers:none" in _status_text(app)
            none_render = app.view.render().plain
            # Hiding the strip must actually change the rendered view.
            assert none_render != before
            assert not _has_strip(none_render)
            app.action_cycle_markers()
            await pilot.pause()
            assert app.view.markers_mode == "single"

    asyncio.run(go())


def test_help_and_bindings_list_m():
    assert "  m " in tui.HelpScreen._HELP
    assert any(b.key == "m" for b in tui.MultiHexApp.BINDINGS)


def test_markers_cycle_preserves_offsets_and_marker_computation():
    async def go():
        app = _make_app()
        async with app.run_test() as pilot:
            await pilot.pause()
            single = app.view.render().plain
            assert "0x00000000" in single and _has_strip(single)
            app.action_cycle_markers()  # repeat (same as single when stacked)
            await pilot.pause()
            assert app.view.render().plain == single

    asyncio.run(go())


def test_search_state_survives_markers_cycle():
    async def go():
        files = [HexFile("a.bin", b"..RIFF.."), HexFile("b.bin", b"....RIFF")]
        app = _make_app(files=files)
        async with app.run_test() as pilot:
            app._run_search("text", "RIFF")
            await pilot.pause()
            matches = app.search_matches
            index = app.search_index
            current = app.view.search_current
            assert matches and index == 0 and current is not None
            app.action_cycle_markers()
            await pilot.pause()
            assert app.search_matches is matches
            assert app.search_index == index
            assert app.view.search_current is current

    asyncio.run(go())


def test_side_by_side_repeat_renders_more_marker_lines_than_single():
    async def go():
        files = [
            HexFile("a.bin", bytes(range(16))),
            HexFile("b.bin", bytes(range(16, 32))),
        ]
        app = _make_app(markers="single", layout="side-by-side", files=files)
        async with app.run_test(size=(120, 24)) as pilot:
            await pilot.pause()
            single_lines = app.view.render().plain.splitlines()
            app.action_cycle_markers()  # repeat
            await pilot.pause()
            repeat_lines = app.view.render().plain.splitlines()
            # repeat adds a dedicated marker line under the (single) data row.
            assert len(repeat_lines) > len(single_lines)
            # And a pure marker-token line exists only in repeat.
            def pure(lines):
                return [
                    ln for ln in lines
                    if ln.split() and all(t in ("==", "!=", "--") for t in ln.split())
                ]
            assert pure(repeat_lines) and not pure(single_lines)

    asyncio.run(go())
