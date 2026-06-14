"""Parity tests: the core model is the single source of truth.

1. HexModel.build_row must match an *independent* recomputation of cells and
   three-state markers from the documented rule, across offsets/widths/refs and
   bounded windows that run past EOF with a partial last row.
2. The batch tool's JSON (multihex.main --json) must report the same cells and
   markers as a direct core walk for the same offset/width/ref/length.
"""

import json
import os
import subprocess
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, REPO)

from fixtures import build_fixtures  # noqa: E402
from multihex_core import HexModel, Marker, format_marker, load_files  # noqa: E402

MULTIHEX = os.path.join(REPO, "multihex.py")


def expected_marker(column, ref):
    """The documented three-state rule, recomputed independently."""
    if any(b is None for b in column):
        return Marker.MISSING
    pivot = column[ref] if ref is not None else column[0]
    return Marker.SAME if all(b == pivot for b in column) else Marker.DIFF


@pytest.fixture(scope="module")
def fixtures(tmp_path_factory):
    d = tmp_path_factory.mktemp("parity_fixtures")
    return str(d), build_fixtures(d)


PARAMS = [
    # (scenario, offset, width, ref, length)
    ("equal", 0, 16, None, None),
    ("equal", 5, 8, 1, 40),
    ("unequal", 0, 16, 0, 0x80),       # past EOF, multiple of width
    ("unequal", 0x10, 16, 1, 0x4a),    # partial last row + missing
    ("unequal", 0, 7, 2, 0x96),        # odd width, runs past largest file
    ("differing", 0, 16, None, None),
    ("identical", 0, 16, 0, 64),
    ("empty", 0, 16, None, 0x20),      # 0-length file -> all missing
]


@pytest.mark.parametrize("scenario,offset,width,ref,length", PARAMS)
def test_build_row_matches_independent_walk(fixtures, scenario, offset, width, ref, length):
    fixture_dir, paths = fixtures
    files = load_files([os.path.join(fixture_dir, p) for p in paths[scenario]])
    model = HexModel(files, start_offset=offset, width=width, ref=ref, length=length)

    for i in range(model.row_count):
        row = model.build_row(i)
        off = offset + i * width
        ncols = len(row.markers)
        # cells: independently read each absolute byte
        for fi, f in enumerate(files):
            exp_cells = [f.byte_at(off + c) for c in range(ncols)]
            assert row.cells[fi] == exp_cells
        # markers: independently recompute from the rule
        for c in range(ncols):
            column = [row.cells[fi][c] for fi in range(len(files))]
            assert row.markers[c] is expected_marker(column, ref)


@pytest.mark.parametrize(
    "scenario,offset,width,ref,length",
    [
        ("equal", 0, 16, None, None),
        ("unequal", 0, 16, 1, 0x4a),
        ("differing", 0, 16, 0, 48),
        ("empty", 0, 16, None, 0x20),
    ],
)
def test_json_matches_core_walk(fixtures, scenario, offset, width, ref, length):
    fixture_dir, paths = fixtures
    names = paths[scenario]

    cmd = [sys.executable, MULTIHEX, *names, "--width", str(width), "--json"]
    if offset:
        cmd += ["--offset", hex(offset)]
    if ref is not None:
        cmd += ["--ref", str(ref)]
    if length is not None:
        cmd += ["--length", hex(length)]

    proc = subprocess.run(cmd, cwd=fixture_dir, stdout=subprocess.PIPE)
    payload = json.loads(proc.stdout)

    files = load_files([os.path.join(fixture_dir, p) for p in names])
    # Mirror the batch frontend's default-length rule (min remaining length)
    # so the core walk uses the same effective window as the tool did.
    eff_length = length
    if eff_length is None:
        eff_length = min(max(0, f.size - offset) for f in files)
    model = HexModel(files, start_offset=offset, width=width, ref=ref, length=eff_length)

    json_rows = payload["rows"]
    assert len(json_rows) == model.row_count
    for jrow, i in zip(json_rows, range(model.row_count)):
        row = model.build_row(i)
        assert jrow["offset"] == row.offset
        assert jrow["markers"] == [format_marker(m) for m in row.markers]
        for fi in range(len(files)):
            assert jrow["files"][fi]["bytes"] == list(row.cells[fi])
