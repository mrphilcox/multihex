# Copyright (c) 2026 Philip Cox
# SPDX-License-Identifier: Apache-2.0

"""The shared shortcut registry is the single source of truth for both frontends.

These tests pin the registry's shape and prove the TUI ``BINDINGS`` and the GUI
help cannot drift from it. Pure-registry assertions need no GUI toolkit; the
BINDINGS cross-check skips cleanly when ``textual`` is absent.
"""

import pytest

import multihex.tui as tui  # noqa: E402  (import-guards textual itself)
from multihex import shortcuts
from multihex.shortcuts import (
    SHORTCUTS,
    gui_help_text,
    gui_key_names,
    gui_shortcuts,
    gui_text_map,
    tui_help_text,
    tui_shortcuts,
)


def test_action_ids_are_unique():
    ids = [s.action_id for s in SHORTCUTS]
    assert len(ids) == len(set(ids))


def test_tui_help_format_and_lists_home_end():
    text = tui_help_text()
    lines = text.splitlines()
    assert lines[0] == "multihex-tui - keys"
    assert lines[-1] == "  (any key to close)"
    # Home/End are present (the whole point of the TUI fix).
    assert "  Home          jump to start of range" in lines
    assert "  End           jump to end (last page)" in lines
    # Every TUI row uses the historical 13-wide key column.
    for s in tui_shortcuts():
        assert f"  {s.display_keys:<13} {s.help_text}" in lines


def test_gui_help_includes_layout_and_scroll():
    text = gui_help_text()
    assert text.startswith("multihex-gui - keys")
    # The GUI now has the side-by-side layout and horizontal scroll the TUI had,
    # so both entries appear in its help (no longer TUI-only).
    assert "cycle layout" in text              # v (cycle_layout)
    assert "scroll horizontally" in text       # left/right (scroll_horizontal)
    # The marker-strip override is gone now that the GUI matches the TUI's
    # single/repeat/none cycle.
    assert "cycle markers (single / repeat / none)" in text
    assert "toggle marker strip" not in text


def test_no_frontend_exclusive_entries_remain():
    # Every action now applies to both frontends; none carries an exclusion note.
    for s in SHORTCUTS:
        assert s.tui is True and s.gui is True
        assert not s.note, f"{s.action_id} should not be frontend-exclusive"


def test_gui_key_maps_are_collision_free_and_cover_every_gui_action():
    # The builders raise on a duplicate, so calling them proves no collisions.
    tmap = gui_text_map()
    kmap = gui_key_names()
    assert tmap["q"] == "quit"
    assert tmap["?"] == "help"
    assert kmap["Home"] == "home"
    assert kmap["End"] == "end"
    represented = set(tmap.values()) | set(kmap.values())
    assert represented == {s.action_id for s in gui_shortcuts()}


def test_registry_module_is_stdlib_only():
    # It must not pull in core / textual / PySide6 (keeps it importable in every
    # context). Inspect its globals for leaked toolkit names.
    names = vars(shortcuts)
    for forbidden in ("HexModel", "QApplication", "QColor", "App", "core"):
        assert forbidden not in names


@pytest.mark.skipif(
    tui._TEXTUAL_IMPORT_ERROR is not None, reason="textual not installed"
)
def test_tui_bindings_key_set_equals_registry():
    binding_keys = {b.key for b in tui.MultiHexApp.BINDINGS}
    registry_keys = set()
    for s in tui_shortcuts():
        registry_keys.update(s.tui_keys)
    assert binding_keys == registry_keys


@pytest.mark.skipif(
    tui._TEXTUAL_IMPORT_ERROR is not None, reason="textual not installed"
)
def test_every_tui_binding_has_an_action_method():
    for b in tui.MultiHexApp.BINDINGS:
        assert hasattr(tui.MultiHexApp, f"action_{b.action}"), b.action
