# Copyright (c) 2026 Philip Cox
# SPDX-License-Identifier: Apache-2.0

"""TUI byte-class highlighting: default state, toggle, status/help, priority.

Driven headless through Textual's test harness, mirroring test_tui_search.
"""

import asyncio
import os
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import multihex.tui as tui  # noqa: E402
from multihex.core import HexFile, HexModel, Marker  # noqa: E402

pytestmark = pytest.mark.skipif(
    tui._TEXTUAL_IMPORT_ERROR is not None, reason="textual not installed"
)


def _make_app(byte_classes_on=False, color_on=True):
    # Two identical files: 'A' (printable), space (ws), NUL (zero), 0xFF (other).
    data = b"A \x00\xff"
    f1 = HexFile("a.bin", data)
    f2 = HexFile("b.bin", data)
    model = HexModel([f1, f2], width=16)
    return tui.MultiHexApp(
        model, ascii_on=True, only_diff=False, color_on=color_on,
        name_mode="basename", byte_classes_on=byte_classes_on,
    )


def _status_text(app):
    return str(app.query_one("#status").render())


def test_default_off_and_toggle():
    async def go():
        app = _make_app()
        async with app.run_test() as pilot:
            assert app.view.byte_classes_on is False
            assert "classes:off" in _status_text(app)
            app.action_toggle_byte_classes()
            await pilot.pause()
            assert app.view.byte_classes_on is True
            assert "classes:on" in _status_text(app)
            app.action_toggle_byte_classes()
            await pilot.pause()
            assert app.view.byte_classes_on is False

    asyncio.run(go())


def test_starts_on_with_flag():
    async def go():
        app = _make_app(byte_classes_on=True)
        async with app.run_test() as pilot:
            await pilot.pause()
            assert app.view.byte_classes_on is True
            assert "classes:on" in _status_text(app)

    asyncio.run(go())


def test_help_lists_t_key():
    assert "\n" in tui.HelpScreen._HELP
    assert "  t " in tui.HelpScreen._HELP


def test_cell_style_byte_class_lowest_priority():
    async def go():
        app = _make_app(byte_classes_on=True)
        async with app.run_test() as pilot:
            await pilot.pause()
            v = app.view
            # SAME + printable 'A' -> green only when both color & classes on.
            assert v._cell_style(0, 0, Marker.SAME, 0x41) == "green"
            v.byte_classes_on = False
            assert v._cell_style(0, 0, Marker.SAME, 0x41) == ""
            v.byte_classes_on = True
            v.color_on = False
            assert v._cell_style(0, 0, Marker.SAME, 0x41) == ""
            v.color_on = True
            # A diff column still wins over byte class.
            assert v._cell_style(0, 0, Marker.DIFF, 0x41) == tui._DIFF_STYLE
            # Missing value never gets a byte-class style.
            assert v._cell_style(0, 0, Marker.SAME, None) == ""

    asyncio.run(go())


def test_search_match_beats_byte_class():
    async def go():
        f1 = HexFile("a.bin", b"AAAA")  # printable; search will cover a cell
        f2 = HexFile("b.bin", b"AAAA")
        model = HexModel([f1, f2], width=16)
        app = tui.MultiHexApp(
            model, ascii_on=True, only_diff=False, color_on=True,
            name_mode="basename", byte_classes_on=True,
        )
        async with app.run_test() as pilot:
            app._run_search("text", "AA")
            await pilot.pause()
            # The first match's first byte must render as the current-match
            # style, not the green byte-class style.
            assert app.view._cell_style(0, 0, Marker.SAME, 0x41) == tui._SEARCH_CUR_STYLE

    asyncio.run(go())
