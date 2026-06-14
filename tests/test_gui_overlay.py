"""Headless GUI layout-overlay tests (offscreen Qt; skipped without PySide6).

Exercises the overlay menu glue at the state level: load applies an applicable
overlay and surfaces diagnostics, clear removes it, an error overlay is loaded
but not applied, reloading files drops a stale overlay, and the cell-color tier
returns the overlay color for a covered non-diff byte. No pixel assertions, and
all feedback dialogs are non-blocking so nothing hangs unattended.
"""

import json
import os

import pytest

pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

import multihex.gui as gui  # noqa: E402
from multihex.core import Marker  # noqa: E402

SCHEMA = {"name": "bintools.layout-overlay", "version": 1}


@pytest.fixture(scope="module")
def app():
    instance = QApplication.instance() or QApplication([])
    yield instance


def _write(tmp_path, name, data):
    p = tmp_path / name
    p.write_bytes(data)
    return str(p)


def _write_json(tmp_path, name, doc):
    p = tmp_path / name
    p.write_text(json.dumps(doc))
    return str(p)


def _loaded_window(tmp_path):
    data = bytes(range(16))
    a = _write(tmp_path, "a.bin", data)
    b = _write(tmp_path, "b.bin", data)
    w = gui.MainWindow()
    w.load_paths([a, b])
    return w


def test_load_applies_overlay_and_colors_cell(app, tmp_path):
    path = _write_json(tmp_path, "ov.json", {
        "schema": SCHEMA, "name": "demo",
        "ranges": [{"path": "magic", "offset": 0, "length": 2}],
    })
    w = _loaded_window(tmp_path)
    st = w.load_overlay(path)
    assert st.applicable is True
    assert w.overlay is st
    assert w.view_widget.overlay is st
    vw = w.view_widget
    # Covered, SAME, present byte -> overlay color; uncovered -> normal text.
    assert vw._cell_color(0x00, Marker.SAME, 0) == gui._COLOR_OVERLAY
    assert vw._cell_color(0x05, Marker.SAME, 5) == vw._text_color()
    # Diff still wins over overlay.
    assert vw._cell_color(0x00, Marker.DIFF, 0) == gui._COLOR_DIFF
    assert "Loaded layout overlay 'demo'" in w.statusBar().currentMessage()
    w.close()


def test_clear_removes_overlay(app, tmp_path):
    path = _write_json(tmp_path, "ov.json", {
        "schema": SCHEMA, "ranges": [{"offset": 0, "length": 2}],
    })
    w = _loaded_window(tmp_path)
    w.load_overlay(path)
    assert w.overlay is not None
    w._overlay_clear()
    assert w.overlay is None
    assert w.view_widget.overlay is None
    assert w.view_widget._cell_color(0x00, Marker.SAME, 0) == w.view_widget._text_color()
    w.close()


def test_warning_overlay_applies_and_shows_details(app, tmp_path):
    # An unknown-type warning keeps the overlay applicable but surfaces a
    # non-blocking details dialog carrying the warning.
    path = _write_json(tmp_path, "warn.json", {
        "schema": SCHEMA, "name": "warn",
        "ranges": [{"path": "x", "offset": 0, "length": 1, "type": "float128"}],
    })
    w = _loaded_window(tmp_path)
    st = w.load_overlay(path)
    assert st.applicable is True
    assert st.warning_count() >= 1
    # Still highlights the covered byte.
    assert w.view_widget._cell_color(0x00, Marker.SAME, 0) == gui._COLOR_OVERLAY
    # A details dialog was queued with the warning detail.
    assert w._message_boxes
    assert "unknown-type" in w._message_boxes[-1].text()
    w.close()


def test_error_overlay_loaded_not_applied(app, tmp_path):
    path = _write_json(tmp_path, "err.json", {
        "schema": SCHEMA,
        "ranges": [
            {"path": "dup", "offset": 0, "length": 1},
            {"path": "dup", "offset": 1, "length": 1},
        ],
    })
    w = _loaded_window(tmp_path)
    st = w.load_overlay(path)
    assert st.applicable is False
    # Loaded (so View can show why) but never highlights.
    assert w.overlay is st
    assert w.view_widget._cell_color(0x00, Marker.SAME, 0) == w.view_widget._text_color()
    # A non-blocking warning dialog was created with the diagnostic detail.
    assert w._message_boxes
    assert "duplicate-path" in w._message_boxes[-1].text()
    w.close()


def test_reloading_files_drops_stale_overlay(app, tmp_path):
    path = _write_json(tmp_path, "ov.json", {
        "schema": SCHEMA, "ranges": [{"offset": 0, "length": 2}],
    })
    w = _loaded_window(tmp_path)
    w.load_overlay(path)
    assert w.overlay is not None
    # Opening different files invalidates the overlay's validation.
    c = _write(tmp_path, "c.bin", bytes(32))
    w.load_paths([c, c])
    assert w.overlay is None
    assert w.view_widget.overlay is None
    w.close()


def test_view_overlay_without_overlay_is_safe(app, tmp_path):
    w = _loaded_window(tmp_path)
    w._overlay_view()  # should not raise; shows an info dialog
    assert w.overlay is None
    assert w._message_boxes
    w.close()


def test_view_overlay_shows_details(app, tmp_path):
    path = _write_json(tmp_path, "ov.json", {
        "schema": SCHEMA, "name": "demo",
        "ranges": [{"path": "magic", "offset": 0, "length": 2}],
    })
    w = _loaded_window(tmp_path)
    w.load_overlay(path)
    w._overlay_view()
    assert "Layout overlay" in w._message_boxes[-1].text()
    assert "magic" in w._message_boxes[-1].text()
    w.close()
