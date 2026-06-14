# Copyright (c) 2026 Philip Cox
# SPDX-License-Identifier: Apache-2.0

"""PySide6 GUI visual-render smoke tests (opt-in, headless/offscreen).

These complement -- they do not duplicate -- the fast headless GUI tests in
``tests/`` (which assert *state*). Here we drive the real ``MainWindow``,
render it to an image with ``QWidget.grab()``, and make conservative checks
(non-null, correct non-zero size, actually painted something). No committed
baseline PNG and no pixel-perfect comparison -- the rendered artifact is
written under ``_artifacts/`` for human inspection only.

Skips cleanly when PySide6 is missing.
"""

import gc
import json
import os
from pathlib import Path

import pytest

pytest.importorskip("PySide6")
# Render headless; conftest also sets this, but be defensive if run standalone.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import fixtures_ui as fx  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

import multihex.gui as gui  # noqa: E402
from multihex.core import Marker  # noqa: E402
from multihex.shortcuts import gui_help_text  # noqa: E402

_OVERLAY_JSON = str(Path(__file__).parent / "data" / "overlay_sample.json")
_ARTIFACTS = Path(__file__).parent / "_artifacts"


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def _grab_image(widget, name):
    """Grab ``widget`` to an image, save a PNG artifact, and return the image."""
    _ARTIFACTS.mkdir(exist_ok=True)
    pixmap = widget.grab()
    assert not pixmap.isNull(), "grab() produced a null pixmap"
    image = pixmap.toImage()
    assert image.width() > 0 and image.height() > 0
    image.save(str(_ARTIFACTS / name), "PNG")
    return image


