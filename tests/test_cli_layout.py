# Copyright (c) 2026 Philip Cox
# SPDX-License-Identifier: Apache-2.0

"""CLI --layout coverage: parsing, side-by-side rendering, and invariants.

Like test_cli_search.py these run the real entry point as a subprocess and
assert on properties of the output (not goldens), so they stay robust to
unrelated rendering changes. The central guarantee is that --layout is
display-only: it never changes offsets, bytes, markers, filtering, or JSON.
"""

import os
import subprocess
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from fixtures import build_fixtures  # noqa: E402, I001


@pytest.fixture(scope="module")
def fixtures(tmp_path_factory):
    d = tmp_path_factory.mktemp("layout_fixtures")
    return str(d), build_fixtures(d)


def _run(fixture_dir, args):
    cmd = [sys.executable, "-m", "multihex.cli", *args]
    return subprocess.run(
        cmd, cwd=fixture_dir, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True,
    )


def _marker_lines(text):
    """Marker rows are the ones whose tokens are only ==, !=, --."""
    out = []
    for line in text.splitlines():
        toks = line.split()
        if toks and all(t in ("==", "!=", "--") for t in toks):
            out.append(" ".join(toks))
    return out


def _leading_markers(text):
    """Marker strips that prefix a data line (side-by-side --markers single).

    Captures the run of marker tokens before the first non-marker token, only
    on lines that also carry file data (so it ignores pure stacked marker rows).
    The offset now rides each data line as a left gutter, so a leading ``0x...``
    token is skipped before the marker run.
    """
    out = []
    for line in text.splitlines():
        toks = line.split()
        if toks and toks[0].startswith("0x"):
            toks = toks[1:]
        lead = []
        for t in toks:
            if t in ("==", "!=", "--"):
                lead.append(t)
            else:
                break
        if lead and len(lead) < len(toks):
            out.append(" ".join(lead))
    return out


# -- parsing ---------------------------------------------------------------- #
def test_default_is_stacked(fixtures):
    fixture_dir, _ = fixtures
    plain = _run(fixture_dir, ["--length", "0x20", "eqA", "eqB", "eqC"])
    stacked = _run(fixture_dir,
                   ["--length", "0x20", "--layout", "stacked", "eqA", "eqB", "eqC"])
    assert plain.returncode == 0
    assert stacked.stdout == plain.stdout


def test_side_by_side_accepted(fixtures):
    fixture_dir, _ = fixtures
    proc = _run(fixture_dir,
                ["--length", "0x10", "--layout", "side-by-side", "eqA", "eqB"])
    assert proc.returncode == 0
    assert proc.stdout


def test_invalid_layout_rejected(fixtures):
    fixture_dir, _ = fixtures
    proc = _run(fixture_dir, ["--layout", "sideways", "eqA"])
    assert proc.returncode != 0
    assert "invalid choice" in proc.stderr


# -- offset is attached to its row's data (no standalone offset line) ------- #
def _no_offset_only_line(text):
    """No output line is just a bare offset label like "0x00000010"."""
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("0x") and len(s.split()) == 1:
            return False
    return True


@pytest.mark.parametrize("layout", ["stacked", "side-by-side"])
@pytest.mark.parametrize("ascii_flag", ["--ascii", "--no-ascii"])
@pytest.mark.parametrize("markers", ["single", "repeat", "none"])
def test_offset_attached_no_standalone_offset_line(fixtures, layout, ascii_flag,
                                                   markers):
    fixture_dir, _ = fixtures
    proc = _run(fixture_dir,
                ["--length", "0x20", "--layout", layout, ascii_flag,
                 "--markers", markers, "dX", "dY", "dZ"])
    assert proc.returncode == 0
    # Every offset shares a line with file data; none sits alone.
    assert _no_offset_only_line(proc.stdout)
    # The line carrying the offset also carries the first file's name+bytes.
    off_line = next(ln for ln in proc.stdout.splitlines()
                    if ln.startswith("0x00000000"))
    assert "dX" in off_line


@pytest.mark.parametrize("layout", ["stacked", "side-by-side"])
@pytest.mark.parametrize("markers", ["single", "repeat", "none"])
def test_no_blank_lines_between_blocks(fixtures, layout, markers):
    """No blank line separates consecutive offset blocks (information density)."""
    fixture_dir, _ = fixtures
    proc = _run(fixture_dir,
                ["--length", "0x20", "--layout", layout,
                 "--markers", markers, "dX", "dY", "dZ"])
    assert proc.returncode == 0
    assert "" not in proc.stdout.splitlines()


def test_offset_attached_with_changed_bytes_and_diff_markers(fixtures):
    fixture_dir, _ = fixtures
    # dX/dY/dZ differ in every column -> the offset line carries diffing bytes.
    proc = _run(fixture_dir,
                ["--length", "0x10", "--layout", "stacked",
                 "--markers", "single", "dX", "dY", "dZ"])
    assert _no_offset_only_line(proc.stdout)
    off_line = next(ln for ln in proc.stdout.splitlines()
                    if ln.startswith("0x00000000"))
    assert "dX" in off_line and "00 00 00" in off_line  # dX bytes on the line


