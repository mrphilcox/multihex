# Copyright (c) 2026 Philip Cox
# SPDX-License-Identifier: Apache-2.0

"""Headless GUI widget glue tests (offscreen Qt; skipped without PySide6).

These exercise the thin Qt layer -- loading files, the menu-action signal glue,
navigation, and reference selection -- at the *state* level (no pixel/UI
assertions). The heavy navigation/filter logic is covered by
``test_gui_viewstate.py``; this just confirms the widget is wired to it.
"""

import os

import pytest

pytest.importorskip("PySide6")
# Render headless so the test needs no display.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEvent, QPoint, QPointF, Qt  # noqa: E402
from PySide6.QtGui import QKeyEvent, QWheelEvent  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

import multihex.gui as gui  # noqa: E402
from multihex.shortcuts import (  # noqa: E402
    gui_help_text,
    gui_key_names,
    gui_shortcuts,
    gui_text_map,
)


def _wheel(angle_y):
    """A vertical QWheelEvent with the given angle delta (120 units == 1 notch)."""
    return QWheelEvent(
        QPointF(10, 10),            # local position
        QPointF(10, 10),            # global position
        QPoint(0, 0),               # pixelDelta
        QPoint(0, angle_y),         # angleDelta
        Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier,
        Qt.ScrollPhase.NoScrollPhase,
        False,                      # inverted
    )


@pytest.fixture(scope="module")
def app():
    instance = QApplication.instance() or QApplication([])
    yield instance


def _write(tmp_path, name, data):
    p = tmp_path / name
    p.write_bytes(data)
    return str(p)


def test_load_and_navigate(app, tmp_path):
    data = bytes((i * 7) % 256 for i in range(1024))  # 64 rows at width 16
    a = _write(tmp_path, "a.bin", data)
    b = _write(tmp_path, "b.bin", data)

    w = gui.MainWindow()
    assert w.load_paths([a, b]) is True
    w.resize(900, 400)
    w.show()
    app.processEvents()

    vw = w.view_widget
    assert vw.view is not None
    assert vw.view.visible_count == 64

    vw.to_end()
    assert vw.view.top == vw.view.max_top(vw._page_rows())
    assert vw.view.top > 0

    vw.to_home()
    assert vw.view.top == 0

    vw.jump_to_offset(0x200)  # row 32
    assert vw.view.offset_at(vw.view.top) == 0x200

    assert "ref=all-agree" in w.statusBar().currentMessage()
    w.close()


def test_menu_toggles_and_reference(app, tmp_path):
    a = _write(tmp_path, "a.bin", bytes([0] * 48))
    bb = bytearray([0] * 48)
    bb[20] = 0xFF  # only row 1 differs
    b = _write(tmp_path, "b.bin", bytes(bb))

    w = gui.MainWindow()
    w.load_paths([a, b])
    w.resize(900, 400)
    w.show()
    app.processEvents()
    vw = w.view_widget

    # only-diff via the menu action exercises the toggled-signal glue.
    w.act_diff.setChecked(True)
    assert vw.view.only_diff is True
    assert vw.view.visible_count == 1

    w.act_markers.setChecked(False)
    assert vw.markers_on is False

    w.act_ascii.setChecked(False)
    assert vw.ascii_on is False

    # reference selection through the Compare menu (exercises the full glue:
    # the action group triggers _on_ref_changed -> set_ref + status refresh).
    target = next(a for a in w.ref_group.actions() if a.data() == 1)
    target.trigger()
    assert w.model.ref == 1
    assert "ref=b.bin" in w.statusBar().currentMessage()
    w.close()


def test_wheel_scrolls_whole_rows_and_clamps(app, tmp_path):
    data = bytes((i * 7) % 256 for i in range(1024))  # 64 rows at width 16
    a = _write(tmp_path, "a.bin", data)
    b = _write(tmp_path, "b.bin", data)
    w = gui.MainWindow()
    w.load_paths([a, b])
    w.resize(900, 400)
    w.show()
    app.processEvents()
    vw = w.view_widget
    assert vw.view.top == 0
    # max_top is large for 64 rows in this viewport, so 3 rows is unclamped.
    assert vw.view.max_top(vw._page_rows()) >= 3

    vw.wheelEvent(_wheel(-120))   # one notch down -> 3 rows forward
    assert vw.view.top == 3
    vw.wheelEvent(_wheel(-120))
    assert vw.view.top == 6
    vw.wheelEvent(_wheel(120))    # one notch up -> 3 rows back
    assert vw.view.top == 3
    vw.wheelEvent(_wheel(120))
    vw.wheelEvent(_wheel(120))    # past the top -> clamps at 0
    assert vw.view.top == 0
    w.close()


