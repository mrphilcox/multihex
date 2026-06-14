# Copyright (c) 2026 Philip Cox
# SPDX-License-Identifier: Apache-2.0

"""Pure-Python GUI helper tests: ViewState navigation/filtering + format_status.

These import only ``multihex.gui``'s Qt-free helpers and ``multihex.core``; they
do not touch PySide6, so they run regardless of whether PySide6 is installed.
"""

from multihex.core import HexFile, HexModel, SearchMatch, SearchQuery
from multihex.gui import (
    ViewState,
    clamp_ref,
    format_overlay_status,
    format_search_status,
    format_status,
    format_status_parts,
)


def _model(*datas, width=16, ref=None, only_diff=False):
    files = [HexFile(f"f{i}", d) for i, d in enumerate(datas)]
    return HexModel(files, width=width, ref=ref)


# --------------------------------------------------------------------------- #
# visible_indices / only-diff
# --------------------------------------------------------------------------- #
def test_default_shows_all_rows_as_range():
    vs = ViewState(_model(bytes(range(48)), bytes(range(48))))
    vis = vs.visible_indices()
    assert isinstance(vis, range)
    assert list(vis) == [0, 1, 2]
    assert vs.visible_count == 3


def test_only_diff_identical_files_is_empty():
    data = bytes(range(48))
    vs = ViewState(_model(data, data), only_diff=True)
    assert list(vs.visible_indices()) == []
    assert vs.visible_count == 0


def test_only_diff_selects_just_the_differing_rows():
    a = bytearray(64)
    b = bytearray(64)
    b[20] = 0xFF  # row 1
    b[60] = 0x01  # row 3
    vs = ViewState(_model(bytes(a), bytes(b)), only_diff=True)
    assert list(vs.visible_indices()) == [1, 3]
    assert vs.visible_count == 2


def test_only_diff_includes_missing_rows():
    # a ends after 16 bytes; b is longer, so rows past a's end are MISSING -> diff.
    vs = ViewState(_model(bytes(16), bytes(48)), only_diff=True)
    assert list(vs.visible_indices()) == [1, 2]


# --------------------------------------------------------------------------- #
# position <-> row-index mapping
# --------------------------------------------------------------------------- #
def test_row_index_and_offset_at_clamp():
    a = bytearray(48)
    b = bytearray(48)
    b[4] = 1   # row 0
    b[40] = 1  # row 2
    vs = ViewState(_model(bytes(a), bytes(b)), only_diff=True)
    assert list(vs.visible_indices()) == [0, 2]
    assert vs.row_index_at(0) == 0
    assert vs.row_index_at(1) == 2
    assert vs.offset_at(1) == 0x20      # row 2 starts at offset 32
    assert vs.row_index_at(99) == 2     # clamp high
    assert vs.row_index_at(-5) == 0     # clamp low


def test_position_for_row_snaps_forward_in_only_diff():
    a = bytearray(64)
    b = bytearray(64)
    b[20] = 1  # row 1
    b[60] = 1  # row 3
    vs = ViewState(_model(bytes(a), bytes(b)), only_diff=True)
    assert list(vs.visible_indices()) == [1, 3]
    assert vs.position_for_row(0) == 0   # before first visible -> first
    assert vs.position_for_row(1) == 0
    assert vs.position_for_row(2) == 1   # between visible rows -> snap forward
    assert vs.position_for_row(3) == 1
    assert vs.position_for_row(99) == 1  # past end -> last


def test_position_for_row_range_mode_clamps():
    vs = ViewState(_model(bytes(48), bytes(48)))  # identical -> range(3)
    assert vs.position_for_row(2) == 2
    assert vs.position_for_row(99) == 2
    assert vs.position_for_row(-1) == 0


def test_position_for_offset_round_trip():
    vs = ViewState(_model(bytes(160), bytes(160)))  # 10 rows
    assert vs.index_for_offset(0x20) == 2
    assert vs.position_for_offset(0x20) == 2
    assert vs.position_for_offset(0x25) == 2  # within the same row block


def test_offset_to_row_with_start_offset():
    # Window starting at 0x10, width 16: row 0 covers 0x10..0x1f, row 1 0x20...
    files = [HexFile("a", bytes(160)), HexFile("b", bytes(160))]
    model = HexModel(files, start_offset=0x10, width=16)
    vs = ViewState(model)
    assert vs.index_for_offset(0x05) == 0   # before the window start -> first row
    assert vs.index_for_offset(0x10) == 0
    assert vs.index_for_offset(0x1F) == 0
    assert vs.index_for_offset(0x20) == 1
    assert vs.index_for_offset(0x25) == 1
    assert vs.offset_at(0) == 0x10
    assert vs.position_for_offset(0x20) == 1


