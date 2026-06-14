# Copyright (c) 2026 Philip Cox
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for the core offset model and plain-text row rendering.

These drive multihex.core directly (HexFile accepts in-memory ``bytes``), so
they exercise construction validation, grid/offset arithmetic, and the shared
renderer without going through a frontend. They cover the error and boundary
branches that the batch CLI reaches only as a subprocess.
"""

import os
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from multihex.core import (  # noqa: E402
    HexFile,
    HexModel,
    Marker,
    format_ascii_char,
    format_byte,
    render_row_text,
)


def _file(name, data):
    return HexFile(path=name, data=bytes(data))


# --------------------------------------------------------------------------- #
# HexModel construction validation
# --------------------------------------------------------------------------- #
def test_no_files_rejected():
    with pytest.raises(ValueError):
        HexModel([], width=16)


@pytest.mark.parametrize("width", [0, -1])
def test_non_positive_width_rejected(width):
    with pytest.raises(ValueError):
        HexModel([_file("a", b"x")], width=width)


def test_negative_offset_rejected():
    with pytest.raises(ValueError):
        HexModel([_file("a", b"x")], start_offset=-1)


def test_negative_length_rejected():
    with pytest.raises(ValueError):
        HexModel([_file("a", b"x")], length=-1)


@pytest.mark.parametrize("ref", [-1, 2])
def test_ref_out_of_range_rejected(ref):
    with pytest.raises(ValueError):
        HexModel([_file("a", b"x"), _file("b", b"y")], ref=ref)


def test_ref_zero_is_valid_pivot():
    # ref=0 is in range and pins the pivot to the first file, distinct from the
    # no-ref case only when there is more than one file.
    files = [_file("a", b"\x01"), _file("b", b"\x02")]
    model = HexModel(files, width=1, ref=0)
    assert model.build_row(0).markers == [Marker.DIFF]


# --------------------------------------------------------------------------- #
# Offset/index arithmetic at the edges
# --------------------------------------------------------------------------- #
def test_index_for_offset_empty_window_is_zero():
    # A zero-length window has no rows; any offset clamps to row 0.
    model = HexModel([_file("a", b"abcd")], width=2, length=0)
    assert model.row_count == 0
    assert model.index_for_offset(99) == 0


def test_index_for_offset_clamps_below_and_above():
    model = HexModel([_file("a", bytes(40))], start_offset=8, width=8)
    assert model.index_for_offset(0) == 0            # before the window start
    assert model.index_for_offset(8) == 0            # exactly at the start
    assert model.index_for_offset(10_000) == model.row_count - 1   # clamps high


def test_locate_before_grid_start_is_none():
    model = HexModel([_file("a", bytes(40))], start_offset=16, width=8)
    assert model.locate(0) is None                   # before start_offset
    assert model.locate(16) == (0, 0)
    assert model.locate(20) == (0, 4)


def test_final_row_narrower_than_width():
    # A bounded window whose length is not a multiple of width yields a short
    # last row; bytes past the window end are not rendered.
    model = HexModel([_file("a", bytes(range(10)))], width=4, length=10)
    assert model.row_count == 3
    assert len(model.build_row(2).cells[0]) == 2     # 10 - 2*4


def test_row_entirely_past_window_end_is_zero_width():
    model = HexModel([_file("a", bytes(range(10)))], width=4, length=8)
    # Index past the bounded window produces a zero-width row, not a crash.
    assert model.build_row(5).cells[0] == []


def test_missing_wins_over_diff_in_markers():
    # A column with any missing byte is MISSING regardless of the others.
    files = [_file("a", b"\x01\x02"), _file("b", b"\x01")]
    model = HexModel(files, width=2)
    assert model.build_row(0).markers == [Marker.SAME, Marker.MISSING]


# --------------------------------------------------------------------------- #
# Cell formatting helpers
# --------------------------------------------------------------------------- #
def test_format_byte_missing_and_value():
    assert format_byte(None) == "--"
    assert format_byte(0x0A) == "0a"
    assert format_byte(0xFF) == "ff"


@pytest.mark.parametrize(
    "byte, expected",
    [
        (None, " "),       # missing renders as a blank in the gutter
        (0x00, "."),       # NUL is non-printable
        (0x1F, "."),       # control byte below space
        (0x20, " "),       # space is printable-as-itself
        (0x41, "A"),
        (0x7E, "~"),
        (0x7F, "."),       # DEL is non-printable
        (0xFF, "."),
    ],
)
def test_format_ascii_char(byte, expected):
    assert format_ascii_char(byte) == expected


# --------------------------------------------------------------------------- #
# render_row_text layout/marker branches
# --------------------------------------------------------------------------- #
def _two_file_row(width=2):
    files = [_file("a", b"\x01\x02"), _file("b", b"\x01\xff")]
    model = HexModel(files, width=width)
    return model.build_row(0), files


def test_render_defaults_name_width_when_omitted():
    # name_width=None makes the renderer derive the column width itself. The
    # offset now rides the first content line as a left gutter (no standalone
    # offset line), and both file names must still appear.
    row, files = _two_file_row()
    lines = render_row_text(row, files, ascii_on=False)
    assert lines[0].startswith("0x00000000")
    # The offset shares the first file's line, so it is not alone on a line.
    assert lines[0].strip() != "0x00000000"
    # No line is just the bare offset label.
    assert all(ln.strip() != "0x00000000" for ln in lines)
    # Block lines after the first are indented under the offset gutter.
    assert all(ln.startswith(" " * len("0x00000000")) for ln in lines[1:])
    assert any("a" in ln for ln in lines) and any("b" in ln for ln in lines)


def test_render_side_by_side_attaches_offset_to_data_line():
    # Side-by-side: the offset and both file segments share one visual line.
    row, files = _two_file_row()
    lines = render_row_text(row, files, layout="side-by-side", markers="single",
                            ascii_on=False)
    assert lines[0].startswith("0x00000000")
    assert "a  01 02" in lines[0] and "b  01 ff" in lines[0]


def test_render_side_by_side_markers_none_has_no_marker_line():
    row, files = _two_file_row()
    lines = render_row_text(row, files, layout="side-by-side", markers="none",
                            ascii_on=False)
    # The offset rides the single combined segment line; no marker strip and no
    # standalone offset line.
    assert len(lines) == 1
    joined = "\n".join(lines)
    assert "=" not in joined and "X" not in joined


def test_render_side_by_side_markers_repeat_adds_marker_row():
    row, files = _two_file_row()
    single = render_row_text(row, files, layout="side-by-side", markers="single",
                             ascii_on=False)
    repeat = render_row_text(row, files, layout="side-by-side", markers="repeat",
                             ascii_on=False)
    # repeat appends a second marker-bearing line that single does not have.
    assert len(repeat) == len(single) + 1


def test_render_stacked_markers_none_drops_marker_strip():
    row, files = _two_file_row()
    with_strip = render_row_text(row, files, layout="stacked", markers="single",
                                 ascii_on=False)
    without = render_row_text(row, files, layout="stacked", markers="none",
                              ascii_on=False)
    assert len(without) == len(with_strip) - 1


def test_render_stacked_attaches_offset_to_first_file():
    # Stacked: the offset prefixes the first file's line; later file lines and
    # the marker strip indent under the offset gutter (no offset-only line).
    row, files = _two_file_row()
    lines = render_row_text(row, files, layout="stacked", markers="single",
                            ascii_on=False)
    gutter = " " * len("0x00000000")
    assert lines[0].startswith("0x00000000")
    assert "a  01 02" in lines[0]            # first file shares the offset line
    assert lines[1].startswith(gutter)       # second file indented under it
    assert "b  01 ff" in lines[1]
    assert all(ln.strip() != "0x00000000" for ln in lines)


def test_render_uneven_lengths_show_missing_with_offset_attached():
    # A row past the shorter file's end renders "--" for the missing bytes while
    # still attaching the offset to the first file line.
    files = [_file("a", b"\x01\x02\x03\x04"), _file("b", b"\x01\x02")]
    model = HexModel(files, width=2)
    row = model.build_row(1)                 # offset 0x02: b has no bytes here
    lines = render_row_text(row, files, layout="stacked", markers="single",
                            ascii_on=False)
    assert lines[0].startswith("0x00000002")
    assert "--" in lines[1]                  # b's missing bytes
    assert all(ln.strip() != "0x00000002" for ln in lines)