def test_ref_menu_rebuild_does_not_accumulate_actions(app, tmp_path):
    a = _write(tmp_path, "a.bin", bytes(48))
    b = _write(tmp_path, "b.bin", bytes(48))
    c = _write(tmp_path, "c.bin", bytes(48))
    w = gui.MainWindow()
    w.load_paths([a, b, c])
    # one "all agree" + one per file
    assert len(w.ref_group.actions()) == 4
    # reloading a smaller set must rebuild, not append.
    w.load_paths([a, b])
    assert len(w.ref_group.actions()) == 3
    # a name-mode change also rebuilds the menu; still no duplicates.
    w._on_names_changed(next(x for x in w.names_group.actions() if x.data() == "path"))
    assert len(w.ref_group.actions()) == 3
    w.close()


def test_out_of_range_start_ref_warns_and_drops(app, tmp_path, capsys):
    # A typo'd --ref (here 9, with only 2 files) must not be swallowed: the GUI
    # coerces it to "no reference" so it keeps running, but warns on stderr --
    # mirroring the CLI's hard error / TUI's exit-2 rather than diverging silently.
    a = _write(tmp_path, "a.bin", bytes(48))
    b = _write(tmp_path, "b.bin", bytes(48))
    w = gui.MainWindow(ref=9)
    assert w.load_paths([a, b]) is True
    assert w.model.ref is None  # dropped, not applied
    err = capsys.readouterr().err
    assert "--ref 9 out of range" in err
    assert "have 2 files" in err
    w.close()


def test_empty_window_has_no_model(app):
    w = gui.MainWindow()  # no files
    assert w.model is None
    assert w.view_widget.view is None
    assert "No files loaded" in w.statusBar().currentMessage()
    w.close()


# --------------------------------------------------------------------------- #
# Shared shortcut registry -> GUI dispatch parity
# --------------------------------------------------------------------------- #


def test_action_slots_cover_every_gui_action(app):
    """Every GUI-applicable registry action has a dispatch slot, and no extras."""
    w = gui.MainWindow()
    assert set(w._action_slots) == {s.action_id for s in gui_shortcuts()}
    w.close()


def test_trigger_action_navigation(app, tmp_path):
    data = bytes((i * 7) % 256 for i in range(1024))  # 64 rows at width 16
    a = _write(tmp_path, "a.bin", data)
    b = _write(tmp_path, "b.bin", data)
    w = gui.MainWindow()
    w.load_paths([a, b])
    w.resize(900, 400)
    w.show()
    app.processEvents()
    vw = w.view_widget

    w.trigger_action("end")
    assert vw.view.top == vw.view.max_top(vw._page_rows())
    assert vw.view.top > 0
    w.trigger_action("home")
    assert vw.view.top == 0
    w.trigger_action("next_row")
    assert vw.view.top == 1
    w.trigger_action("next_page")
    assert vw.view.top == 1 + vw._page_rows()
    w.close()


def test_trigger_action_toggles_flip_state_and_menu(app, tmp_path):
    a = _write(tmp_path, "a.bin", bytes(48))
    b = _write(tmp_path, "b.bin", bytes(48))
    w = gui.MainWindow()
    w.load_paths([a, b])
    vw = w.view_widget

    assert vw.color_on is True
    w.trigger_action("toggle_color")
    assert vw.color_on is False
    assert w.act_color.isChecked() is False

    assert vw.byte_classes_on is False
    w.trigger_action("toggle_byte_classes")
    assert vw.byte_classes_on is True
    assert w.act_byte_classes.isChecked() is True

    w.trigger_action("toggle_ascii")
    assert vw.ascii_on is False
    assert w.act_ascii.isChecked() is False

    # cycle_markers is the GUI's strip on/off (no side-by-side "repeat" mode).
    assert vw.markers_on is True
    w.trigger_action("cycle_markers")
    assert vw.markers_on is False
    assert w.act_markers.isChecked() is False
    w.close()


def test_real_key_event_dispatches_and_bubbles(app, tmp_path):
    """A QKeyEvent to the window dispatches; one to the focused child bubbles up."""
    data = bytes((i * 7) % 256 for i in range(1024))
    a = _write(tmp_path, "a.bin", data)
    b = _write(tmp_path, "b.bin", data)
    w = gui.MainWindow()
    w.load_paths([a, b])
    w.resize(900, 400)
    w.show()
    app.processEvents()
    vw = w.view_widget

    # Named key delivered straight to the window.
    app.sendEvent(
        w, QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_End, Qt.KeyboardModifier.NoModifier)
    )
    assert vw.view.top == vw.view.max_top(vw._page_rows())

    # A key delivered to the focused child must bubble (HexCompareView.ignore()).
    app.sendEvent(
        vw, QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Home, Qt.KeyboardModifier.NoModifier)
    )
    assert vw.view.top == 0

    # A printable key resolves via QKeyEvent.text().
    app.sendEvent(
        vw, QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_J, Qt.KeyboardModifier.NoModifier, "j")
    )
    assert vw.view.top == 1
    w.close()


