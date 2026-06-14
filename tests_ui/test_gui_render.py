"""PySide6 GUI visual-render smoke tests (opt-in, headless/offscreen).

These complement -- they do not duplicate -- the fast headless GUI tests in
``tests/`` (which assert *state*). Here we drive the real ``MainWindow``,
render it to an image with ``QWidget.grab()``, and make conservative checks
(non-null, correct non-zero size, actually painted something). No committed
baseline PNG and no pixel-perfect comparison -- the rendered artifact is
written under ``_artifacts/`` for human inspection only.

Skips cleanly when PySide6 is missing.
"""

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
    # A covered, SAME, present byte gets the overlay colour; diff still wins.
    assert vw._cell_color(0x00, Marker.SAME, 0) == gui._COLOR_OVERLAY
    assert vw._cell_color(0x00, Marker.DIFF, 0) == gui._COLOR_DIFF

    image = _grab_image(w, "gui_overlay.png")
    assert _is_painted(image)
    w.close()


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
