# Copyright (c) 2026 Philip Cox
# SPDX-License-Identifier: Apache-2.0

"""Headless GUI side-by-side layout tests (offscreen Qt; skipped without PySide6).

These cover the GUI's side-by-side layout: cycling it through the shared shortcut
registry, that layout is display-only (it never touches the comparison model),
that the painter's column geometry matches ``core.render_row_text`` (so it reuses
the shared layout, not a reinvented one), that highlight priority is unchanged in
side-by-side, and that wide rows scroll horizontally instead of clipping.
"""

import os

import pytest

pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEvent, Qt  # noqa: E402
from PySide6.QtGui import QKeyEvent  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

import multihex.gui as gui  # noqa: E402
from multihex.core import (  # noqa: E402
    Marker,
    format_byte,
    format_marker,
    render_row_text,
)


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def _write(tmp_path, name, data):
    p = tmp_path / name
    p.write_bytes(data)
    return str(p)


def _loaded(tmp_path, *, a=None, b=None):
    """A shown MainWindow over two files (default: a differing pair)."""
    if a is None:
        a = bytes((i * 7) % 256 for i in range(256))
    if b is None:
        bb = bytearray(a)
        bb[5] ^= 0xFF  # one differing byte in row 0
        b = bytes(bb)
    pa = _write(tmp_path, "a.bin", a)
    pb = _write(tmp_path, "b.bin", b)
    w = gui.MainWindow()
    w.load_paths([pa, pb])
    w.resize(900, 400)
    w.show()
    return w


# --------------------------------------------------------------------------- #
# Cycling through the shared shortcut registry
# --------------------------------------------------------------------------- #


def test_cycle_layout_via_registry_action(app, tmp_path):
    w = _loaded(tmp_path)
    app.processEvents()
    vw = w.view_widget
    assert vw.layout_mode == "stacked"

    w.trigger_action("cycle_layout")
    assert vw.layout_mode == "side-by-side"
    assert w.act_layout.isChecked() is True  # menu stays in sync

    w.trigger_action("cycle_layout")
    assert vw.layout_mode == "stacked"
    assert w.act_layout.isChecked() is False
    w.close()


def test_v_key_event_cycles_layout(app, tmp_path):
    w = _loaded(tmp_path)
    app.processEvents()
    vw = w.view_widget
    app.sendEvent(
        w, QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_V,
                     Qt.KeyboardModifier.NoModifier, "v"),
    )
    assert vw.layout_mode == "side-by-side"
    w.close()


# --------------------------------------------------------------------------- #
# Layout is display-only: the model never changes
# --------------------------------------------------------------------------- #


def test_layout_is_display_only(app, tmp_path):
    w = _loaded(tmp_path)
    app.processEvents()
    vw = w.view_widget
    model = vw.view.model

    def snapshot():
        return [
            (
                r.offset,
                [list(c) for c in r.cells],
                [m.value for m in r.markers],
            )
            for r in (model.build_row(i) for i in range(model.row_count))
        ]

    stacked_rows = snapshot()
    stacked_count = vw.view.visible_count

    vw.set_layout("side-by-side")
    app.processEvents()

    # The model grid, byte cells, markers, and visible-row count are identical;
    # only the on-screen arrangement changed.
    assert snapshot() == stacked_rows
    assert vw.view.visible_count == stacked_count

    # Same under only-diff filtering.
    vw.set_only_diff(True)
    sbs_diff = vw.view.visible_count
    vw.set_layout("stacked")
    assert vw.view.visible_count == sbs_diff
    w.close()


def test_lines_per_block_matches_modes(app, tmp_path):
    w = _loaded(tmp_path)  # two files
    vw = w.view_widget
    # Stacked: 2 files + marker line, blocks adjacent (no gap). The
    # single-vs-none difference is exactly the marker line's height, so marker
    # space is reserved only when markers are on.
    vw.set_layout("stacked")
    vw.set_markers_mode("single")
    assert vw._lines_per_block() == 3
    vw.set_markers_mode("none")
    assert vw._lines_per_block() == 2
    # Side-by-side: 1 content line, blocks adjacent; "repeat" adds a marker
    # line, "single"/"none" draw/hide the strip inline (no extra line).
    vw.set_layout("side-by-side")
    vw.set_markers_mode("single")
    assert vw._lines_per_block() == 1
    vw.set_markers_mode("none")
    assert vw._lines_per_block() == 1
    vw.set_markers_mode("repeat")
    assert vw._lines_per_block() == 2
    w.close()


def test_block_px_matches_lines_per_block(app, tmp_path):
    # Row height is exactly the painted lines: no hidden blank-separator pixels.
    w = _loaded(tmp_path)
    vw = w.view_widget
    for layout in ("stacked", "side-by-side"):
        for mode in ("single", "repeat", "none"):
            vw.set_layout(layout)
            vw.set_markers_mode(mode)
            assert vw._block_px() == vw._lines_per_block() * vw._line_h
    w.close()


# --------------------------------------------------------------------------- #
# Painter geometry matches core.render_row_text (reuse, not reinvention)
# --------------------------------------------------------------------------- #


def _gui_side_by_side_columns(vw):
    """Recompute the painter's side-by-side columns the way _paint_block does."""
    model = vw.view.model
    width = model.width
    nw = vw.name_width
    strip_col = gui.OFFSET_LABEL_WIDTH + 2
    seg_w = vw._seg_width_chars()
    first_col = strip_col + (
        (3 * width - 1) + 2 if vw.markers_mode == "single" else 0
    )
    seg_cols = [first_col + i * (seg_w + 3) for i in range(len(model.files))]
    hex_cols = [c + nw + 2 for c in seg_cols]
    return strip_col, seg_cols, hex_cols