def _is_painted(image):
    """True if the image has more than one distinct pixel value (sampled)."""
    seen = set()
    xs = max(1, image.width() // 40)
    ys = max(1, image.height() // 40)
    for y in range(0, image.height(), ys):
        for x in range(0, image.width(), xs):
            seen.add(image.pixel(x, y))
            if len(seen) > 1:
                return True
    return False


def test_construct_and_load_single(app, tmp_path):
    """An empty window constructs, then loads a single file into a model."""
    w = gui.MainWindow()
    assert w.model is None  # empty until files load
    path = fx.write(tmp_path, "only.bin", fx.blob_mixed())
    assert w.load_paths([path]) is True
    w.resize(800, 360)
    w.show()
    app.processEvents()
    assert w.model is not None
    assert w.view_widget.view is not None
    w.close()


def test_empty_window_render_png(app):
    """The no-file startup window renders a painted empty-state view."""
    w = gui.MainWindow()
    w.resize(800, 360)
    w.show()
    app.processEvents()

    image = _grab_image(w, "gui_empty.png")
    assert _is_painted(image), "empty window render is a single uniform colour"
    w.close()


def test_diff_render_png(app, tmp_path):
    """Two differing files render to a non-empty, actually-painted image."""
    a_data, b_data = fx.diff_pair()
    a = fx.write(tmp_path, "a.bin", a_data)
    b = fx.write(tmp_path, "b.bin", b_data)
    w = gui.MainWindow()
    w.load_paths([a, b])
    w.resize(900, 420)
    w.show()
    app.processEvents()

    image = _grab_image(w, "gui_diff.png")
    assert _is_painted(image), "rendered image is a single uniform colour"
    w.close()


def test_toggled_view_render_png(app, tmp_path):
    """Hiding ASCII and markers still produces a painted comparison view."""
    a_data, b_data = fx.diff_pair()
    a = fx.write(tmp_path, "a.bin", a_data)
    b = fx.write(tmp_path, "b.bin", b_data)
    w = gui.MainWindow()
    w.load_paths([a, b])
    w.resize(900, 420)
    w.show()
    app.processEvents()

    w.act_ascii.setChecked(False)
    none_marker = next(a for a in w.markers_group.actions() if a.data() == "none")
    none_marker.trigger()
    app.processEvents()

    image = _grab_image(w, "gui_toggled.png")
    assert _is_painted(image)
    w.close()


def test_side_by_side_render_png(app, tmp_path):
    """Side-by-side layout paints the per-file segments across one row."""
    a_data, b_data = fx.diff_pair()
    a = fx.write(tmp_path, "a.bin", a_data)
    b = fx.write(tmp_path, "b.bin", b_data)
    w = gui.MainWindow()
    w.load_paths([a, b])
    w.view_widget.set_layout("side-by-side")
    w.resize(1100, 420)
    w.show()
    app.processEvents()

    image = _grab_image(w, "gui_sidebyside.png")
    assert _is_painted(image)

    # "repeat" adds the per-segment marker line; it still paints cleanly.
    w.view_widget.set_markers_mode("repeat")
    app.processEvents()
    repeat_image = _grab_image(w, "gui_sidebyside_repeat.png")
    assert _is_painted(repeat_image)
    w.close()


def test_overlay_highlight_smoke(app, tmp_path):
    """The sample overlay applies, colours covered cells, and reports status."""
    data = fx.overlay_target()
    a = fx.write(tmp_path, "a.bin", data)
    b = fx.write(tmp_path, "b.bin", data)
    w = gui.MainWindow()
    w.load_paths([a, b])
    w.resize(900, 420)
    w.show()
    app.processEvents()

    st = w.load_overlay(_OVERLAY_JSON)
    assert st.applicable is True
    assert w.view_widget.overlay is st

    vw = w.view_widget
    # A covered, SAME, present byte gets the overlay background fill; a diff
    # cell keeps its red glyphs with no fill (diff still wins).
    assert vw._cell_bg(0, 0x00, Marker.SAME) == vw._accents().overlay_bg
    assert vw._cell_color(0x00, Marker.DIFF, 0) == vw._accents().diff
    assert vw._cell_bg(0, 0x00, Marker.DIFF) is None

    image = _grab_image(w, "gui_overlay.png")
    assert _is_painted(image)
    w.close()


def test_overlay_diff_render_after_navigation(app, tmp_path):
    """A long overlay/diff view remains painted after end/home navigation."""
    base = bytes((i * 7) % 256 for i in range(1024))
    other = bytearray(base)
    other[700] ^= 0xFF
    a = fx.write(tmp_path, "a.bin", base)
    b = fx.write(tmp_path, "b.bin", bytes(other))
    overlay_path = tmp_path / "ov.json"
    overlay_path.write_text(
        json.dumps({
            "schema": {"name": "bintools.layout-overlay", "version": 1},
            "name": "long-render",
            "ranges": [{"path": "head", "offset": 0, "length": 128}],
        }),
        encoding="utf-8",
    )

    w = gui.MainWindow()
    w.load_paths([a, b])
    st = w.load_overlay(str(overlay_path))
    assert st.applicable is True
    w.resize(900, 420)
    w.show()
    app.processEvents()

    w.view_widget.to_end()
    app.processEvents()
    end_image = _grab_image(w, "gui_overlay_scrolled_end.png")
    assert _is_painted(end_image)

    w.view_widget.to_home()
    app.processEvents()
    home_image = _grab_image(w, "gui_overlay_scrolled_home.png")
    assert _is_painted(home_image)
    w.close()


def test_help_dialog_smoke(app, tmp_path):
    """The help dialog opens (non-modal, headless-safe) with registry-generated text."""
    a = fx.write(tmp_path, "a.bin", fx.blob_no_magic())
    w = gui.MainWindow()
    w.load_paths([a])
    w.show()
    app.processEvents()

    assert w.trigger_action("help") is True
    app.processEvents()
    assert w._message_boxes, "help dialog was not retained"
    assert w._message_boxes[-1].text() == gui_help_text()
    # Reap deterministically so the order-sensitive clean-shutdown test (which
    # measures the global top-level pool) is not polluted by a lingering dialog.
    w.close()
    del w
    gc.collect()
    app.processEvents()


def test_search_highlight_render_png(app, tmp_path):
    """A run search paints a match-highlight tier without errors."""
    data = b"....RIFF....RIFF...." + bytes(40)
    a = fx.write(tmp_path, "a.bin", data)
    b = fx.write(tmp_path, "b.bin", data)
    w = gui.MainWindow()
    w.load_paths([a, b])
    w.resize(900, 420)
    w.show()
    app.processEvents()

    w.run_search("hex", "52 49 46 46")  # "RIFF" bytes
    assert w.search_matches
    app.processEvents()
    image = _grab_image(w, "gui_search.png")
    assert _is_painted(image)
    w.close()
    del w
    gc.collect()
    app.processEvents()


def test_dark_palette_render_png(app, tmp_path):
    """A dark palette flips to the dark accent set and still paints cleanly."""
    from PySide6.QtGui import QColor, QPalette

    a_data, b_data = fx.diff_pair()
    a = fx.write(tmp_path, "a.bin", a_data)
    b = fx.write(tmp_path, "b.bin", b_data)
    w = gui.MainWindow()
    w.load_paths([a, b])

    dark = QPalette()
    dark.setColor(QPalette.ColorRole.Base, QColor(0x1E, 0x1E, 0x1E))
    dark.setColor(QPalette.ColorRole.Window, QColor(0x2A, 0x2A, 0x2A))
    dark.setColor(QPalette.ColorRole.Text, QColor(0xE6, 0xE6, 0xE6))
    dark.setColor(QPalette.ColorRole.WindowText, QColor(0xE6, 0xE6, 0xE6))
    w.setPalette(dark)
    w.view_widget.setPalette(dark)

    vw = w.view_widget
    assert vw._accents() is gui._ACCENTS_DARK
    assert vw._cell_color(0x00, Marker.DIFF, 0) == gui._ACCENTS_DARK.diff

    w.resize(900, 420)
    w.show()
    app.processEvents()
    image = _grab_image(w, "gui_dark.png")
    assert _is_painted(image)
    w.close()
    del w
    gc.collect()
    app.processEvents()


def test_overlay_report_dialog_render_png(app, tmp_path):
    """'View current overlay' opens the scrollable monospace report dialog."""
    data = fx.overlay_target()
    a = fx.write(tmp_path, "a.bin", data)
    w = gui.MainWindow()
    w.load_paths([a])
    w.load_overlay(_OVERLAY_JSON)
    w.show()
    app.processEvents()

    w._overlay_view()
    dlg = w._message_boxes[-1]
    assert isinstance(dlg, gui._TextReportDialog)
    assert "Ranges under cursor" in dlg.text()
    app.processEvents()
    image = _grab_image(dlg, "gui_overlay_dialog.png")
    assert _is_painted(image)
    dlg.close()
    w.close()
    del w
    gc.collect()
    app.processEvents()


def test_clean_shutdown(app, tmp_path):
    """A window closes, hides, and is fully reaped (no leaked top-levels)."""
    import gc

    baseline = len(QApplication.topLevelWidgets())
    a = fx.write(tmp_path, "a.bin", fx.blob_no_magic())
    b = fx.write(tmp_path, "b.bin", fx.blob_short_id())
    w = gui.MainWindow()
    w.load_paths([a, b])
    w.show()
    app.processEvents()
    assert w.isVisible()

    w.close()
    assert not w.isVisible()

    # Dropping the last reference reaps the parentless window (and its child
    # menus, which also count as top-level widgets), returning to baseline.
    del w
    gc.collect()
    app.processEvents()
    assert len(QApplication.topLevelWidgets()) == baseline
