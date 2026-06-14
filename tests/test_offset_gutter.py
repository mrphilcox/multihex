# Copyright (c) 2026 Philip Cox
# SPDX-License-Identifier: Apache-2.0

"""Offset-gutter sizing for large offsets.

The offset gutter is fixed at a minimum of 8 hex digits so small-file output
(and the goldens) stays byte-for-byte unchanged, but it must widen once an
offset needs 9+ hex digits (>= 0x100000000); otherwise the offset label on a
block's first line outgrows the continuation/marker rows' indent and the
gutter misaligns. These tests drive the core helpers and ``render_row_text``
directly; in-memory ``bytes`` backing means no temp files.
"""

import os
import subprocess
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from multihex.core import (  # noqa: E402
    OFFSET_LABEL_WIDTH,
    HexFile,
    HexModel,
    offset_gutter_width,
    offset_hex_digits,
    offset_label,
    render_row_text,
)


def _file(name, data):
    return HexFile(path=name, data=bytes(data))


# --------------------------------------------------------------------------- #
# Pure helpers
# --------------------------------------------------------------------------- #
def test_offset_hex_digits_minimum_is_eight():
    # The historical width never narrows: every offset that fits in 8 hex
    # digits keeps the 8-digit gutter, so existing output is unchanged.
    assert offset_hex_digits(0) == 8
    assert offset_hex_digits(0xFFFFFFFF) == 8


def test_offset_hex_digits_widens_past_boundary():
    # 0x100000000 is the first offset that needs a 9th hex digit.
    assert offset_hex_digits(0x100000000) == 9
    assert offset_hex_digits(0xFFFFFFFFF) == 9
    assert offset_hex_digits(0x10000000000) == 11


def test_offset_hex_digits_guards_nonpositive():
    # Negative or zero never underflows the minimum.
    assert offset_hex_digits(-1) == 8
    assert offset_hex_digits(0) == 8


def test_offset_label_width_and_value():
    # Default keeps the legacy 8-digit label.
    assert offset_label(0) == "0x00000000"
    assert offset_label(0xFF) == "0x000000ff"
    # An explicit digit count zero-pads to that width.
    assert offset_label(0x100000000, 9) == "0x100000000"
    assert offset_label(0xFF, 11) == "0x000000000ff"


def test_offset_gutter_width_matches_constant_at_minimum():
    assert offset_gutter_width(0) == OFFSET_LABEL_WIDTH == 10
    assert offset_gutter_width(0xFFFFFFFF) == 10
    assert offset_gutter_width(0x100000000) == 11


# --------------------------------------------------------------------------- #
# Model max_offset
# --------------------------------------------------------------------------- #
def test_max_offset_empty_model_is_start_offset():
    f = _file("a", b"")
    model = HexModel([f], start_offset=0x40, width=16, length=None)
    assert model.row_count == 0
    assert model.max_offset == 0x40


def test_max_offset_is_last_rendered_row():
    f = _file("a", bytes(40))
    model = HexModel([f], start_offset=0, width=16, length=None)
    # rows at 0x00, 0x10, 0x20 -> last row offset is 0x20.
    assert model.max_offset == 0x20


def test_max_offset_large_start_offset_with_length():
    # A small length window anchored at a huge start offset is the cheap way
    # to exercise wide offsets without allocating a multi-GB file.
    f = _file("a", bytes(8))
    model = HexModel([f], start_offset=0x100000000, width=16, length=0x40)
    assert model.max_offset == 0x100000000 + 3 * 16  # 4 rows of width 16


# --------------------------------------------------------------------------- #
# render_row_text gutter alignment
# --------------------------------------------------------------------------- #
def test_render_row_text_small_offset_unchanged():
    f = _file("a", bytes(range(16)))
    model = HexModel([f], start_offset=0, width=16, length=None)
    lines = render_row_text(model.build_row(0), [f])
    assert lines[0].startswith("0x00000000")
    # Continuation lines (marker strip) keep the legacy 10-char indent.
    assert all(line[:OFFSET_LABEL_WIDTH].strip() in ("", "0x00000000")
               or line.startswith("0x00000000") for line in lines)
    for line in lines[1:]:
        assert line[:OFFSET_LABEL_WIDTH] == " " * OFFSET_LABEL_WIDTH


def test_render_row_text_large_offset_gutter_aligns():
    # Regression: with a wide offset the label is 11 chars but the legacy
    # continuation pad was 10, so the marker strip drifted left by one. The
    # gutter width must size the label and every continuation line equally.
    f = _file("a", bytes(8))
    model = HexModel([f], start_offset=0x100000000, width=16, length=0x40)
    gutter = offset_gutter_width(model.max_offset)
    assert gutter == 11  # "0x" + 9 hex digits (max offset 0x100000030)

    lines = render_row_text(model.build_row(0), [f], gutter_width=gutter)
    assert lines[0][:gutter] == "0x100000000"
    assert lines[0].startswith(offset_label(0x100000000, gutter - 2))
    # Every continuation line shares the exact gutter width as blank indent,
    # so the block body lines up under the label rather than drifting left.
    for line in lines[1:]:
        assert line[:gutter] == " " * gutter

    # Demonstrate the regression: the legacy fixed width (OFFSET_LABEL_WIDTH)
    # is one short of this label, so the first line's body starts one column
    # right of the padded continuation lines -> misaligned.
    legacy = render_row_text(model.build_row(0), [f],
                             gutter_width=OFFSET_LABEL_WIDTH)
    assert len(offset_label(0x100000000)) > OFFSET_LABEL_WIDTH
    first_body_col = len(offset_label(0x100000000))  # where row 0 body begins
    cont_body_col = OFFSET_LABEL_WIDTH               # where padded rows begin
    assert first_body_col != cont_body_col
    # The fix renders both at the same column; the legacy width does not.
    assert legacy[0][:OFFSET_LABEL_WIDTH] != legacy[1][:OFFSET_LABEL_WIDTH]


