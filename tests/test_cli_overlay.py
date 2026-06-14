"""CLI --overlay coverage: highlight ANSI, diagnostics, JSON safety, no-op path.

Runs the real entry point as a subprocess (like the other CLI tests) over tiny
purpose-built fixtures so the expected escape sequences and stderr text are
unambiguous.
"""

import json
import os
import subprocess
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

# ANSI emitted by multihex.cli for an overlay-covered byte (blue background).
OVERLAY = "\033[44m"
RED = "\033[31m"   # a cell that differs from the reference
DIM = "\033[2m"    # a missing ("--") cell
ESC = "\033["

SCHEMA = {"name": "bintools.layout-overlay", "version": 1}


def _run(cwd, args):
    cmd = [sys.executable, "-m", "multihex.cli", *args]
    return subprocess.run(
        cmd, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
    )


@pytest.fixture(scope="module")
def fixture_dir(tmp_path_factory):
    d = tmp_path_factory.mktemp("overlay_cli")
    # Two identical files so the covered bytes are SAME (not diffs).
    data = bytes(range(16))
    for name in ("a.bin", "b.bin"):
        (d / name).write_bytes(data)
    # A valid overlay covering offsets 0..1.
    (d / "ok.json").write_text(json.dumps({
        "schema": SCHEMA,
        "name": "demo",
        "ranges": [{"path": "magic", "offset": 0, "length": 2}],
    }))
    # A structural-error overlay (duplicate path).
    (d / "err.json").write_text(json.dumps({
        "schema": SCHEMA,
        "ranges": [
            {"path": "dup", "offset": 0, "length": 1},
            {"path": "dup", "offset": 1, "length": 1},
        ],
    }))
    # A warning-only overlay (unknown type).
    (d / "warn.json").write_text(json.dumps({
        "schema": SCHEMA,
        "ranges": [{"path": "x", "offset": 0, "length": 1, "type": "float128"}],
    }))
    return str(d)


def test_overlay_highlights_covered_bytes(fixture_dir):
    r = _run(fixture_dir, ["--overlay", "ok.json", "--color", "always",
                           "a.bin", "b.bin"])
    # Byte 00 at offset 0 is covered -> blue background; byte at offset 2 is not.
    assert OVERLAY + "00" in r.stdout
    assert OVERLAY + "02" not in r.stdout
    assert "Loaded layout overlay 'demo'" in r.stderr


def test_overlay_no_color_emits_no_escapes(fixture_dir):
    r = _run(fixture_dir, ["--overlay", "ok.json", "--color", "never",
                           "a.bin", "b.bin"])
    assert ESC not in r.stdout


def test_overlay_warning_reported_and_applied(fixture_dir):
    r = _run(fixture_dir, ["--overlay", "warn.json", "--color", "always",
                           "a.bin", "b.bin"])
    assert r.returncode == 0
    assert "warning" in r.stderr
    assert "unknown-type" in r.stderr
    # Still applied: offset 0 is highlighted.
    assert OVERLAY + "00" in r.stdout


def test_overlay_error_reported_and_not_applied(fixture_dir):
    r = _run(fixture_dir, ["--overlay", "err.json", "--color", "always",
                           "a.bin", "b.bin"])
    assert r.returncode == 0  # the comparison still renders
    assert "duplicate-path" in r.stderr
    assert "not applied" in r.stderr
    # Not applied -> no overlay background anywhere.
    assert OVERLAY not in r.stdout


def test_overlay_does_not_affect_json(fixture_dir):
    plain = _run(fixture_dir, ["--json", "a.bin", "b.bin"]).stdout
    withov = _run(fixture_dir, ["--json", "--overlay", "ok.json",
                                "a.bin", "b.bin"]).stdout
    assert json.loads(plain) == json.loads(withov)
    assert ESC not in withov


def test_no_overlay_output_unchanged(fixture_dir):
    # Sanity: omitting --overlay leaves stdout free of overlay escapes.
    r = _run(fixture_dir, ["--color", "always", "a.bin", "b.bin"])
    assert OVERLAY not in r.stdout


# -- render priority: diff/missing must win over overlay --------------------- #
@pytest.fixture(scope="module")
def priority_dir(tmp_path_factory):
    # base.bin is the reference; diff.bin differs only at offset 0; short.bin is
    # a single byte so offsets covered by the overlay are *missing* in it. The
    # overlay covers offset 0 (for the diff case) and offsets 4..5 (for missing).
    d = tmp_path_factory.mktemp("overlay_priority")
    base = bytes(range(16))
    (d / "base.bin").write_bytes(base)
    (d / "diff.bin").write_bytes(b"\xff" + base[1:])
    (d / "short.bin").write_bytes(b"\x00")
    (d / "prio.json").write_text(json.dumps({
        "schema": SCHEMA,
        "name": "prio",
        "ranges": [
            {"path": "head", "offset": 0, "length": 1},
            {"path": "tail", "offset": 4, "length": 2},
        ],
    }))
    return str(d)


def test_diff_wins_over_overlay(priority_dir):
    # At offset 0: base (reference) byte is covered -> overlay; diff.bin's byte
    # differs from the reference -> red, NOT swallowed by the overlay highlight.
    r = _run(priority_dir, ["--overlay", "prio.json", "--color", "always",
                            "base.bin", "diff.bin"])
    assert OVERLAY + "00" in r.stdout   # reference byte, covered, not a diff
    assert RED + "ff" in r.stdout       # differing byte stays a diff
    assert OVERLAY + "ff" not in r.stdout


def test_missing_wins_over_overlay(priority_dir):
    # short.bin has no bytes at offsets 4..5, so those covered cells are missing
    # ("--", dimmed) -- the overlay must never wrap a missing cell. --length is
    # needed because the default window is the shortest file's length (1 byte),
    # which would never reach the missing covered offsets.
    r = _run(priority_dir, ["--overlay", "prio.json", "--color", "always",
                            "--length", "6", "base.bin", "short.bin"])
    assert OVERLAY + "04" in r.stdout   # present+covered byte still highlighted
    assert DIM + "--" in r.stdout       # the missing covered cell is dimmed
    assert OVERLAY + "--" not in r.stdout


# -- a range spanning a row boundary highlights on both rows ----------------- #
@pytest.fixture(scope="module")
def boundary_dir(tmp_path_factory):
    # 20 bytes => two 16-wide rows (0x00..0x0f, 0x10..0x13). The overlay range
    # straddles the split: offsets 14,15 on row 0 and 16,17 on row 1.
    d = tmp_path_factory.mktemp("overlay_boundary")
    data = bytes(range(20))
    for name in ("a.bin", "b.bin"):
        (d / name).write_bytes(data)
    (d / "span.json").write_text(json.dumps({
        "schema": SCHEMA,
        "name": "span",
        "ranges": [{"path": "spanning", "offset": 14, "length": 4}],
    }))
    return str(d)


def test_overlay_highlights_across_row_boundary(boundary_dir):
    r = _run(boundary_dir, ["--overlay", "span.json", "--color", "always",
                            "a.bin", "b.bin"])
    assert OVERLAY + "0e" in r.stdout   # offset 14, last covered byte on row 0
    assert OVERLAY + "10" in r.stdout   # offset 16, first covered byte on row 1
    assert OVERLAY + "0d" not in r.stdout   # offset 13, just before the range
    assert OVERLAY + "12" not in r.stdout   # offset 18, just after the range
