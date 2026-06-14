# Copyright (c) 2026 Philip Cox
# SPDX-License-Identifier: Apache-2.0

"""Headless TUI key-binding dispatch tests (skip without textual).

These drive the real ``BINDINGS`` table via ``pilot.press(...)`` rather than
calling ``action_*`` methods directly, so a wrong key or a mis-wired action_id
is caught. The per-action behaviour itself is asserted in detail elsewhere
(test_tui_search, test_tui_byte_classes, test_tui_markers, test_tui_layout,
test_tui_home_end); here we verify the key -> action wiring and the observable
effect of each single-key binding.
"""

import asyncio
import json

import pytest

import multihex.tui as tui
from multihex.core import HexFile, HexModel

pytestmark = pytest.mark.skipif(
    tui._TEXTUAL_IMPORT_ERROR is not None, reason="textual not installed"
)

SIZE = (80, 24)
SCHEMA = {"name": "bintools.layout-overlay", "version": 1}


def _app(files=None, **kw):
    if files is None:
        files = _pair()
    model = HexModel(files, width=16)
    return tui.MultiHexApp(
        model, ascii_on=True, only_diff=False, color_on=True,
        name_mode="basename", **kw,
    )


def _pair(nbytes=1024):
    data = bytes((i * 7) % 256 for i in range(nbytes))
    return [HexFile("a.bin", data), HexFile("b.bin", data)]


# --- navigation ------------------------------------------------------------

def test_j_k_scroll_one_row():
    async def go():
        app = _app()
        async with app.run_test(size=SIZE) as pilot:
            await pilot.pause()
            assert app.view.top == 0
            await pilot.press("j")
            await pilot.pause()
            assert app.view.top == 1
            await pilot.press("k")
            await pilot.pause()
            assert app.view.top == 0

    asyncio.run(go())


def test_pagedown_pageup_move_by_page():
    async def go():
        app = _app()
        async with app.run_test(size=SIZE) as pilot:
            await pilot.pause()
            await pilot.press("pagedown")
            await pilot.pause()
            after_page = app.view.top
            assert after_page > 1           # moved more than a single row
            await pilot.press("pageup")
            await pilot.pause()
            assert app.view.top < after_page

    asyncio.run(go())


# --- display toggles -------------------------------------------------------

def test_toggle_keys_flip_view_state():
    async def go():
        app = _app()
        async with app.run_test(size=SIZE) as pilot:
            await pilot.pause()
            v = app.view

            assert v.color_on is True
            await pilot.press("c")
            await pilot.pause()
            assert v.color_on is False

            assert v.byte_classes_on is False
            await pilot.press("t")
            await pilot.pause()
            assert v.byte_classes_on is True

            assert v.ascii_on is True
            await pilot.press("a")
            await pilot.pause()
            assert v.ascii_on is False

            assert v.only_diff is False
            await pilot.press("d")
            await pilot.pause()
            assert v.only_diff is True

            assert v.layout_mode == "stacked"
            await pilot.press("v")
            await pilot.pause()
            assert v.layout_mode == "side-by-side"

            assert v.markers_mode == "single"
            await pilot.press("m")
            await pilot.pause()
            assert v.markers_mode == "repeat"

    asyncio.run(go())


# --- search navigation -----------------------------------------------------

def test_n_p_keys_step_through_matches():
    async def go():
        app = _app()
        async with app.run_test(size=SIZE) as pilot:
            await pilot.pause()
            # Seed a search with several matches, then drive nav by key.
            app._run_search("hex", "07")
            await pilot.pause()
            assert len(app.search_matches) > 2
            start = app.search_index
            await pilot.press("n")
            await pilot.pause()
            assert app.search_index != start
            after_n = app.search_index
            await pilot.press("p")
            await pilot.pause()
            assert app.search_index == start
            # 'N' is an alias for previous.
            await pilot.press("N")
            await pilot.pause()
            assert app.search_index != start
            assert app.search_index != after_n or len(app.search_matches) == 2

    asyncio.run(go())


# --- modal openers ---------------------------------------------------------

@pytest.mark.parametrize(
    "key, screen_name",
    [
        ("slash", "TextSearchScreen"),
        ("x", "_PromptScreen"),       # hex search prompt
        ("g", "_PromptScreen"),       # jump-to-offset prompt
        ("r", "_PromptScreen"),       # choose-ref prompt
        ("l", "_PromptScreen"),       # load-overlay prompt
        ("o", "SettingsScreen"),
        ("h", "HelpScreen"),
        ("question_mark", "HelpScreen"),
    ],
)
def test_key_opens_modal_then_escape_closes(key, screen_name):
    async def go():
        app = _app()
        async with app.run_test(size=SIZE) as pilot:
            await pilot.pause()
            assert len(app.screen_stack) == 1
            await pilot.press(key)
            await pilot.pause()
            assert type(app.screen).__name__ == screen_name
            assert len(app.screen_stack) == 2
            await pilot.press("escape")
            await pilot.pause()
            assert len(app.screen_stack) == 1

    asyncio.run(go())


# --- dialog error / cancel paths ------------------------------------------

def _set_prompt(app, value):
    from textual.widgets import Input
    app.screen.query_one(Input).value = value


def test_jump_bad_offset_rings_bell_and_keeps_position():
    async def go():
        app = _app()
        async with app.run_test(size=SIZE) as pilot:
            await pilot.pause()
            bells = []
            app.bell = lambda *a, **k: bells.append(1)
            top0 = app.view.top
            await pilot.press("g")
            await pilot.pause()
            _set_prompt(app, "not-a-number")
            await pilot.press("enter")
            await pilot.pause()
            assert bells == [1]
            assert app.view.top == top0

    asyncio.run(go())


def test_choose_ref_out_of_range_rings_bell_and_keeps_ref():
    async def go():
        app = _app()
        async with app.run_test(size=SIZE) as pilot:
            await pilot.pause()
            bells = []
            app.bell = lambda *a, **k: bells.append(1)
            ref0 = app.model.ref
            await pilot.press("r")
            await pilot.pause()
            _set_prompt(app, "99")           # only two files loaded
            await pilot.press("enter")
            await pilot.pause()
            assert bells == [1]
            assert app.model.ref == ref0

    asyncio.run(go())


def test_jump_cancel_is_a_noop():
    async def go():
        app = _app()
        async with app.run_test(size=SIZE) as pilot:
            await pilot.pause()
            bells = []
            app.bell = lambda *a, **k: bells.append(1)
            top0 = app.view.top
            await pilot.press("g")
            await pilot.pause()
            await pilot.press("escape")       # cancel -> handle(None)
            await pilot.pause()
            assert bells == []
            assert app.view.top == top0
            assert len(app.screen_stack) == 1

    asyncio.run(go())


def test_view_overlay_key_opens_overlay_screen(tmp_path):
    path = tmp_path / "ov.json"
    path.write_text(json.dumps({
        "schema": SCHEMA, "name": "demo",
        "ranges": [{"path": "magic", "offset": 0, "length": 2}],
    }))

    async def go():
        app = _app()
        async with app.run_test(size=SIZE) as pilot:
            await pilot.pause()
            app._apply_overlay(str(path))
            await pilot.pause()
            assert app.overlay is not None and app.overlay.applicable
            await pilot.press("L")            # view current overlay
            await pilot.pause()
            assert type(app.screen).__name__ == "OverlayScreen"
            await pilot.press("escape")
            await pilot.pause()
            assert len(app.screen_stack) == 1

    asyncio.run(go())
