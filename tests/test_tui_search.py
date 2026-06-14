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