def test_every_keymap_entry_dispatches_its_action(app, tmp_path):
    """Each registry key, delivered as a real QKeyEvent, hits the right action_id.

    A spy replaces ``trigger_action`` so dialog-opening slots never actually run
    (no modal exec under the offscreen platform); we only assert the key ->
    action_id resolution, which is the part keyPressEvent owns. Covers the whole
    keymap, not just the few keys checked above.
    """
    a = _write(tmp_path, "a.bin", bytes(64))
    b = _write(tmp_path, "b.bin", bytes(64))
    w = gui.MainWindow()
    w.load_paths([a, b])
    w.show()
    app.processEvents()

    recorded = []
    w.trigger_action = lambda aid: (recorded.append(aid) or True)

    # Printable keys resolve via QKeyEvent.text(); use Key_unknown so the
    # key-code lookup misses and dispatch falls through to the character map.
    text_map = gui_text_map()
    assert text_map
    for ch, aid in text_map.items():
        recorded.clear()
        app.sendEvent(
            w,
            QKeyEvent(
                QEvent.Type.KeyPress, Qt.Key.Key_unknown,
                Qt.KeyboardModifier.NoModifier, ch,
            ),
        )
        assert recorded == [aid], f"text key {ch!r} should dispatch {aid}"

    # Named keys (Down/PageUp/Home/End/...) resolve via the key-code map.
    name_map = gui_key_names()
    assert name_map
    for name, aid in name_map.items():
        recorded.clear()
        keycode = getattr(Qt.Key, f"Key_{name}")
        app.sendEvent(
            w,
            QKeyEvent(
                QEvent.Type.KeyPress, keycode, Qt.KeyboardModifier.NoModifier, "",
            ),
        )
        assert recorded == [aid], f"named key {name} should dispatch {aid}"

    w.close()


# --------------------------------------------------------------------------- #
# GUI dialog error paths and markers status
# --------------------------------------------------------------------------- #


def test_jump_dialog_invalid_offset_warns_and_keeps_position(app, tmp_path, monkeypatch):
    data = bytes((i * 7) % 256 for i in range(1024))
    a = _write(tmp_path, "a.bin", data)
    b = _write(tmp_path, "b.bin", data)
    w = gui.MainWindow()
    w.load_paths([a, b])
    w.show()
    app.processEvents()
    top0 = w.view_widget.view.top

    monkeypatch.setattr(
        gui.QInputDialog, "getText",
        staticmethod(lambda *a, **k: ("not-a-number", True)),
    )
    warnings = []
    monkeypatch.setattr(
        gui.QMessageBox, "warning",
        staticmethod(lambda *a, **k: warnings.append(a)),
    )

    w.trigger_action("jump")            # goes through the real slot + handler
    assert len(warnings) == 1
    assert w.view_widget.view.top == top0
    w.close()


def test_jump_dialog_valid_offset_navigates(app, tmp_path, monkeypatch):
    data = bytes((i * 7) % 256 for i in range(1024))
    a = _write(tmp_path, "a.bin", data)
    b = _write(tmp_path, "b.bin", data)
    w = gui.MainWindow()
    w.load_paths([a, b])
    w.show()
    app.processEvents()

    monkeypatch.setattr(
        gui.QInputDialog, "getText",
        staticmethod(lambda *a, **k: ("0x200", True)),
    )
    w.trigger_action("jump")
    assert w.view_widget.view.offset_at(w.view_widget.view.top) == 0x200
    w.close()


def test_jump_and_ref_dialogs_are_noop_without_model(app, monkeypatch):
    # An empty window has no model/files; the dialog slots must guard and return
    # without ever prompting or crashing.
    w = gui.MainWindow()
    assert w.model is None

    def _boom(*a, **k):  # would raise if a dialog were actually shown
        raise AssertionError("dialog should not be shown without a model")

    monkeypatch.setattr(gui.QInputDialog, "getText", staticmethod(_boom))
    monkeypatch.setattr(gui.QInputDialog, "getItem", staticmethod(_boom))

    w.trigger_action("jump")
    w.trigger_action("choose_ref")
    w.close()