def test_position_for_offset_snaps_forward_in_only_diff():
    a = bytearray(64)
    b = bytearray(64)
    b[20] = 1  # row 1 (0x10..0x1f)
    b[60] = 1  # row 3 (0x30..0x3f)
    vs = ViewState(_model(bytes(a), bytes(b)), only_diff=True)
    assert list(vs.visible_indices()) == [1, 3]
    assert vs.position_for_offset(0x00) == 0   # row 0 not visible -> first diff row
    assert vs.position_for_offset(0x10) == 0   # row 1 is the first diff row
    assert vs.position_for_offset(0x20) == 1   # row 2 not visible -> snap to row 3
    assert vs.position_for_offset(0x30) == 1   # row 3


# --------------------------------------------------------------------------- #
# clamp_ref (reference-selection validation; Qt-free)
# --------------------------------------------------------------------------- #
def test_clamp_ref_valid_index_kept():
    assert clamp_ref(0, 3) == 0
    assert clamp_ref(2, 3) == 2


def test_clamp_ref_out_of_range_becomes_none():
    assert clamp_ref(3, 3) is None    # == nfiles is out of range
    assert clamp_ref(9, 3) is None
    assert clamp_ref(-1, 3) is None


def test_clamp_ref_none_stays_none():
    assert clamp_ref(None, 3) is None


def test_clamp_ref_single_file_edge():
    assert clamp_ref(0, 1) == 0
    assert clamp_ref(1, 1) is None


# --------------------------------------------------------------------------- #
# top / clamping
# --------------------------------------------------------------------------- #
def test_max_top_and_clamp_top():
    vs = ViewState(_model(bytes(160), bytes(160)))  # 10 rows
    assert vs.visible_count == 10
    assert vs.max_top(4) == 6
    assert vs.max_top(20) == 0  # page bigger than content
    vs.top = 99
    vs.clamp_top(4)
    assert vs.top == 6
    vs.top = -3
    vs.clamp_top(4)
    assert vs.top == 0


def test_empty_range_is_well_defined():
    # offset past every file's end -> no rows.
    files = [HexFile("a", bytes(8)), HexFile("b", bytes(8))]
    model = HexModel(files, start_offset=64, width=16)
    vs = ViewState(model)
    assert vs.visible_count == 0
    assert vs.row_index_at(0) == 0
    assert vs.max_top(4) == 0
    vs.clamp_top(4)
    assert vs.top == 0


# --------------------------------------------------------------------------- #
# filter / reference changes re-anchor the top row
# --------------------------------------------------------------------------- #
def test_set_only_diff_reanchors_top_to_visible_row():
    a = bytearray(64)
    b = bytearray(64)
    b[40] = 1  # only row 2 differs
    vs = ViewState(_model(bytes(a), bytes(b)))  # 4 rows, all visible
    vs.top = 2  # viewing the differing row
    vs.set_only_diff(True, page_rows=4)
    assert vs.only_diff is True
    assert list(vs.visible_indices()) == [2]
    assert vs.top == 0                       # the only visible row
    assert vs.row_index_at(vs.top) == 2      # still the same global row


def test_set_ref_updates_ref_and_keeps_anchor():
    # SAME/DIFF markers don't depend on the pivot, so the diff set is unchanged;
    # set_ref must still update model.ref and keep the top anchored / valid.
    a = bytearray(64)
    b = bytearray(64)
    b[40] = 1  # row 2 differs
    vs = ViewState(_model(bytes(a), bytes(b)), only_diff=True)
    assert list(vs.visible_indices()) == [2]
    vs.set_ref(1, page_rows=4)
    assert vs.model.ref == 1
    assert list(vs.visible_indices()) == [2]
    assert vs.row_index_at(vs.top) == 2
    vs.set_ref(None, page_rows=4)
    assert vs.model.ref is None


def test_invalidate_forces_recompute():
    a = bytearray(48)
    b = bytearray(48)
    vs = ViewState(_model(bytes(a), bytes(b)), only_diff=True)
    assert list(vs.visible_indices()) == []   # identical -> nothing
    # Mutate the underlying buffer, then invalidate: the cache must rebuild.
    b[20] = 0xFF
    vs.model.files[1].data = bytes(b)
    vs.invalidate()
    assert list(vs.visible_indices()) == [1]