def test_offset_attached_with_uneven_lengths(fixtures):
    fixture_dir, _ = fixtures
    # Past u_short's end, missing bytes render "--"; the offset still attaches.
    proc = _run(fixture_dir,
                ["--offset", "0x10", "--length", "0x10", "--layout", "stacked",
                 "u_short", "u_mid", "u_long"])
    assert _no_offset_only_line(proc.stdout)
    assert "--" in proc.stdout
    off_line = next(ln for ln in proc.stdout.splitlines()
                    if ln.startswith("0x00000010"))
    assert "u_short" in off_line


# -- side-by-side rendering ------------------------------------------------- #
def test_side_by_side_groups_files_on_one_row(fixtures):
    fixture_dir, _ = fixtures
    proc = _run(fixture_dir,
                ["--length", "0x10", "--layout", "side-by-side", "eqA", "eqB", "eqC"])
    lines = proc.stdout.splitlines()
    # The single data row carries every file name horizontally.
    data_line = next(ln for ln in lines if "eqA" in ln)
    assert "eqA" in data_line and "eqB" in data_line and "eqC" in data_line
    # eqA[5]=0x26 but eqB[5]/eqC[5]=0xd9 -> the bytes are present per file.
    assert "26" in data_line and "d9" in data_line


def test_side_by_side_shows_missing_bytes(fixtures):
    fixture_dir, _ = fixtures
    # At 0x10 u_short (20 bytes) has run out -> "--" cells appear on the row.
    proc = _run(fixture_dir,
                ["--offset", "0x10", "--length", "0x10", "--layout", "side-by-side",
                 "u_short", "u_mid", "u_long"])
    data_line = next(ln for ln in proc.stdout.splitlines() if "u_short" in ln)
    assert "--" in data_line


def test_side_by_side_markers_match_stacked(fixtures):
    fixture_dir, _ = fixtures
    common = ["--offset", "0x10", "--length", "0x20", "u_short", "u_mid", "u_long"]
    stacked = _run(fixture_dir, ["--layout", "stacked", *common]).stdout
    side = _run(fixture_dir, ["--layout", "side-by-side", *common]).stdout
    # Default --markers single: side-by-side puts the strip as a left prefix
    # column on the data line; its tokens must match the stacked marker rows.
    assert _leading_markers(side) == _marker_lines(stacked)
    assert _leading_markers(side)  # sanity: there is at least one marker strip


def test_no_ascii_side_by_side_omits_gutters(fixtures):
    fixture_dir, _ = fixtures
    proc = _run(fixture_dir,
                ["--length", "0x10", "--no-ascii", "--layout", "side-by-side",
                 "eqA", "eqB"])
    assert "|" not in proc.stdout


# -- interactions preserved (display-only) ---------------------------------- #
def test_only_diff_filters_same_rows_in_both_layouts(fixtures):
    fixture_dir, _ = fixtures
    common = ["--length", "0x40", "--only-diff", "u_short", "u_mid", "u_long"]
    stacked = _run(fixture_dir, ["--layout", "stacked", *common]).stdout
    side = _run(fixture_dir, ["--layout", "side-by-side", *common]).stdout

    def offsets(text):
        # The offset now rides the first data line as a left gutter, so compare
        # the leading offset tokens (not whole lines, which differ by layout).
        return [ln.split()[0] for ln in text.splitlines() if ln.startswith("0x")]

    assert offsets(side) == offsets(stacked)


def test_ref_markers_match_in_both_layouts(fixtures):
    fixture_dir, _ = fixtures
    common = ["--length", "0x20", "--ref", "0", "u_short", "u_mid", "u_long"]
    stacked = _run(fixture_dir, ["--layout", "stacked", *common]).stdout
    side = _run(fixture_dir, ["--layout", "side-by-side", *common]).stdout
    assert _leading_markers(side) == _marker_lines(stacked)


def test_json_unchanged_by_layout(fixtures):
    fixture_dir, _ = fixtures
    common = ["--length", "0x30", "--json", "eqA", "eqB", "eqC"]
    plain = _run(fixture_dir, common).stdout
    side = _run(fixture_dir, ["--layout", "side-by-side", *common]).stdout
    assert side == plain


# -- search context honors layout, match lines unchanged -------------------- #
def test_search_context_honors_layout(fixtures):
    fixture_dir, _ = fixtures
    common = ["--search-hex", "31 34 37", "--search-context", "1",
              "u_short", "u_mid", "u_long"]
    stacked = _run(fixture_dir, ["--layout", "stacked", *common]).stdout
    side = _run(fixture_dir, ["--layout", "side-by-side", *common]).stdout

    def match_lines(text):
        return [ln for ln in text.splitlines() if ln.startswith("file=")]

    # Match lines are identical regardless of layout.
    assert match_lines(side) == match_lines(stacked)
    assert match_lines(side)
    # A side-by-side context row carries multiple file names on one line.
    grouped = [
        ln for ln in side.splitlines()
        if "u_short" in ln and "u_mid" in ln and "u_long" in ln
    ]
    assert grouped
