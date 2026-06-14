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