def test_render_row_text_default_gutter_matches_legacy_width():
    # Omitting gutter_width keeps the historical OFFSET_LABEL_WIDTH so any
    # other caller is unaffected.
    f = _file("a", bytes(range(16)))
    model = HexModel([f], start_offset=0, width=16, length=None)
    default = render_row_text(model.build_row(0), [f])
    explicit = render_row_text(model.build_row(0), [f],
                               gutter_width=OFFSET_LABEL_WIDTH)
    assert default == explicit


# --------------------------------------------------------------------------- #
# CLI end-to-end (subprocess): continuation/marker rows align under a wide label
# --------------------------------------------------------------------------- #
def _marker_under_hex_offset(out):
    """Columns where the first hex cell (data line) and the marker strip begin.

    In stacked layout the marker strip is drawn directly under the first hex
    column. The offset between these two columns is exactly the alignment error:
    0 when the gutter is sized correctly, nonzero when the continuation indent
    disagrees with the label width.
    """
    lines = out.splitlines()
    data = next(line for line in lines
                if line.startswith("0x") and "a.bin" in line)
    marker = next(line for line in lines
                  if line.strip() and "a.bin" not in line
                  and not line.startswith("0x"))
    name_col = data.index("a.bin")
    hex_start = name_col + len("a.bin") + 2   # name + two-space gap
    marker_start = len(marker) - len(marker.lstrip(" "))
    return hex_start, marker_start


def _run_cli(path, *args):
    return subprocess.run(
        [sys.executable, "-m", "multihex.cli", *args, str(path)],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )


def test_cli_large_offset_gutter_aligns(tmp_path):
    # A real CLI dump anchored at a 9-hex-digit offset. Bytes past EOF render as
    # missing (--), which is irrelevant to alignment. The label is 11 chars
    # ("0x100000000"); the marker strip must still sit directly under the first
    # hex column. With the legacy fixed 10-char gutter it drifts one left.
    p = tmp_path / "a.bin"
    p.write_bytes(bytes(range(16)))
    # --markers single forces the strip on for this single-file alignment check
    # (a lone file hides it by default, which is unrelated to gutter geometry).
    proc = _run_cli(p, "--offset", "0x100000000", "--length", "0x20",
                    "--markers", "single")
    assert proc.returncode == 0, proc.stderr
    out = proc.stdout
    assert "0x100000000" in out

    data = next(line for line in out.splitlines() if line.startswith("0x"))
    assert data[:13] == "0x100000000  "   # 11-char label + two-space body gap
    hex_start, marker_start = _marker_under_hex_offset(out)
    assert hex_start == marker_start, (hex_start, marker_start)


def test_cli_small_offset_output_unchanged(tmp_path):
    # The minimum 8-digit gutter is preserved for ordinary files, and the marker
    # strip lines up under the first hex column as it always has.
    p = tmp_path / "a.bin"
    p.write_bytes(bytes(range(16)))
    # --markers single: this single-file dump hides the strip by default, but the
    # test measures where the (present) strip aligns under the first hex column.
    proc = _run_cli(p, "--markers", "single")
    assert proc.returncode == 0, proc.stderr
    out = proc.stdout
    data = next(line for line in out.splitlines() if line.startswith("0x"))
    assert data[:OFFSET_LABEL_WIDTH] == "0x00000000"
    hex_start, marker_start = _marker_under_hex_offset(out)
    assert hex_start == marker_start, (hex_start, marker_start)


# --------------------------------------------------------------------------- #
# TUI (headless): the view sizes its gutter once from the model's max offset
# --------------------------------------------------------------------------- #
def test_tui_view_gutter_sized_from_model():
    tui = pytest.importorskip("multihex.tui")
    if tui._TEXTUAL_IMPORT_ERROR is not None:
        pytest.skip("textual not installed")

    small = HexModel([_file("a", bytes(range(16)))], width=16, length=None)
    view = tui.HexView(small, ascii_on=True, only_diff=False, color_on=True,
                       name_mode="basename")
    assert view._offset_digits == 8
    assert view._gutter_width == OFFSET_LABEL_WIDTH

    big = HexModel([_file("a", bytes(8))], start_offset=0x100000000,
                   width=16, length=0x40)
    view_big = tui.HexView(big, ascii_on=True, only_diff=False, color_on=True,
                           name_mode="basename")
    assert view_big._offset_digits == 9
    assert view_big._gutter_width == 11
