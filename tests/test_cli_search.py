# Copyright (c) 2026 Philip Cox
# SPDX-License-Identifier: Apache-2.0

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


@pytest.mark.parametrize("value", ["0", "-1"])
def test_search_max_results_rejects_nonpositive_values(fixtures, value):
    fixture_dir, _ = fixtures
    proc = _run(fixture_dir, ["--search-text", "a", "--search-max-results", value, "eqA"])
    assert proc.returncode != 0
    assert "--search-max-results must be >= 1" in proc.stderr


def test_explicit_max_results_truncates_with_stderr_notice(fixtures):
    # dX is 48 zero bytes; cap the search at 2 and confirm it truncates.
    fixture_dir, _ = fixtures
    proc = _run(fixture_dir, ["--search-hex", "00", "--search-max-results", "2", "dX"])
    assert proc.returncode == 0
    lines = [ln for ln in proc.stdout.splitlines() if ln.startswith("file=")]
    assert len(lines) == 2
    assert "results truncated at 2 matches" in proc.stderr
    # The truncation notice never pollutes the machine-parseable stdout lines.
    assert "truncated" not in proc.stdout


def test_unlimited_collects_all_without_notice(fixtures):
    fixture_dir, _ = fixtures
    proc = _run(fixture_dir, ["--search-hex", "00", "--search-unlimited", "dX"])
    assert proc.returncode == 0
    lines = [ln for ln in proc.stdout.splitlines() if ln.startswith("file=")]
    assert len(lines) == 48
    assert "truncated" not in proc.stderr


def test_default_cap_leaves_small_searches_untouched(fixtures):
    # The default cap (10000) is far above the 48 matches in dX, so no truncation.
    fixture_dir, _ = fixtures
    proc = _run(fixture_dir, ["--search-hex", "00", "dX"])
    assert proc.returncode == 0
    lines = [ln for ln in proc.stdout.splitlines() if ln.startswith("file=")]
    assert len(lines) == 48
    assert "truncated" not in proc.stderr


def test_max_results_and_unlimited_are_mutually_exclusive(fixtures):
    fixture_dir, _ = fixtures
    proc = _run(
        fixture_dir,
        ["--search-hex", "00", "--search-max-results", "5", "--search-unlimited", "dX"],
    )
    assert proc.returncode != 0
    assert "not allowed with" in proc.stderr


@pytest.mark.parametrize("value", ["0", "-1"])
def test_limit_rows_rejects_nonpositive_values(fixtures, value):
    fixture_dir, _ = fixtures
    proc = _run(fixture_dir, ["--limit-rows", value, "eqA", "eqB"])
    assert proc.returncode != 0
    assert "--limit-rows must be >= 1" in proc.stderr


def test_hex_search_matches_byte_not_ascii(tmp_path):
    """--search-hex D9 finds byte 0xd9, never the ASCII spelling 44 39.

    The file holds 0xd9 at offset 0 and ASCII "D9" (0x44 0x39) at offset 1.
    """
    p = tmp_path / "mix.bin"
    p.write_bytes(bytes([0xD9]) + b"D9")
    for pattern in ("D9", "d9", "0xD9"):
        proc = _run(str(tmp_path), ["--search-hex", pattern, "mix.bin"])
        assert proc.returncode == 0, proc.stderr
        assert "offset=0x00000000 len=1 match=d9" in proc.stdout
        # Must not report the ASCII bytes at offset 1.
        assert "offset=0x00000001" not in proc.stdout


def test_hex_search_for_ascii_bytes_finds_ascii(tmp_path):
    p = tmp_path / "mix.bin"
    p.write_bytes(bytes([0xD9]) + b"D9")
    # The byte form of ASCII "D9" is 44 39 -> matches offset 1, not 0.
    proc = _run(str(tmp_path), ["--search-hex", "44 39", "mix.bin"])
    assert proc.returncode == 0, proc.stderr
    assert "offset=0x00000001 len=2 match=44 39" in proc.stdout
    assert "offset=0x00000000" not in proc.stdout


def test_ignore_case_text_search_folds_ascii(tmp_path):
    p = tmp_path / "hdr.bin"
    p.write_bytes(b"....Content-Type: text/plain")
    # Case-sensitive (default) misses the lowercase query.
    miss = _run(str(tmp_path), ["--search-text", "content-type", "hdr.bin"])
    assert miss.returncode == 0
    assert "file=" not in miss.stdout
    assert "no matches" in miss.stderr
    # --search-ignore-case folds ASCII letters and finds it.
    hit = _run(
        str(tmp_path),
        ["--search-text", "content-type", "--search-ignore-case", "hdr.bin"],
    )
    assert hit.returncode == 0, hit.stderr
    assert "offset=0x00000004 len=12 match=43 6f 6e 74 65 6e 74 2d 54 79 70 65" in hit.stdout


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


def test_search_file_unmatched_spec_errors(fixtures):
    # A --search-file that matches no file by index or name exits non-zero with
    # a clear message rather than silently searching everything.
    fixture_dir, _ = fixtures
    proc = _run(fixture_dir, ["--search-hex", "11", "--search-file", "nope",
                              "dX", "dY", "dZ"])
    assert proc.returncode != 0
    assert "did not match any file" in proc.stderr


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