def test_markers_toggle_reflected_in_status(app, tmp_path):
    a = _write(tmp_path, "a.bin", bytes(48))
    b = _write(tmp_path, "b.bin", bytes(48))
    w = gui.MainWindow()
    w.load_paths([a, b])
    w.show()
    app.processEvents()

    assert "markers:on" in w.statusBar().currentMessage()
    w.trigger_action("cycle_markers")
    assert w.view_widget.markers_on is False
    assert "markers:off" in w.statusBar().currentMessage()
    w.close()


# --------------------------------------------------------------------------- #
# GUI search (reuses the core engine; renders/navigates only)
# --------------------------------------------------------------------------- #


def test_search_runs_navigates_and_highlights(app, tmp_path):
    data = bytes(64)  # all zeros -> many "00 00" matches
    a = _write(tmp_path, "a.bin", data)
    b = _write(tmp_path, "b.bin", data)
    w = gui.MainWindow()
    w.load_paths([a, b])
    w.resize(900, 400)
    w.show()
    app.processEvents()

    w.run_search("hex", "00 00")
    assert w.search_matches
    assert w.search_index == 0
    assert w.search_error is None
    # highlight state is installed on the view
    assert w.view_widget._search_covered
    assert w.view_widget.search_current is w.search_matches[0]

    first = w.search_index
    w.search_next()
    assert w.search_index == 1
    w.search_prev()
    assert w.search_index == first
    # prev from the first wraps to the last
    w.search_prev()
    assert w.search_index == len(w.search_matches) - 1
    w.close()


def test_search_bad_hex_sets_error_without_crashing(app, tmp_path):
    a = _write(tmp_path, "a.bin", bytes(16))
    w = gui.MainWindow()
    w.load_paths([a])
    w.run_search("hex", "zz")  # invalid hex
    assert w.search_error is not None
    assert w.search_matches == []
    assert w.search_index is None
    assert w.view_widget._search_covered == set()
    w.close()


def test_search_hex_matches_bytes_not_ascii(app, tmp_path):
    # The bytes 0x52 0x49 0x46 0x46 ("RIFF") appear; the ASCII text "5249..." must not.
    data = b"....RIFF...." + bytes(40)
    a = _write(tmp_path, "a.bin", data)
    w = gui.MainWindow()
    w.load_paths([a])
    w.run_search("hex", "52 49 46 46")
    assert [m.offset for m in w.search_matches] == [4]
    w.close()


def test_text_search_preserves_significant_whitespace(app, tmp_path):
    data = b"xx RIFF yy   zzRIFF"
    a = _write(tmp_path, "a.bin", data)
    w = gui.MainWindow()
    w.load_paths([a])

    w.run_search("text", " RIFF ")
    assert [m.offset for m in w.search_matches] == [2]
    assert w.search_query.pattern == " RIFF "
    assert w.search_query.needle == b" RIFF "

    w.run_search("text", "   ")
    assert [m.offset for m in w.search_matches] == [10]
    assert w.search_query.pattern == "   "
    assert w.search_query.needle == b"   "

    matches = w.search_matches
    query = w.search_query
    index = w.search_index
    w.run_search("hex", "   ")
    assert w.search_matches is matches
    assert w.search_query is query
    assert w.search_index == index
    w.close()


def test_search_cleared_on_file_reload(app, tmp_path):
    data = bytes(64)
    a = _write(tmp_path, "a.bin", data)
    b = _write(tmp_path, "b.bin", data)
    w = gui.MainWindow()
    w.load_paths([a, b])
    w.run_search("hex", "00 00")
    assert w.search_matches
    w.load_paths([a, b])  # reload drops the stale results
    assert w.search_matches == []
    assert w.search_index is None
    assert w.view_widget._search_covered == set()
    w.close()


# --------------------------------------------------------------------------- #
# Help / options
# --------------------------------------------------------------------------- #


def test_help_dialog_text_is_generated_from_registry(app):
    w = gui.MainWindow()
    box = w._show_help_dialog()
    assert box.text() == gui_help_text()
    w.close()


def test_settings_dialog_applies_immediately(app, tmp_path):
    a = _write(tmp_path, "a.bin", bytes(48))
    b = _write(tmp_path, "b.bin", bytes(48))
    w = gui.MainWindow()
    w.load_paths([a, b])
    dlg = gui._SettingsDialog(w)

    color_box = dlg._checks["Color highlighting"]
    assert color_box.isChecked() is True
    color_box.setChecked(False)  # drives act_color -> view, immediately
    assert w.view_widget.color_on is False
    assert w.act_color.isChecked() is False

    classes_box = dlg._checks["Byte-class highlighting"]
    classes_box.setChecked(True)
    assert w.view_widget.byte_classes_on is True
    dlg.reject()
    w.close()
