# Copyright (c) 2026 Philip Cox
# SPDX-License-Identifier: Apache-2.0

"""TUI settings pane: open with 'o', view/change settings, save, save failure.

Headless through Textual's test harness, mirroring test_tui_search. The modal is
pushed onto the screen stack, so queries use ``app.screen.query_one(...)``.
"""

import asyncio
import os
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import multihex.tui as tui  # noqa: E402
from multihex.core import HexFile, HexModel  # noqa: E402
from multihex.tui_config import TuiSettings, load_settings  # noqa: E402

pytestmark = pytest.mark.skipif(
    tui._TEXTUAL_IMPORT_ERROR is not None, reason="textual not installed"
)


def _make_app(config_path, layout="stacked", color_mode="auto"):
    files = [HexFile("a.bin", bytes(range(20))), HexFile("b.bin", bytes(range(5, 25)))]
    model = HexModel(files, width=16)
    return tui.MultiHexApp(
        model, ascii_on=True, only_diff=False, color_on=True, name_mode="basename",
        layout=layout, color_mode=color_mode, config_path=config_path,
    )


def _body(app):
    return str(app.screen.query_one("#settings_body").render())


def test_o_opens_pane_showing_settings_and_path():
    async def go():
        cfg = "/tmp/multihex-test-unused.toml"
        app = _make_app(cfg)
        async with app.run_test(size=(80, 30)) as pilot:
            await pilot.pause()
            await pilot.press("o")
            await pilot.pause()
            assert type(app.screen).__name__ == "SettingsScreen"
            body = _body(app)
            for label in ("layout", "ascii", "byte classes", "color", "names",
                          "markers", "width", "only-diff"):
                assert label in body
            assert cfg in body                 # active config path shown

    asyncio.run(go())


def test_pane_changes_apply_to_running_view(tmp_path):
    async def go():
        app = _make_app(str(tmp_path / "tui.toml"))
        async with app.run_test(size=(80, 30)) as pilot:
            await pilot.pause()
            await pilot.press("o")
            await pilot.pause()
            # Row 0 is layout: change it and confirm the live view updated.
            await pilot.press("right")
            await pilot.pause()
            assert app.view.layout_mode == "side-by-side"
            assert "layout:side-by-side" in str(app.query_one("#status").render())
            # ascii row (index 1): toggle off.
            await pilot.press("down", "right")
            await pilot.pause()
            assert app.view.ascii_on is False

    asyncio.run(go())


def test_each_saved_setting_is_changeable_and_persisted(tmp_path):
    async def go():
        cfg = tmp_path / "tui.toml"
        app = _make_app(str(cfg))
        async with app.run_test(size=(80, 30)) as pilot:
            await pilot.pause()
            await pilot.press("o")
            await pilot.pause()
            # Touch every row: layout, ascii, byte_classes, color, names,
            # markers, width, only_diff
            await pilot.press("right")                       # layout
            await pilot.press("down", "right")               # ascii
            await pilot.press("down", "right")               # byte_classes
            await pilot.press("down", "right")               # color
            await pilot.press("down", "right")               # names
            await pilot.press("down", "right")               # markers
            await pilot.press("down", "right")               # width +1
            await pilot.press("down", "right")               # only_diff
            await pilot.pause()
            await pilot.press("s")                           # save
            await pilot.pause()

            loaded, warnings = load_settings(cfg, TuiSettings())
            assert warnings == []
            assert loaded.layout == "side-by-side"
            assert loaded.ascii is False
            assert loaded.byte_classes is True
            assert loaded.color == "always"
            assert loaded.names == "path"
            assert loaded.markers == "repeat"
            assert loaded.width == 17
            assert loaded.only_diff is True

    asyncio.run(go())


def test_save_failure_is_surfaced_without_crashing(tmp_path):
    async def go():
        # config_path's parent is a regular file -> save raises OSError, which the
        # app must catch and surface as a notification (not crash).
        blocker = tmp_path / "afile"
        blocker.write_text("x")
        app = _make_app(str(blocker / "tui.toml"))
        async with app.run_test(size=(80, 30)) as pilot:
            await pilot.pause()
            await pilot.press("o")
            await pilot.pause()
            await pilot.press("s")              # attempt save -> fails internally
            await pilot.pause()
            # App still alive and the pane still open.
            assert type(app.screen).__name__ == "SettingsScreen"
            assert not (blocker / "tui.toml").exists()

    asyncio.run(go())


def test_esc_closes_without_requiring_save(tmp_path):
    async def go():
        cfg = tmp_path / "tui.toml"
        app = _make_app(str(cfg))
        async with app.run_test(size=(80, 30)) as pilot:
            await pilot.pause()
            await pilot.press("o")
            await pilot.pause()
            await pilot.press("right")          # change applied live
            await pilot.press("escape")
            await pilot.pause()
            assert type(app.screen).__name__ != "SettingsScreen"
            assert not cfg.exists()             # closing alone never writes

    asyncio.run(go())


def test_help_and_bindings_list_o():
    assert "  o " in tui.HelpScreen._HELP
    assert any(b.key == "o" for b in tui.MultiHexApp.BINDINGS)
