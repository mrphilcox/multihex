"""Pure-Python GUI helper tests: ViewState navigation/filtering + format_status.

These import only ``multihex.gui``'s Qt-free helpers and ``multihex.core``; they
do not touch PySide6, so they run regardless of whether PySide6 is installed.
"""

from multihex.core import HexFile, HexModel
from multihex.gui import ViewState, format_status


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
# format_status
# --------------------------------------------------------------------------- #
def test_format_status_all_agree():
    s = format_status(
        offset_start=0, offset_end=0x0F, row_pos=1, row_count=3,
        ref_label="all-agree", ascii_on=True, only_diff=False, markers_on=True,
        sizes=[("a", 48), ("b", 48)],
    )
    assert s == (
        "0x00000000-0x0000000f | row 1/3 | ref=all-agree | "
        "ascii:on diff:off markers:on | sizes: a=48  b=48"
    )


def test_format_status_ref_and_toggles_off():
    s = format_status(
        offset_start=0x10, offset_end=0x1F, row_pos=2, row_count=4,
        ref_label="b.bin", ascii_on=False, only_diff=True, markers_on=False,
        sizes=[("a.bin", 70), ("b.bin", 70)],
    )
    assert s.startswith("0x00000010-0x0000001f | row 2/4 | ref=b.bin | ")
    assert "ascii:off diff:on markers:off" in s
    assert s.endswith("sizes: a.bin=70  b.bin=70")


def test_format_status_no_rows():
    s = format_status(
        offset_start=0, offset_end=0, row_pos=0, row_count=0,
        ref_label="all-agree", ascii_on=True, only_diff=True, markers_on=True,
        sizes=[],
    )
    assert s.startswith("no rows | ref=all-agree | ")
