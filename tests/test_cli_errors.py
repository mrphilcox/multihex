# Copyright (c) 2026 Philip Cox
# SPDX-License-Identifier: Apache-2.0

"""CLI argument-validation and error-path coverage.

These exercise the ``main()`` validation guards in ``multihex.cli`` through the
real entry point (subprocess, like the other CLI tests), asserting both a
non-zero exit and the exact ``multihex: ...`` stderr message. They run in the
default pytest suite; the equivalent checks previously lived only in the opt-in
``scripts/integration/run_cli_behaviors.sh``.

``--limit-rows`` / ``--search-max-results`` non-positive handling is already
covered in ``test_cli_search.py`` and is not duplicated here.
"""

import json
import os
import subprocess
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from fixtures import build_fixtures  # noqa: E402, I001


@pytest.fixture(scope="module")
def fixtures(tmp_path_factory):
    d = tmp_path_factory.mktemp("error_fixtures")
    return str(d), build_fixtures(d)


def _run(fixture_dir, args):
    cmd = [sys.executable, "-m", "multihex.cli", *args]
    return subprocess.run(
        cmd, cwd=fixture_dir, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True,
    )


def test_width_zero_rejected(fixtures):
    fixture_dir, _ = fixtures
    proc = _run(fixture_dir, ["--width", "0", "eqA", "eqB"])
    assert proc.returncode != 0
    assert "--width must be >= 1" in proc.stderr


def test_offset_negative_rejected(fixtures):
    fixture_dir, _ = fixtures
    proc = _run(fixture_dir, ["--offset", "-1", "eqA", "eqB"])
    assert proc.returncode != 0
    assert "--offset must be >= 0" in proc.stderr


def test_length_negative_rejected(fixtures):
    fixture_dir, _ = fixtures
    proc = _run(fixture_dir, ["--length", "-1", "eqA", "eqB"])
    assert proc.returncode != 0
    assert "--length must be >= 0" in proc.stderr


def test_ref_out_of_range_rejected(fixtures):
    fixture_dir, _ = fixtures
    # Two files -> valid refs are 0 and 1; 9 is out of range.
    proc = _run(fixture_dir, ["--ref", "9", "eqA", "eqB"])
    assert proc.returncode != 0
    assert "--ref 9 out of range (have 2 files)" in proc.stderr


def test_around_without_colon_rejected(fixtures):
    fixture_dir, _ = fixtures
    proc = _run(fixture_dir, ["--around", "0x40", "eqA"])
    assert proc.returncode != 0
    assert "--around expects OFF:N" in proc.stderr


def test_around_nonnumeric_rejected(fixtures):
    fixture_dir, _ = fixtures
    proc = _run(fixture_dir, ["--around", "zz:8", "eqA"])
    assert proc.returncode != 0
    # argparse surfaces the ValueError text from parse_around.
    assert proc.returncode == 2


def test_around_extra_colon_rejected(fixtures):
    # OFF:N splits on the first colon only, so a second colon lands in N and
    # fails the integer parse rather than being silently accepted.
    fixture_dir, _ = fixtures
    proc = _run(fixture_dir, ["--around", "0x40:8:16", "eqA"])
    assert proc.returncode == 2


def test_json_all_missing_window_is_valid(fixtures):
    # A window entirely past EOF still produces well-formed JSON: every row is
    # present with all-null bytes rather than an error or truncated document.
    fixture_dir, _ = fixtures
    proc = _run(fixture_dir, ["--json", "--offset", "0x1000", "--length", "0x10",
                              "eqA"])
    assert proc.returncode == 0
    doc = json.loads(proc.stdout)
    assert doc["rows"], "expected rows even when the window is past EOF"
    for row in doc["rows"]:
        for f in row["files"]:
            assert all(b is None for b in f["bytes"])


def test_missing_file_reports_oserror(fixtures):
    fixture_dir, _ = fixtures
    proc = _run(fixture_dir, ["no_such_file.bin"])
    assert proc.returncode != 0
    assert "multihex:" in proc.stderr
    assert "no_such_file.bin" in proc.stderr


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="platform has no os.mkfifo")
def test_fifo_input_rejected_quickly(fixtures):
    # A FIFO with no writer used to block the open() syscall forever. The loader
    # now stats it first and rejects it, so the CLI exits non-zero immediately.
    # The subprocess timeout makes a regression fail fast instead of hanging the
    # suite.
    fixture_dir, _ = fixtures
    fifo = os.path.join(fixture_dir, "input_fifo")
    if os.path.exists(fifo):
        os.remove(fifo)
    os.mkfifo(fifo)
    try:
        cmd = [sys.executable, "-m", "multihex.cli", "input_fifo"]
        proc = subprocess.run(
            cmd, cwd=fixture_dir, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, timeout=10,
        )
    finally:
        os.remove(fifo)
    assert proc.returncode != 0
    assert "multihex:" in proc.stderr
    assert "input_fifo" in proc.stderr


def test_search_context_negative_rejected(fixtures):
    fixture_dir, _ = fixtures
    proc = _run(
        fixture_dir, ["--search-hex", "00", "--search-context", "-1", "dX"]
    )
    assert proc.returncode != 0
    assert "--search-context must be >= 0" in proc.stderr