def test_side_by_side_geometry_matches_core(app, tmp_path):
    w = _loaded(tmp_path)
    app.processEvents()
    vw = w.view_widget
    vw.set_layout("side-by-side")
    vw.set_markers_mode("single")
    model = vw.view.model
    row = model.build_row(0)

    line = render_row_text(
        row, model.files, name_mode=vw.name_mode, ascii_on=vw.ascii_on,
        markers="single", layout="side-by-side", name_width=vw.name_width,
    )[0]

    strip_col, seg_cols, hex_cols = _gui_side_by_side_columns(vw)
    width = model.width

    # The marker strip sits where the GUI paints it.
    strip_text = " ".join(format_marker(m) for m in row.markers)
    assert line[strip_col:strip_col + len(strip_text)] == strip_text

    for fi, f in enumerate(model.files):
        name = f.display_name(vw.name_mode).ljust(vw.name_width)
        assert line[seg_cols[fi]:seg_cols[fi] + vw.name_width] == name
        hexpart = " ".join(format_byte(b) for b in row.cells[fi])
        assert line[hex_cols[fi]:hex_cols[fi] + (3 * width - 1)] == hexpart
    w.close()


# --------------------------------------------------------------------------- #
# Highlight priority is layout-independent
# --------------------------------------------------------------------------- #


def test_cell_styling_is_layout_independent(app, tmp_path):
    w = _loaded(tmp_path)
    app.processEvents()
    vw = w.view_widget

    cases = [
        (0, 0x05, Marker.DIFF, 0x41),     # diff cell
        (0, 0x00, Marker.SAME, 0x00),     # same/zero
        (1, 0x02, Marker.SAME, 0x20),     # whitespace byte class
        (0, 0x03, Marker.MISSING, None),  # missing
    ]

    def styles():
        return [
            (vw._cell_color(val, mk, off, fi), vw._cell_bg(fi, off, mk))
            for fi, off, mk, val in cases
        ]

    vw.set_layout("stacked")
    stacked = styles()
    vw.set_layout("side-by-side")
    assert styles() == stacked  # cell styling never reads the layout
    # And with byte classes on, the tier order still holds across layouts.
    vw.set_byte_classes(True)
    vw.set_layout("stacked")
    stacked_bc = styles()
    vw.set_layout("side-by-side")
    assert styles() == stacked_bc
    w.close()


# --------------------------------------------------------------------------- #
# Horizontal scrolling on wide rows (any overflow, both layouts)
# --------------------------------------------------------------------------- #


def test_side_by_side_row_scrolls_horizontally(app, tmp_path):
    w = _loaded(tmp_path)
    app.processEvents()
    vw = w.view_widget
    vw.set_layout("side-by-side")
    app.processEvents()

    # A side-by-side row of two width-16 files is wider than the viewport here.
    assert vw._content_width_px() > vw.viewport().width()
    hsb = vw.horizontalScrollBar()
    assert hsb.maximum() > 0
    assert vw.h_offset_px == 0

    vw.scroll_h(8)  # right: advance ~8 chars
    assert vw.h_offset_px > 0
    vw.scroll_h(10_000)  # clamp at the far right
    assert vw.h_offset_px == hsb.maximum()
    vw.scroll_h(-10_000)  # back to the start
    assert vw.h_offset_px == 0
    w.close()


def test_wide_stacked_width_scrolls_horizontally(app, tmp_path):
    # A wide --width in stacked layout used to clip on the right; it now scrolls.
    data = bytes((i * 11) % 256 for i in range(2048))
    w = _loaded(tmp_path, a=data, b=data)
    app.processEvents()
    vw = w.view_widget
    assert vw.layout_mode == "stacked"
    w.set_row_width(96)  # very wide rows
    app.processEvents()
    assert vw._content_width_px() > vw.viewport().width()
    assert vw.horizontalScrollBar().maximum() > 0
    vw.scroll_h(8)
    assert vw.h_offset_px > 0
    w.close()


def test_no_overflow_means_no_horizontal_scroll(app, tmp_path):
    # A narrow row that fits leaves the horizontal bar inert.
    w = _loaded(tmp_path)
    app.processEvents()
    vw = w.view_widget
    w.set_row_width(4)  # tiny rows fit easily in the 900px window
    app.processEvents()
    assert vw._content_width_px() <= vw.viewport().width()
    assert vw.horizontalScrollBar().maximum() == 0
    vw.scroll_h(8)
    assert vw.h_offset_px == 0  # clamped no-op
    w.close()


# --------------------------------------------------------------------------- #
# Painting smoke across marker modes in side-by-side
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("mode", ["single", "repeat", "none"])
def test_side_by_side_paints_without_error(app, tmp_path, mode):
    w = _loaded(tmp_path)
    vw = w.view_widget
    vw.set_layout("side-by-side")
    vw.set_markers_mode(mode)
    w.resize(900, 400)
    w.show()
    app.processEvents()
    img = vw.grab().toImage()
    assert not img.isNull()
    w.close()


# --------------------------------------------------------------------------- #
# Startup flags
# --------------------------------------------------------------------------- #


def test_layout_and_markers_startup_flags(app, tmp_path):
    a = _write(tmp_path, "a.bin", bytes(64))
    b = _write(tmp_path, "b.bin", bytes(64))
    args = gui.parse_args(["--layout", "side-by-side", "--markers", "repeat", a, b])
    assert args.layout == "side-by-side"
    assert args.markers == "repeat"
    w = gui.MainWindow(markers=args.markers, layout=args.layout)
    w.load_paths([a, b])
    assert w.view_widget.layout_mode == "side-by-side"
    assert w.view_widget.markers_mode == "repeat"
    w.close()
