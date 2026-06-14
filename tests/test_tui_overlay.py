# Copyright (c) 2026 Philip Cox
# SPDX-License-Identifier: Apache-2.0

"""TUI layout-overlay: load/clear/view state, status line, and cell-style tier.

Driven headless through Textual's test harness, mirroring test_tui_byte_classes.
"""

import asyncio
import json
import os
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import multihex.tui as tui  # noqa: E402
from multihex.core import HexFile, HexModel, Marker  # noqa: E402
from multihex.overlay import OverlayState  # noqa: E402

pytestmark = pytest.mark.skipif(
    tui._TEXTUAL_IMPORT_ERROR is not None, reason="textual not installed"
)

SCHEMA = {"name": "bintools.layout-overlay", "version": 1}


def _make_app(overlay=None, color_on=True):
    data = bytes(range(16))
    f1 = HexFile("a.bin", data)
    f2 = HexFile("b.bin", data)
    model = HexModel([f1, f2], width=16)
    return tui.MultiHexApp(
        model, ascii_on=True, only_diff=False, color_on=color_on,
        name_mode="basename", overlay=overlay,
    )


def _write(tmp_path, name, doc):
    p = tmp_path / name
    p.write_text(json.dumps(doc))
    return str(p)


def _status_text(app):
    return str(app.query_one("#status").render())


def test_load_clear_and_status(tmp_path):
    path = _write(tmp_path, "ov.json", {
        "schema": SCHEMA, "name": "demo",
        "ranges": [{"path": "magic", "offset": 0, "length": 2}],
    })

    async def go():
        app = _make_app()
        async with app.run_test() as pilot:
            assert app.overlay is None
            assert "overlay:" not in _status_text(app)

            app._apply_overlay(path)
            await pilot.pause()
            assert app.overlay is not None and app.overlay.applicable
            assert app.view.overlay is app.overlay
            assert "overlay:on" in _status_text(app)

            app._apply_overlay("")  # blank clears
            await pilot.pause()
            assert app.overlay is None
            assert app.view.overlay is None
            assert "overlay:" not in _status_text(app)

    asyncio.run(go())


def test_cancel_leaves_overlay_untouched(tmp_path):
    path = _write(tmp_path, "ov.json", {
        "schema": SCHEMA, "ranges": [{"offset": 0, "length": 2}],
    })

    async def go():
        app = _make_app()
        async with app.run_test() as pilot:
            app._apply_overlay(path)
            await pilot.pause()
            assert app.overlay is not None
            app._apply_overlay(None)  # cancelled prompt
            await pilot.pause()
            assert app.overlay is not None  # unchanged

    asyncio.run(go())


def test_error_overlay_loaded_but_not_applied(tmp_path):
    path = _write(tmp_path, "err.json", {
        "schema": SCHEMA,
        "ranges": [
            {"path": "dup", "offset": 0, "length": 1},
            {"path": "dup", "offset": 1, "length": 1},
        ],
    })

    async def go():
        app = _make_app()
        async with app.run_test() as pilot:
            app._apply_overlay(path)
            await pilot.pause()
            assert app.overlay is not None
            assert app.overlay.applicable is False
            # Kept for viewing, but the status shows it is not applied.
            assert "overlay:err" in _status_text(app)
            # Never highlights.
            assert app.view._cell_style(0, 0, Marker.SAME, 0x00) == ""

    asyncio.run(go())


def test_cell_style_overlay_priority(tmp_path):
    doc = {"schema": SCHEMA, "ranges": [{"offset": 0, "length": 2}]}
    f = HexFile("a.bin", bytes(16))
    overlay = OverlayState.load(_write(tmp_path, "ov.json", doc), [f])
    assert overlay.applicable

    async def go():
        app = _make_app(overlay=overlay)
        async with app.run_test() as pilot:
            await pilot.pause()
            v = app.view
            # SAME + covered -> overlay style.
            assert v._cell_style(0, 0, Marker.SAME, 0x00) == tui._OVERLAY_STYLE
            # Uncovered offset -> no style.
            assert v._cell_style(0, 5, Marker.SAME, 0x05) == ""
            # Diff beats overlay.
            assert v._cell_style(0, 0, Marker.DIFF, 0x00) == tui._DIFF_STYLE
            # Color off -> no overlay style.
            v.color_on = False
            assert v._cell_style(0, 0, Marker.SAME, 0x00) == ""

    asyncio.run(go())


def test_view_overlay_no_overlay_is_safe():
    async def go():
        app = _make_app()
        async with app.run_test() as pilot:
            app.action_view_overlay()  # should not raise / push a screen
            await pilot.pause()
            assert app.overlay is None

    asyncio.run(go())


def test_help_lists_overlay_keys():
    assert "  l " in tui.HelpScreen._HELP
    assert "  L " in tui.HelpScreen._HELP
