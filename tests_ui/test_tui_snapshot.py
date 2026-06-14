"""Textual TUI visual-regression snapshots (opt-in).

These complement -- they do not duplicate -- the fast headless TUI tests in
``tests/`` (which assert *state*). Here we assert that the *rendered* output
stays stable via ``pytest-textual-snapshot`` (SVG baselines under
``__snapshots__/``), plus one thin launch-smoke that runs even when the
snapshot plugin is absent.

Skips cleanly when ``textual`` is missing (whole module) or when
``pytest-textual-snapshot`` is missing (only the snapshot tests).
"""

import asyncio
import importlib.util
from pathlib import Path

import pytest

import multihex.tui as tui

pytestmark = pytest.mark.skipif(
    tui._TEXTUAL_IMPORT_ERROR is not None, reason="textual not installed"
)

import fixtures_ui as fx  # noqa: E402

from multihex.core import HexModel  # noqa: E402
from multihex.overlay import OverlayState  # noqa: E402

_OVERLAY_JSON = str(Path(__file__).parent / "data" / "overlay_sample.json")

_HAS_SNAPSHOT = importlib.util.find_spec("pytest_textual_snapshot") is not None
requires_snapshot = pytest.mark.skipif(
    not _HAS_SNAPSHOT, reason="pytest-textual-snapshot not installed"
)

# A roomy, fixed terminal so the snapshot is deterministic across environments.
TERM = (100, 30)


def _diff_app() -> "tui.MultiHexApp":
    a, b = fx.diff_pair()
    return tui.MultiHexApp(
        fx.model(a, b, width=16),
        ascii_on=True,
        only_diff=False,
        color_on=True,
        name_mode="basename",
    )


def _overlay_app() -> "tui.MultiHexApp":
    data = fx.overlay_target()
    files = [fx.hexfile("sample0.bin", data), fx.hexfile("sample1.bin", data)]
    model = HexModel(files, width=16)
    overlay = OverlayState.load(_OVERLAY_JSON, files)
    return tui.MultiHexApp(
        model,
        ascii_on=True,
        only_diff=False,
        color_on=True,
        name_mode="basename",
        overlay=overlay,
    )


def _tall_app() -> "tui.MultiHexApp":
    """A view taller than the terminal so End actually scrolls to the last page."""
    base = bytes((i * 7 + 3) & 0xFF for i in range(512))  # 32 rows at width 16
    other = bytearray(base)
    other[400] ^= 0xFF  # a late differing byte, visible on the bottom-anchored page
    return tui.MultiHexApp(
        fx.model(bytes(base), bytes(other), width=16),
        ascii_on=True,
        only_diff=False,
        color_on=True,
        name_mode="basename",
    )


def _side_by_side_app() -> "tui.MultiHexApp":
    files = [
        fx.hexfile("left.bin", bytes(range(16))),
        fx.hexfile("middle.bin", bytes(range(16, 32))),
        fx.hexfile("right.bin", bytes(range(32, 48))),
    ]
    return tui.MultiHexApp(
        HexModel(files, width=16),
        ascii_on=True,
        only_diff=False,
        color_on=True,
        name_mode="basename",
        layout="side-by-side",
        markers="repeat",
    )


# --------------------------------------------------------------------------- #
# Thin launch smoke (no snapshot plugin required)
# --------------------------------------------------------------------------- #


def test_launches_and_composes():
    """The app starts, composes its widgets, and survives a redraw + scroll."""

    async def go():
        app = _diff_app()
        async with app.run_test() as pilot:
            await pilot.pause()
            # core widgets are present
            assert app.query_one("#status") is not None
            assert app.view is not None
            # a key label is visible in the footer
            await pilot.press("down")  # move cursor / repaint
            await pilot.pause()

    asyncio.run(go())


def test_overlay_loads_and_is_applicable():
    """The sample overlay loads, stays applicable, and warns (no error)."""
    app = _overlay_app()
    assert app.overlay is not None
    assert app.overlay.applicable is True
    sevs = {d.severity for d in app.overlay.all_diagnostics()}
    assert "error" not in sevs
    assert "warning" in sevs  # the out-of-bounds trailer range


# --------------------------------------------------------------------------- #
# Snapshots (require pytest-textual-snapshot)
# --------------------------------------------------------------------------- #


@requires_snapshot
def test_snapshot_diff_view(snap_compare):
    assert snap_compare(_diff_app(), terminal_size=TERM)


@requires_snapshot
def test_snapshot_overlay_view(snap_compare):
    assert snap_compare(_overlay_app(), terminal_size=TERM)


@requires_snapshot
def test_snapshot_side_by_side_repeat_markers(snap_compare):
    assert snap_compare(_side_by_side_app(), terminal_size=TERM)


@requires_snapshot
def test_snapshot_text_search_panel(snap_compare):
    assert snap_compare(_diff_app(), press=["slash"], terminal_size=TERM)


@requires_snapshot
def test_snapshot_settings_panel(snap_compare):
    assert snap_compare(_diff_app(), press=["o"], terminal_size=TERM)


@requires_snapshot
def test_snapshot_overlay_details_panel(snap_compare):
    assert snap_compare(_overlay_app(), press=["L"], terminal_size=TERM)


@requires_snapshot
def test_snapshot_end_scrolled(snap_compare):
    # Locks the bottom-anchored End view (the final row is the last visible row).
    assert snap_compare(_tall_app(), press=["end"], terminal_size=TERM)


@requires_snapshot
def test_snapshot_help_popup(snap_compare):
    # The help popup is generated from the shared registry; this snapshot makes
    # registry drift visible. Regenerate with scripts/ui-tests/update_snapshots.sh.
    assert snap_compare(_diff_app(), press=["question_mark"], terminal_size=TERM)
