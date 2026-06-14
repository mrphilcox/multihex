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

from PySide6.QtCore import QPoint, QPointF, Qt  # noqa: E402
from PySide6.QtGui import QWheelEvent  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

import multihex.gui as gui  # noqa: E402


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


def test_empty_window_has_no_model(app):
    w = gui.MainWindow()  # no files
    assert w.model is None
    assert w.view_widget.view is None
    assert "No files loaded" in w.statusBar().currentMessage()
    w.close()
