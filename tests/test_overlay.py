# Copyright (c) 2026 Philip Cox
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for multihex.overlay.OverlayState (the frontend-agnostic seam).

These target the helper directly -- no CLI/TUI/GUI -- covering: no overlay,
valid load, warnings preserved, structural error blocks apply, range lookup,
overlapping-range order, zero-length behaviour, out-of-bounds robustness, and
per-file labelled diagnostics. Overlay docs are built inline (mirroring
test_layout_overlay_v1.py); binaries are tiny in-memory HexFiles.
"""

import hashlib
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from multihex.core import HexFile  # noqa: E402
from multihex.overlay import OverlayRange, OverlayState  # noqa: E402


def _schema():
    return {"name": "bintools.layout-overlay", "version": 1}


def _write(tmp_path, name, doc):
    p = tmp_path / name
    p.write_text(json.dumps(doc))
    return str(p)


def _file(name="a.bin", data=b""):
    return HexFile(name, data)


# -- no overlay / failed load ------------------------------------------------ #
def test_missing_file_is_not_loaded(tmp_path):
    st = OverlayState.load(str(tmp_path / "nope.json"))
    assert st.loaded is False
    assert st.applicable is False
    assert st.covers(0) is False
    assert st.ranges_at(0) == []
    assert "Could not load" in st.summary()


def test_invalid_json_is_not_loaded(tmp_path):
    p = tmp_path / "bad.json"
    p.write_text("{ not json")
    st = OverlayState.load(str(p))
    assert st.loaded is False
    assert st.applicable is False


# -- valid overlay ----------------------------------------------------------- #
def test_valid_overlay_loads_and_highlights(tmp_path):
    doc = {
        "schema": _schema(),
        "name": "demo",
        "ranges": [
            {"path": "magic", "offset": 0, "length": 2, "label": "magic"},
            {"path": "body", "offset": 4, "length": 4, "type": "u32le"},
        ],
    }
    data = bytes(range(16))
    st = OverlayState.load(_write(tmp_path, "ov.json", doc), [_file(data=data)])
    assert st.applicable is True
    assert st.name == "demo"
    assert st.range_count == 2
    assert st.error_count() == 0 and st.warning_count() == 0
    # In-range vs out-of-range.
    assert st.covers(0) and st.covers(1) and not st.covers(2)
    assert st.covers(4) and st.covers(7) and not st.covers(8)
    hits = st.ranges_at(0)
    assert [r.path for r in hits] == ["magic"]


def test_warnings_preserved_and_still_applicable(tmp_path):
    # unknown-type is a warning; the overlay stays loadable/applicable.
    doc = {
        "schema": _schema(),
        "ranges": [{"offset": 0, "length": 1, "type": "float128"}],
    }
    st = OverlayState.load(_write(tmp_path, "ov.json", doc), [_file(data=b"\x00\x01")])
    assert st.applicable is True
    assert st.warning_count() >= 1
    assert any("unknown-type" in line for line in st.diagnostic_lines())


# -- structural error blocks apply ------------------------------------------- #
def test_structural_error_blocks_apply(tmp_path):
    # duplicate-path is an error -> not applicable -> never highlights.
    doc = {
        "schema": _schema(),
        "ranges": [
            {"path": "dup", "offset": 0, "length": 1},
            {"path": "dup", "offset": 1, "length": 1},
        ],
    }
    st = OverlayState.load(_write(tmp_path, "ov.json", doc))
    assert st.loaded is True
    assert st.applicable is False
    assert st.error_count() >= 1
    assert st.covers(0) is False
    assert st.ranges_at(0) == []
    assert any("duplicate-path" in line for line in st.diagnostic_lines())


def test_wrong_schema_name_not_applicable(tmp_path):
    doc = {"schema": {"name": "something.else", "version": 1}, "ranges": []}
    st = OverlayState.load(_write(tmp_path, "ov.json", doc), [_file(data=b"x")])
    assert st.applicable is False
    # File-aware checks are skipped for a foreign schema, so no per-file noise.
    assert st.file_results == []


# -- range lookup ------------------------------------------------------------ #
def test_overlapping_ranges_returned_in_deterministic_order(tmp_path):
    doc = {
        "schema": _schema(),
        "ranges": [
            {"path": "outer", "offset": 0, "length": 8},
            {"path": "inner", "offset": 2, "length": 2},
            {"path": "point", "offset": 2, "length": 4},
        ],
    }
    st = OverlayState.load(_write(tmp_path, "ov.json", doc), [_file(data=bytes(8))])
    hits = st.ranges_at(2)
    # All three cover offset 2; order is (offset, length, path, index).
    assert [r.path for r in hits] == ["outer", "inner", "point"]
    # Calling again yields the same order (no in-place mutation surprises).
    assert [r.path for r in st.ranges_at(2)] == ["outer", "inner", "point"]


def test_zero_length_range_matches_nothing(tmp_path):
    doc = {
        "schema": _schema(),
        "ranges": [{"path": "marker", "offset": 3, "length": 0}],
    }
    st = OverlayState.load(_write(tmp_path, "ov.json", doc), [_file(data=bytes(8))])
    assert st.applicable is True
    assert st.range_count == 1
    assert st.covers(3) is False
    assert st.ranges_at(3) == []


def test_out_of_bounds_range_does_not_crash(tmp_path):
    # Range extends past the 4-byte file: a warning, still applicable, and
    # lookups around/inside the range never raise.
    doc = {
        "schema": _schema(),
        "ranges": [{"path": "tail", "offset": 2, "length": 100}],
    }
    st = OverlayState.load(_write(tmp_path, "ov.json", doc), [_file(data=bytes(4))])
    assert st.applicable is True
    assert any("range-out-of-bounds" in line for line in st.diagnostic_lines())
    assert st.covers(50) is True   # inside the (oversized) range, no crash
    assert st.covers(1) is False
    assert [r.path for r in st.ranges_at(50)] == ["tail"]


def test_empty_ranges_list_is_applicable_and_safe(tmp_path):
    # A structurally-valid overlay with no ranges loads and applies; lookups are
    # safe and the summary pluralizes "0 ranges".
    doc = {"schema": _schema(), "ranges": []}
    st = OverlayState.load(_write(tmp_path, "ov.json", doc), [_file(data=bytes(4))])
    assert st.applicable is True
    assert st.range_count == 0
    assert st.covers(0) is False
    assert st.ranges_at(0) == []
    assert "0 ranges" in st.summary()


def test_ranges_at_in_gap_returns_empty(tmp_path):
    # Offset between two non-adjacent ranges matches nothing.
    doc = {
        "schema": _schema(),
        "ranges": [
            {"path": "a", "offset": 0, "length": 2},
            {"path": "b", "offset": 4, "length": 2},
        ],
    }
    st = OverlayState.load(_write(tmp_path, "ov.json", doc), [_file(data=bytes(8))])
    assert st.ranges_at(2) == []  # in the gap
    assert st.ranges_at(3) == []
    assert [r.path for r in st.ranges_at(1)] == ["a"]
    assert [r.path for r in st.ranges_at(4)] == ["b"]


def test_adjacent_ranges_split_at_shared_boundary(tmp_path):
    # Half-open intervals: [0,2) and [2,4) touch at offset 2, which belongs only
    # to the second range -- no double-count at the seam.
    doc = {
        "schema": _schema(),
        "ranges": [
            {"path": "first", "offset": 0, "length": 2},
            {"path": "second", "offset": 2, "length": 2},
        ],
    }
    st = OverlayState.load(_write(tmp_path, "ov.json", doc), [_file(data=bytes(8))])
    assert [r.path for r in st.ranges_at(1)] == ["first"]
    assert [r.path for r in st.ranges_at(2)] == ["second"]
    assert [r.path for r in st.ranges_at(3)] == ["second"]


# -- per-file labelled diagnostics ------------------------------------------- #
def test_per_file_labelled_diagnostics(tmp_path):
    # source_size mismatches one file but not the other; each file-aware
    # diagnostic is labelled by that file's basename.
    doc = {
        "schema": _schema(),
        "source_size": 4,
        "ranges": [{"offset": 0, "length": 1}],
    }
    good = _file("good.bin", bytes(4))
    bad = _file("bad.bin", bytes(8))
    st = OverlayState.load(_write(tmp_path, "ov.json", doc), [good, bad])
    assert st.applicable is True  # size mismatch is a warning
    labels = [label for label, _ in st.file_results]
    assert labels == ["good.bin", "bad.bin"]
    lines = st.diagnostic_lines()
    assert any("[bad.bin]" in line and "source-size-mismatch" in line for line in lines)
    assert not any("[good.bin]" in line for line in lines)


# -- details / summary ------------------------------------------------------- #
def test_details_text_includes_cursor_section(tmp_path):
    doc = {
        "schema": _schema(),
        "name": "demo",
        "ranges": [{"path": "magic", "offset": 0, "length": 2}],
    }
    st = OverlayState.load(_write(tmp_path, "ov.json", doc), [_file(data=bytes(8))])
    text = st.details_text(cursor_offset=0)
    assert "Layout overlay" in text
    assert "status: applied" in text
    assert "Ranges under cursor (0x00000000):" in text
    assert "magic" in text


def test_details_text_for_error_overlay_no_cursor(tmp_path):
    # An overlay with a structural error renders the "not applied" status, lists
    # its diagnostics, and -- with no cursor -- omits the under-cursor section.
    doc = {
        "schema": _schema(),
        "ranges": [
            {"path": "dup", "offset": 0, "length": 1},
            {"path": "dup", "offset": 1, "length": 1},
        ],
    }
    st = OverlayState.load(_write(tmp_path, "ov.json", doc))
    text = st.details_text()
    assert "status: NOT applied (errors present)" in text
    assert "Diagnostics:" in text
    assert "duplicate-path" in text
    assert "Ranges under cursor" not in text


def test_summary_for_applicable_overlay_counts_warnings(tmp_path):
    # An applicable overlay with a warning reports both the range and warning
    # counts in its one-line summary.
    doc = {
        "schema": _schema(),
        "ranges": [{"path": "tail", "offset": 0, "length": 100}],
    }
    st = OverlayState.load(_write(tmp_path, "ov.json", doc), [_file(data=bytes(4))])
    summary = st.summary()
    assert st.applicable is True
    assert "1 range" in summary
    assert "1 warning" in summary


def test_summary_for_error_overlay_reports_not_applied(tmp_path):
    doc = {
        "schema": _schema(),
        "ranges": [
            {"path": "dup", "offset": 0, "length": 1},
            {"path": "dup", "offset": 1, "length": 1},
        ],
    }
    st = OverlayState.load(_write(tmp_path, "ov.json", doc))
    summary = st.summary()
    assert "not applied" in summary
    assert "1 error" in summary
    assert "(see details)" in summary


# -- _parse_ranges robustness ------------------------------------------------ #
def test_parse_ranges_skips_malformed_entries(tmp_path):
    # A non-dict entry and a range with a non-integer offset are skipped during
    # parsing (the validator flags them as errors, so the overlay is not
    # applicable), leaving only the one well-formed range in the model.
    doc = {
        "schema": _schema(),
        "ranges": [
            5,
            {"offset": "x", "length": 1},
            {"path": "good", "offset": 0, "length": 2},
        ],
    }
    st = OverlayState.load(_write(tmp_path, "ov.json", doc), [_file(data=bytes(8))])
    assert st.applicable is False          # malformed entries are errors
    assert st.range_count == 1             # only the well-formed range survives
    assert [r.path for r in st.ranges] == ["good"]


def test_non_list_ranges_parses_to_no_ranges(tmp_path):
    doc = {"schema": _schema(), "ranges": "oops"}
    st = OverlayState.load(_write(tmp_path, "ov.json", doc))
    assert st.applicable is False
    assert st.range_count == 0


# -- diagnostics aggregation ------------------------------------------------- #
def test_all_diagnostics_flattens_structural_then_per_file(tmp_path):
    # source_size mismatch is file-aware; all_diagnostics returns the flat
    # Diagnostic objects (structural first, then each file's), matching the
    # labelled diagnostic_lines.
    doc = {"schema": _schema(), "source_size": 4, "ranges": [{"offset": 0, "length": 1}]}
    st = OverlayState.load(_write(tmp_path, "ov.json", doc), [_file("bad.bin", bytes(8))])
    diags = st.all_diagnostics()
    assert [d.code for d in diags] == ["source-size-mismatch"]


# -- details / summary edge cases -------------------------------------------- #
def test_details_text_for_failed_load_shows_error(tmp_path):
    st = OverlayState.load(str(tmp_path / "nope.json"))
    text = st.details_text()
    assert "Layout overlay" in text
    assert "error:" in text


def test_details_text_includes_source_metadata(tmp_path):
    data = bytes(range(4))
    doc = {
        "schema": _schema(),
        "name": "demo",
        "source_file": "sample.bin",
        "source_size": len(data),
        "source_sha256": hashlib.sha256(data).hexdigest(),
        "ranges": [
            {"path": "field", "offset": 0, "length": 2, "type": "u16le",
             "decoded": 513},
        ],
    }
    st = OverlayState.load(_write(tmp_path, "ov.json", doc), [_file(data=data)])
    text = st.details_text()
    assert st.applicable is True
    assert "source_file: sample.bin" in text
    assert f"source_size: {len(data)}" in text
    assert "source_sha256:" in text
    # The range line carries the decoded value.
    assert "decoded=513" in text


def test_details_text_cursor_with_no_ranges_says_none(tmp_path):
    # An applicable overlay with no ranges: the "Ranges:" list is omitted and the
    # under-cursor section reports "(none)".
    doc = {"schema": _schema(), "ranges": []}
    st = OverlayState.load(_write(tmp_path, "ov.json", doc), [_file(data=bytes(8))])
    text = st.details_text(cursor_offset=0)
    assert "\nRanges:\n" not in text
    assert "Ranges under cursor (0x00000000):" in text
    assert "(none)" in text


def test_overlay_range_covers_semantics():
    r = OverlayRange(offset=4, length=2)
    assert r.end == 6
    assert not r.covers(3)
    assert r.covers(4) and r.covers(5)
    assert not r.covers(6)
    assert OverlayRange(offset=4, length=0).covers(4) is False
