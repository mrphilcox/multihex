"""Headless TUI Home/End navigation tests (state-level; skip without textual).

Home jumps to the start of the compared range; End is the bottom-anchored final
page. Both touch navigation state only -- never comparison or search state -- and
stay stable with empty data, zero diff rows, uneven lengths, and explicit
offset/length windows.
"""

import asyncio

import pytest

import multihex.tui as tui
from multihex.core import HexFile, HexModel

pytestmark = pytest.mark.skipif(
    tui._TEXTUAL_IMPORT_ERROR is not None, reason="textual not installed"
)

SIZE = (80, 24)


def _app(files, *, only_diff=False, offset=0, width=16, length=None, ref=None):
    model = HexModel(
        files, start_offset=offset, width=width, length=length, ref=ref
    )
    return tui.MultiHexApp(
        model, ascii_on=True, only_diff=only_diff, color_on=True,
        name_mode="basename",
    )


def _pair(nbytes=1024):
    data = bytes((i * 7) % 256 for i in range(nbytes))
    return [HexFile("a.bin", data), HexFile("b.bin", data)]


def test_home_returns_to_range_start():
    async def go():
        app = _app(_pair())
        async with app.run_test(size=SIZE) as pilot:
            await pilot.pause()
            await pilot.press("end")
            await pilot.pause()
            assert app.view.top > 0
            await pilot.press("home")
            await pilot.pause()
            assert app.view.top == 0
            assert (
                app.model.row_offset(app.view.current_top_row())
                == app.model.start_offset
            )

    asyncio.run(go())


def test_end_is_bottom_anchored_final_page():
    async def go():
        app = _app(_pair())
        async with app.run_test(size=SIZE) as pilot:
            await pilot.pause()
            await pilot.press("end")
            await pilot.pause()
            v = app.view
            assert v.top == v._max_top()
            # The final row is on the visible page (bottom-anchored, not top-anchored).
            assert v.top + v._page_rows >= v.visible_count

    asyncio.run(go())


def test_offset_respected_home_goes_to_offset_not_zero():
    async def go():
        app = _app(_pair(), offset=0x40)
        async with app.run_test(size=SIZE) as pilot:
            await pilot.pause()
            await pilot.press("end")
            await pilot.pause()
            await pilot.press("home")
            await pilot.pause()
            assert app.view.top == 0
            assert app.model.row_offset(app.view.current_top_row()) == 0x40

    asyncio.run(go())


def test_length_window_end_stays_within_bounds():
    async def go():
        app = _app(_pair(), length=5 * 16)  # a bounded 5-row window
        async with app.run_test(size=SIZE) as pilot:
            await pilot.pause()
            assert app.view.visible_count == 5
            await pilot.press("end")
            await pilot.pause()
            assert app.view.top == app.view._max_top()

    asyncio.run(go())


def test_empty_files_home_end_are_stable():
    async def go():
        app = _app([HexFile("a.bin", b""), HexFile("b.bin", b"")])
        async with app.run_test(size=SIZE) as pilot:
            await pilot.pause()
            assert app.view.visible_count == 0
            await pilot.press("end")
            await pilot.pause()
            assert app.view.top == 0
            await pilot.press("home")
            await pilot.pause()
            assert app.view.top == 0

    asyncio.run(go())


def test_only_diff_zero_rows_home_end_are_stable():
    async def go():
        app = _app(_pair(), only_diff=True)  # identical files -> no diff rows
        async with app.run_test(size=SIZE) as pilot:
            await pilot.pause()
            assert app.view.visible_count == 0
            await pilot.press("end")
            await pilot.pause()
            assert app.view.top == 0
            await pilot.press("home")
            await pilot.pause()
            assert app.view.top == 0

    asyncio.run(go())


def test_uneven_lengths_end_reaches_final_page():
    async def go():
        a = HexFile("a.bin", bytes(1024))  # 64 rows
        b = HexFile("b.bin", bytes(16))    # 1 row; the rest renders as missing
        app = _app([a, b])
        async with app.run_test(size=SIZE) as pilot:
            await pilot.pause()
            assert app.view.visible_count == 64  # derived from the largest file
            await pilot.press("end")
            await pilot.pause()
            assert app.view.top == app.view._max_top()
            assert app.view.top > 0

    asyncio.run(go())


def test_search_state_unchanged_across_home_end():
    async def go():
        a = HexFile("a.bin", b"....RIFF....RIFF...." + bytes(400))
        b = HexFile("b.bin", b"....RIFF....RIFF...." + bytes(400))
        app = _app([a, b])
        async with app.run_test(size=SIZE) as pilot:
            await pilot.pause()
            app._run_search("text", "RIFF")
            await pilot.pause()
            matches = list(app.search_matches)
            idx = app.search_index
            query = app.search_query
            assert matches and idx is not None
            await pilot.press("end")
            await pilot.pause()
            await pilot.press("home")
            await pilot.pause()
            # Home/End must not clear or recompute the search, nor move the match.
            assert app.search_matches == matches
            assert app.search_index == idx
            assert app.search_query is query

    asyncio.run(go())


def test_help_popup_opens_on_question_mark():
    async def go():
        app = _app(_pair())
        async with app.run_test(size=SIZE) as pilot:
            await pilot.pause()
            await pilot.press("question_mark")
            await pilot.pause()
            assert isinstance(app.screen, tui.HelpScreen)

    asyncio.run(go())
