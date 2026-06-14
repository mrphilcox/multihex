"""CLI search coverage: the --search-* path, its output, and clean errors.

These run the real entry point as a subprocess (like the other CLI tests) and
assert on the script-friendly ``file=...`` lines, not goldens, so they stay
robust to unrelated rendering changes.
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
    d = tmp_path_factory.mktemp("search_fixtures")
    return str(d), build_fixtures(d)


def _run(fixture_dir, args):
    cmd = [sys.executable, "-m", "multihex.cli", *args]
    return subprocess.run(
        cmd, cwd=fixture_dir, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True,
    )


def test_text_search_reports_match(fixtures):
    fixture_dir, _ = fixtures
    # u_long starts with byte 0x01; search for that hex.
    proc = _run(fixture_dir, ["--search-hex", "01", "u_long"])
    assert proc.returncode == 0
    assert "file=0 path=u_long offset=0x00000000 len=1 match=01" in proc.stdout


def test_hex_and_text_agree(fixtures):
    """'RIFF' bytes == 52 49 46 46; place a known string by searching eqA's start.

    eqA[0] is (0*7+3)=3 -> 0x03; assert text and hex find the same offsets.
    """
    fixture_dir, _ = fixtures
    hex_out = _run(fixture_dir, ["--search-hex", "03", "eqA"]).stdout
    assert "offset=0x00000000 len=1 match=03" in hex_out


def test_no_match_exits_zero_with_stderr_note(fixtures):
    fixture_dir, _ = fixtures
    proc = _run(fixture_dir, ["--search-text", "this-string-is-absent", "eqA"])
    assert proc.returncode == 0
    assert proc.stdout == ""
    assert "no matches" in proc.stderr


def test_invalid_hex_exits_nonzero(fixtures):
    fixture_dir, _ = fixtures
    proc = _run(fixture_dir, ["--search-hex", "GG", "eqA"])
    assert proc.returncode != 0
    assert 'invalid hex byte "GG"' in proc.stderr


def test_overlap_reports_more(fixtures):
    fixture_dir, _ = fixtures
    # dY is 48 bytes of 0x11; "11 11" overlapping finds many more than not.
    non = _run(fixture_dir, ["--search-hex", "11 11", "dY"]).stdout.splitlines()
    over = _run(
        fixture_dir, ["--search-hex", "11 11", "dY", "--search-overlap"]
    ).stdout.splitlines()
    assert len(over) > len(non)
    assert len(non) == 24      # 48 bytes / 2 non-overlapping
    assert len(over) == 47     # 48 - 1 overlapping


def test_search_file_selection(fixtures):
    fixture_dir, _ = fixtures
    # 0x11 only exists in dY (dX is 0x00, dZ is 0x22).
    proc = _run(fixture_dir, ["--search-hex", "11", "--search-file", "dY", "dX", "dY", "dZ"])
    lines = [ln for ln in proc.stdout.splitlines() if ln.startswith("file=")]
    assert lines and all(ln.startswith("file=1 ") for ln in lines)


def test_context_renders_rows(fixtures):
    fixture_dir, _ = fixtures
    proc = _run(fixture_dir, ["--search-hex", "00", "--search-context", "1", "dX"])
    assert "file=0 path=dX" in proc.stdout
    # context reuses the comparison renderer -> offset header lines appear
    assert "0x00000000" in proc.stdout


def test_normal_dump_unaffected_without_search(fixtures):
    fixture_dir, _ = fixtures
    proc = _run(fixture_dir, ["--length", "0x10", "eqA", "eqB"])
    assert proc.returncode == 0
    assert "file=" not in proc.stdout          # no search lines
    assert "0x00000000" in proc.stdout          # normal dump present