# --------------------------------------------------------------------------- #
# format_status / format_status_parts
# --------------------------------------------------------------------------- #
def test_format_status_all_agree():
    s = format_status(
        offset_start=0, offset_end=0x0F, row_pos=1, row_count=3,
        ref_label="all-agree", ascii_on=True, only_diff=False, markers_on=True,
        sizes=[("a", 48), ("b", 48)],
    )
    assert s == (
        "0x00000000-0x0000000f | row 1/3 | ref=all-agree | "
        "ascii:on diff:off markers:on color:on classes:off | sizes: a=48  b=48"
    )


def test_format_status_ref_and_toggles_off():
    s = format_status(
        offset_start=0x10, offset_end=0x1F, row_pos=2, row_count=4,
        ref_label="b.bin", ascii_on=False, only_diff=True, markers_on=False,
        color_on=False, byte_classes_on=True,
        sizes=[("a.bin", 70), ("b.bin", 70)],
    )
    assert s.startswith("0x00000010-0x0000001f | row 2/4 | ref=b.bin | ")
    assert "ascii:off diff:on markers:off color:off classes:on" in s
    assert s.endswith("sizes: a.bin=70  b.bin=70")


def test_format_status_no_rows():
    s = format_status(
        offset_start=0, offset_end=0, row_pos=0, row_count=0,
        ref_label="all-agree", ascii_on=True, only_diff=True, markers_on=True,
        sizes=[],
    )
    assert s.startswith("no rows | ref=all-agree | ")


def test_format_status_parts_segments():
    # One string per status-bar segment, in display order; format_status is
    # exactly the " | " join of these.
    kwargs = dict(
        offset_start=0, offset_end=0x0F, row_pos=1, row_count=3,
        ref_label="all-agree", ascii_on=True, only_diff=False, markers_on=True,
        sizes=[("a", 48)],
    )
    parts = format_status_parts(**kwargs)
    assert parts == [
        "0x00000000-0x0000000f | row 1/3",
        "ref=all-agree",
        "ascii:on diff:off markers:on color:on classes:off",
        "sizes: a=48",
    ]
    assert format_status(**kwargs) == " | ".join(parts)


# --------------------------------------------------------------------------- #
# format_search_status (the persistent search segment; mirrors the TUI line)
# --------------------------------------------------------------------------- #
def _match(file_index=0, offset=4, length=4):
    return SearchMatch(
        file_index=file_index, path="a.bin", offset=offset, length=length,
        matched=b"RIFF",
    )


def test_format_search_status_inactive_is_none():
    assert format_search_status(None, [], None, None) is None


def test_format_search_status_error_wins():
    assert format_search_status(None, [], None, "bad hex") == "Search error: bad hex"


def test_format_search_status_no_matches():
    q = SearchQuery(mode="text", pattern="RIFF", needle=b"RIFF")
    assert format_search_status(q, [], None, None) == 'Search: text "RIFF" | no matches'


def test_format_search_status_current_match_and_ci_flag():
    q = SearchQuery(mode="text", pattern="riff", needle=b"riff", case_sensitive=False)
    matches = [_match(offset=4), _match(file_index=1, offset=0x20)]
    s = format_search_status(q, matches, 1, None)
    assert s == (
        'Search: text "riff" (ci) | match 2/2 | file 1 | offset 0x00000020'
    )
    # Hex mode never shows a case flag.
    qh = SearchQuery(mode="hex", pattern="52 49", needle=b"RI", case_sensitive=False)
    assert "(ci)" not in format_search_status(qh, matches, 0, None)


# --------------------------------------------------------------------------- #
# format_overlay_status (the persistent overlay segment)
# --------------------------------------------------------------------------- #
def test_format_overlay_status_applicable():
    s = format_overlay_status(
        name="gzip", applicable=True, range_count=6, warning_count=0, error_count=0,
    )
    assert s == "overlay 'gzip': 6 ranges"


def test_format_overlay_status_warnings_and_singular():
    s = format_overlay_status(
        name=None, applicable=True, range_count=1, warning_count=1, error_count=0,
    )
    assert s == "overlay: 1 range, 1 warning"


def test_format_overlay_status_not_applied():
    s = format_overlay_status(
        name="bad", applicable=False, range_count=3, warning_count=0, error_count=2,
    )
    assert s == "overlay 'bad': not applied (2 errors)"
