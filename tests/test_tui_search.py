# Copyright (c) 2026 Philip Cox
# SPDX-License-Identifier: Apache-2.0

"""TUI search behaviour, driven headless through Textual's test harness.

These call the app's search entry points directly (the modal input is trivial
glue) and assert on the resulting state and the search status line. Wrapped in
asyncio.run so no pytest-asyncio plugin is required.
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


def _make_app():
    f1 = HexFile("a.bin", b"..RIFF..")      # match at offset 2
    f2 = HexFile("b.bin", b"....RIFF")      # match at offset 4
    model = HexModel([f1, f2], width=16)
    return tui.MultiHexApp(
        model, ascii_on=True, only_diff=False, color_on=True, name_mode="basename"
    )


def _status_text(app):
    return str(app.query_one("#search_status").render())


def _make_big_zero_app(nbytes):
    f = HexFile("big.bin", bytes(nbytes))
    model = HexModel([f], width=16)
    return tui.MultiHexApp(
        model, ascii_on=True, only_diff=False, color_on=True, name_mode="basename"
    )


def test_search_truncates_at_default_cap():
    from multihex.core import DEFAULT_SEARCH_MAX_RESULTS

    async def go():
        # One byte past the cap so the search reports truncation.
        app = _make_big_zero_app(DEFAULT_SEARCH_MAX_RESULTS + 1)
        async with app.run_test() as pilot:
            app._run_search("hex", "00")
            await pilot.pause()
            assert len(app.search_matches) == DEFAULT_SEARCH_MAX_RESULTS
            assert app.search_truncated is True
            status = _status_text(app)
            assert "capped; more matches exist" in status
            # Navigation still cycles within the capped set.
            app.action_next_match()
            await pilot.pause()
            assert app.search_index == 1

    asyncio.run(go())


def test_search_under_cap_is_not_truncated():
    async def go():
        app = _make_app()
        async with app.run_test() as pilot:
            app._run_search("text", "RIFF")
            await pilot.pause()
            assert app.search_truncated is False
            assert "capped" not in _status_text(app)

    asyncio.run(go())


def test_text_search_sets_state_and_status():
    async def go():
        app = _make_app()
        async with app.run_test() as pilot:
            app._run_search("text", "RIFF")
            await pilot.pause()
            assert [(m.file_index, m.offset) for m in app.search_matches] == [
                (0, 2),
                (1, 4),
            ]
            assert app.search_index == 0
            status = _status_text(app)
            assert 'text "RIFF"' in status
            assert "match 1/2" in status
            assert "offset 0x00000002" in status
            # highlight state wired into the view
            assert app.view.search_current is app.search_matches[0]
            assert app.view._search_covered

    asyncio.run(go())


def test_next_and_prev_wraparound():
    async def go():
        app = _make_app()
        async with app.run_test() as pilot:
            app._run_search("text", "RIFF")
            await pilot.pause()
            app.action_next_match()
            await pilot.pause()
            assert app.search_index == 1
            assert "match 2/2" in _status_text(app)
            app.action_next_match()           # wrap to first
            await pilot.pause()
            assert app.search_index == 0
            app.action_prev_match()           # wrap to last
            await pilot.pause()
            assert app.search_index == 1

    asyncio.run(go())


def test_no_match_status():
    async def go():
        app = _make_app()
        async with app.run_test() as pilot:
            app._run_search("text", "ZZZZ")
            await pilot.pause()
            assert app.search_matches == []
            assert app.search_index is None
            assert "no matches" in _status_text(app)

    asyncio.run(go())


def test_invalid_hex_sets_error_without_crashing():
    async def go():
        app = _make_app()
        async with app.run_test() as pilot:
            app._run_search("hex", "GG")
            await pilot.pause()
            assert app.search_error is not None
            assert app.search_query is None
            assert "Search error" in _status_text(app)
            assert 'invalid hex byte "GG"' in _status_text(app)
            # app stays usable: a valid search afterwards recovers
            app._run_search("hex", "52 49 46 46")
            await pilot.pause()
            assert app.search_error is None
            assert len(app.search_matches) == 2

    asyncio.run(go())


def test_hex_search_matches_text():
    async def go():
        app = _make_app()
        async with app.run_test() as pilot:
            app._run_search("hex", "52 49 46 46")   # "RIFF"
            await pilot.pause()
            assert [(m.file_index, m.offset) for m in app.search_matches] == [
                (0, 2),
                (1, 4),
            ]

    asyncio.run(go())


def test_text_search_preserves_significant_whitespace():
    async def go():
        f1 = HexFile("a.bin", b"xx RIFF yy   zzRIFF")
        model = HexModel([f1], width=16)
        app = tui.MultiHexApp(
            model, ascii_on=True, only_diff=False, color_on=True,
            name_mode="basename",
        )
        async with app.run_test() as pilot:
            app._run_search("text", " RIFF ")
            await pilot.pause()
            assert [m.offset for m in app.search_matches] == [2]
            assert app.search_query.pattern == " RIFF "
            assert app.search_query.needle == b" RIFF "

            app._run_search("text", "   ")
            await pilot.pause()
            assert [m.offset for m in app.search_matches] == [10]
            assert app.search_query.pattern == "   "
            assert app.search_query.needle == b"   "

            matches = app.search_matches
            query = app.search_query
            index = app.search_index
            app._run_search("hex", "   ")
            await pilot.pause()
            assert app.search_matches is matches
            assert app.search_query is query
            assert app.search_index == index

    asyncio.run(go())


def _mixed_case_app():
    f1 = HexFile("a.bin", b"FooFOOfoo")
    model = HexModel([f1], width=16)
    return tui.MultiHexApp(
        model, ascii_on=True, only_diff=False, color_on=True, name_mode="basename"
    )


def test_text_search_default_is_case_sensitive():
    async def go():
        app = _mixed_case_app()
        async with app.run_test() as pilot:
            # No ignore_case -> case-sensitive: only the lowercase "foo" matches.
            app._run_search("text", "foo")
            await pilot.pause()
            assert [m.offset for m in app.search_matches] == [6]
            assert "(ci)" not in _status_text(app)

    asyncio.run(go())


def test_text_search_case_insensitive_matches_and_navigates():
    async def go():
        app = _mixed_case_app()
        async with app.run_test() as pilot:
            app._run_search("text", "foo", ignore_case=True)
            await pilot.pause()
            assert [m.offset for m in app.search_matches] == [0, 3, 6]
            assert app.search_index == 0
            assert "(ci)" in _status_text(app)
            # existing n/N/p navigation still works over the result set
            app.action_next_match()
            await pilot.pause()
            assert app.search_index == 1
            app.action_prev_match()
            await pilot.pause()
            assert app.search_index == 0
            # highlight wired up on the matched bytes
            assert app.view.search_current is app.search_matches[0]
            assert app.view._search_covered

    asyncio.run(go())


def test_run_text_search_remembers_session_pref():
    async def go():
        app = _make_app()
        async with app.run_test() as pilot:
            assert app.text_search_ignore_case is False
            app._run_text_search(("RIFF", True))
            await pilot.pause()
            assert app.text_search_ignore_case is True
            # a cancelled (None) prompt leaves state untouched
            app._run_text_search(None)
            await pilot.pause()
            assert app.text_search_ignore_case is True

    asyncio.run(go())


def test_hex_search_finds_byte_not_ascii_spelling():
    async def go():
        f1 = HexFile("a.bin", bytes([0xD9]) + b"D9")  # 0xd9, then 0x44 0x39
        model = HexModel([f1], width=16)
        app = tui.MultiHexApp(
            model, ascii_on=True, only_diff=False, color_on=True,
            name_mode="basename",
        )
        async with app.run_test() as pilot:
            app._run_search("hex", "D9")
            await pilot.pause()
            # finds the 0xd9 byte at offset 0, not the ASCII "D9" at offset 1
            assert [(m.file_index, m.offset) for m in app.search_matches] == [(0, 0)]

    asyncio.run(go())


def test_text_panel_exposes_case_insensitive_checkbox():
    async def go():
        from textual.widgets import Checkbox

        app = _make_app()
        async with app.run_test() as pilot:
            app.action_search_text()
            await pilot.pause()
            assert isinstance(app.screen, tui.TextSearchScreen)
            assert len(app.screen.query(Checkbox)) == 1

    asyncio.run(go())


def test_hex_panel_has_no_case_toggle():
    async def go():
        from textual.widgets import Checkbox

        app = _make_app()
        async with app.run_test() as pilot:
            app.action_search_hex()
            await pilot.pause()
            assert isinstance(app.screen, tui._PromptScreen)
            assert len(app.screen.query(Checkbox)) == 0

    asyncio.run(go())


def test_text_panel_submit_runs_search():
    """End-to-end: typing in the panel and pressing Enter runs a text search."""
    async def go():
        app = _make_app()
        async with app.run_test() as pilot:
            app.action_search_text()
            await pilot.pause()
            await pilot.press("R", "I", "F", "F")
            await pilot.press("enter")
            await pilot.pause()
            assert [(m.file_index, m.offset) for m in app.search_matches] == [
                (0, 2),
                (1, 4),
            ]
            # default checkbox state -> case-sensitive
            assert app.text_search_ignore_case is False

    asyncio.run(go())


def test_text_panel_seeds_checkbox_from_session_pref():
    async def go():
        from textual.widgets import Checkbox

        app = _make_app()
        async with app.run_test() as pilot:
            app.text_search_ignore_case = True
            app.action_search_text()
            await pilot.pause()
            assert app.screen.query_one(Checkbox).value is True

    asyncio.run(go())
