# Copyright (c) 2026 Philip Cox
# SPDX-License-Identifier: Apache-2.0

"""CLI --markers coverage: parsing, both layouts, and display-only invariants.

Like test_cli_layout.py these run the real entry point as a subprocess and assert
on properties of the output (not goldens). The central guarantee is that --markers
is display-only: it never changes offsets, bytes, markers, --only-diff, search, or
JSON. It only controls whether/how the marker *text* is drawn.
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
    d = tmp_path_factory.mktemp("markers_fixtures")
    return str(d), build_fixtures(d)


def _run(fixture_dir, args):
    cmd = [sys.executable, "-m", "multihex.cli", *args]
    return subprocess.run(
        cmd, cwd=fixture_dir, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True,
    )


def _has_marker_token(text):
    """True if any line contains a marker token as a standalone word.

    Safe only on fixtures without missing bytes, where ``--`` cannot appear as a
    byte cell. For fixtures that run past EOF use ``_marker_strip_lines``.
    """
    return any(
        t in ("==", "!=", "--")
        for line in text.splitlines()
        for t in line.split()
    )


def _marker_strip_lines(text):
    """Lines that are *only* marker tokens (stacked strips, repeat strips).

    Data lines always carry a file name token, so this never matches them even
    when their byte cells are all ``--`` (missing). The side-by-side ``single``
    prefix is on a data line, so it is intentionally not matched here.
    """
    return [
        ln for ln in text.splitlines()
        if ln.split() and all(t in ("==", "!=", "--") for t in ln.split())
    ]


def _data_lines(text):
    """Lines that carry hex byte data (have an ASCII gutter; markers do not)."""
    return [ln for ln in text.splitlines() if "|" in ln]


# -- parsing ---------------------------------------------------------------- #
def test_default_is_single(fixtures):
    fixture_dir, _ = fixtures
    plain = _run(fixture_dir, ["--length", "0x20", "eqA", "eqB", "eqC"])
    single = _run(fixture_dir,
                  ["--length", "0x20", "--markers", "single", "eqA", "eqB", "eqC"])
    assert plain.returncode == 0
    assert single.stdout == plain.stdout


@pytest.mark.parametrize("mode", ["single", "repeat", "none"])
def test_modes_accepted(fixtures, mode):
    fixture_dir, _ = fixtures
    proc = _run(fixture_dir, ["--length", "0x10", "--markers", mode, "eqA", "eqB"])
    assert proc.returncode == 0
    assert proc.stdout


def test_invalid_markers_rejected(fixtures):
    fixture_dir, _ = fixtures
    proc = _run(fixture_dir, ["--markers", "sometimes", "eqA"])
    assert proc.returncode != 0
    assert "invalid choice" in proc.stderr


# -- stacked layout --------------------------------------------------------- #
def test_stacked_repeat_equals_single(fixtures):
    fixture_dir, _ = fixtures
    common = ["--length", "0x30", "eqA", "eqB", "eqC"]
    single = _run(fixture_dir, ["--markers", "single", *common]).stdout
    repeat = _run(fixture_dir, ["--markers", "repeat", *common]).stdout
    assert repeat == single


def test_stacked_none_hides_markers_but_keeps_bytes(fixtures):
    fixture_dir, _ = fixtures
    common = ["--length", "0x20", "eqA", "eqB", "eqC"]
    single = _run(fixture_dir, ["--markers", "single", *common]).stdout
    none = _run(fixture_dir, ["--markers", "none", *common]).stdout
    assert _has_marker_token(single)
    assert not _has_marker_token(none)
    # The data rows (offsets + hex bytes) are unchanged when markers are hidden.
    assert _data_lines(none) == _data_lines(single)


def test_none_only_diff_still_filters(fixtures):
    fixture_dir, _ = fixtures
    common = ["--length", "0x40", "--only-diff", "u_short", "u_mid", "u_long"]
    with_markers = _run(fixture_dir, common).stdout
    none = _run(fixture_dir, ["--markers", "none", *common]).stdout

    def offsets(text):
        return [ln for ln in text.splitlines() if ln.startswith("0x")]

    # Filtering is marker-based and identical; only the marker text differs.
    assert offsets(none) == offsets(with_markers)
    assert _marker_strip_lines(with_markers)   # default has marker strips
    assert not _marker_strip_lines(none)       # none drops them


# -- side-by-side layout ---------------------------------------------------- #
def test_side_by_side_single_prefixes_one_strip(fixtures):
    fixture_dir, _ = fixtures
    proc = _run(fixture_dir,
                ["--length", "0x10", "--layout", "side-by-side",
                 "--markers", "single", "eqA", "eqB", "eqC"])
    data = next(ln for ln in proc.stdout.splitlines() if "eqA" in ln)
    # The marker strip is a left prefix: marker tokens come before "eqA".
    lead = data.split()[:1]
    assert lead and lead[0] in ("==", "!=", "--")
    assert data.index("==") < data.index("eqA") or data.index("!=") < data.index("eqA")


def test_side_by_side_repeat_has_one_strip_per_file(fixtures):
    fixture_dir, _ = fixtures
    proc = _run(fixture_dir,
                ["--length", "0x10", "--layout", "side-by-side",
                 "--markers", "repeat", "eqA", "eqB", "eqC"])
    lines = proc.stdout.splitlines()
    marker_line = next(
        ln for ln in lines
        if ln.strip() and all(t in ("==", "!=", "--") for t in ln.split())
    )
    # Three files -> the 16-column strip repeats three times on the marker line.
    assert marker_line.split().count("!=") + marker_line.split().count("==") == 16 * 3


def test_side_by_side_none_hides_markers(fixtures):
    fixture_dir, _ = fixtures
    proc = _run(fixture_dir,
                ["--length", "0x10", "--layout", "side-by-side",
                 "--markers", "none", "eqA", "eqB", "eqC"])
    # No standalone marker token anywhere (missing "--" bytes don't appear here).
    assert not _has_marker_token(proc.stdout)


def test_all_modes_show_same_bytes_side_by_side(fixtures):
    fixture_dir, _ = fixtures
    common = ["--length", "0x20", "--layout", "side-by-side", "eqA", "eqB", "eqC"]

    def bytes_only(text):
        # Strip marker tokens; keep the rest so byte data can be compared.
        out = []
        for ln in text.splitlines():
            toks = [t for t in ln.split() if t not in ("==", "!=", "--")]
            if toks:
                out.append(" ".join(toks))
        return out

    single = bytes_only(_run(fixture_dir, ["--markers", "single", *common]).stdout)
    repeat = bytes_only(_run(fixture_dir, ["--markers", "repeat", *common]).stdout)
    none = bytes_only(_run(fixture_dir, ["--markers", "none", *common]).stdout)
    assert single == repeat == none


# -- JSON unchanged --------------------------------------------------------- #
@pytest.mark.parametrize("mode", ["single", "repeat", "none"])
def test_json_unchanged_by_markers(fixtures, mode):
    fixture_dir, _ = fixtures
    common = ["--length", "0x30", "--json", "eqA", "eqB", "eqC"]
    plain = _run(fixture_dir, common).stdout
    out = _run(fixture_dir, ["--markers", mode, *common]).stdout
    assert out == plain
    assert '"markers"' in out  # the markers array is still present


# -- search context honors --markers, match lines unchanged ----------------- #
def test_search_context_honors_markers(fixtures):
    fixture_dir, _ = fixtures
    common = ["--search-hex", "31 34 37", "--search-context", "1",
              "u_short", "u_mid", "u_long"]
    single = _run(fixture_dir, common).stdout
    none = _run(fixture_dir, ["--markers", "none", *common]).stdout

    def match_lines(text):
        return [ln for ln in text.splitlines() if ln.startswith("file=")]

    # Match lines are identical; only the context marker text differs.
    assert match_lines(none) == match_lines(single)
    assert match_lines(single)
    assert _marker_strip_lines(single)         # context rows carry strips
    assert not _marker_strip_lines(none)       # none drops them
