# Copyright (c) 2026 Philip Cox
# SPDX-License-Identifier: Apache-2.0

"""CLI stdin (``-``) coverage: read raw bytes from stdin as one input.

Runs the real entry point as a subprocess (like the other CLI tests) and feeds
bytes via ``input=`` so the binary path is exercised end-to-end. ``-`` is just
another input file whose bytes come from stdin, so these assert that comparison,
markers, search, overlay, and --json behave identically to file input -- only the
source of the bytes (and the ``<stdin>`` label / null path) differ.
"""

import json
import subprocess
import sys

# ANSI emitted by multihex.cli (mirrors test_cli_overlay / test_cli_byte_classes).
OVERLAY = "\033[44m"   # overlay-covered byte (blue background)
GREEN = "\033[32m"     # printable-ASCII byte class
ESC = "\033["

SCHEMA = {"name": "bintools.layout-overlay", "version": 1}


def _run(args, *, stdin=None, cwd=None):
    """Invoke the CLI as a subprocess, optionally piping ``stdin`` bytes."""
    cmd = [sys.executable, "-m", "multihex.cli", *args]
    return subprocess.run(
        cmd, input=stdin, cwd=cwd,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )


def _text(b):
    return b.decode("utf-8", "replace")


def test_stdin_basic_render_is_binary_safe():
    """NUL and high bytes round-trip through stdin into the hex dump."""
    proc = _run(["-"], stdin=b"\x00ABC\xff")
    assert proc.returncode == 0
    out = _text(proc.stdout)
    assert "0x00000000" in out
    assert "00 41 42 43 ff" in out
    # The stdin input is labelled <stdin>, not a path.
    assert "<stdin>" in out


def test_stdin_label_ignores_names_path():
    """--names path cannot invent a filesystem path for stdin; stays <stdin>."""
    proc = _run(["-", "--names", "path"], stdin=b"ABCD")
    assert proc.returncode == 0
    assert "<stdin>" in _text(proc.stdout)


def test_stdin_byte_classes_colored():
    proc = _run(["-", "--byte-classes", "--color", "always"], stdin=b"\x00ABC\xff")
    assert proc.returncode == 0
    out = _text(proc.stdout)
    # Printable ASCII 'A' (0x41) gets the byte-class green; only-one-file so no diff.
    assert GREEN + "41" in out


def test_stdin_json_uses_stdin_name_and_null_path():
    proc = _run(["-", "--json"], stdin=b"\x00ABC\xff")
    assert proc.returncode == 0
    doc = json.loads(proc.stdout)
    assert doc["files"] == ["<stdin>"]
    assert doc["paths"] == [None]
    # Bytes/markers/offset are unchanged shape.
    assert doc["rows"][0]["files"][0]["bytes"] == [0, 65, 66, 67, 255]
    assert doc["rows"][0]["markers"] == ["==", "==", "==", "==", "=="]


def test_stdin_multi_input_comparison(tmp_path):
    """cat a.bin | multihex - b.bin compares stdin against a file at fixed offsets."""
    b = tmp_path / "b.bin"
    b.write_bytes(b"\x00\x01\x02\x03")
    proc = _run(["-", "b.bin"], stdin=b"\x00\xff\x02\x03", cwd=str(tmp_path))
    assert proc.returncode == 0
    out = _text(proc.stdout)
    assert "<stdin>" in out and "b.bin" in out
    # Column 1 differs (ff vs 01); the rest match -> "== != == ==".
    assert "== != == ==" in out


def test_stdin_twice_errors_clearly():
    proc = _run(["-", "-"], stdin=b"")
    assert proc.returncode != 0
    assert "at most once" in _text(proc.stderr)


def test_empty_stdin_is_graceful():
    proc = _run(["-"], stdin=b"")
    assert proc.returncode == 0
    assert proc.stdout == b""
    assert "nothing to display" in _text(proc.stderr)


def test_bare_invocation_does_not_block_on_stdin():
    """No positional -> argparse error before any stdin read; never hangs."""
    proc = _run([], stdin=b"")
    assert proc.returncode == 2
    assert "required" in _text(proc.stderr)


def test_search_within_stdin_by_name_and_index(tmp_path):
    other = tmp_path / "b.bin"
    other.write_bytes(b"\x00\x01\x02\x03")
    by_name = _run(
        ["-", "b.bin", "--search-text", "RIFF", "--search-file", "<stdin>"],
        stdin=b"RIFFdata", cwd=str(tmp_path),
    )
    assert by_name.returncode == 0
    assert "path=<stdin>" in _text(by_name.stdout)
    assert "match=52 49 46 46" in _text(by_name.stdout)

    by_index = _run(
        ["-", "b.bin", "--search-text", "RIFF", "--search-file", "0"],
        stdin=b"RIFFdata", cwd=str(tmp_path),
    )
    assert by_index.returncode == 0
    assert "path=<stdin>" in _text(by_index.stdout)


def test_overlay_source_file_mismatch_still_applies(tmp_path):
    """An overlay naming a different source_file still validates/applies over stdin.

    The validator never compares source_file to a filename, so stdin (which has
    no path) is highlighted exactly like file input.
    """
    (tmp_path / "ov.json").write_text(json.dumps({
        "schema": SCHEMA,
        "name": "demo",
        "source_file": "somewhere-else.bin",
        "ranges": [{"path": "magic", "offset": 0, "length": 2}],
    }))
    proc = _run(["-", "--overlay", "ov.json", "--color", "always"],
                stdin=b"\x00\x01\x02\x03", cwd=str(tmp_path))
    assert proc.returncode == 0
    assert "Loaded layout overlay 'demo'" in _text(proc.stderr)
    # Offsets 0..1 covered -> blue background; offset 2 not covered.
    out = _text(proc.stdout)
    assert OVERLAY + "00" in out
    assert OVERLAY + "02" not in out


def test_overlay_error_reported_not_applied_over_stdin(tmp_path):
    """A structural-error overlay is reported but not highlighted -- as with files."""
    (tmp_path / "err.json").write_text(json.dumps({
        "schema": SCHEMA,
        "ranges": [
            {"path": "dup", "offset": 0, "length": 1},
            {"path": "dup", "offset": 1, "length": 1},
        ],
    }))
    proc = _run(["-", "--overlay", "err.json", "--color", "always"],
                stdin=b"\x00\x01\x02\x03", cwd=str(tmp_path))
    assert proc.returncode == 0
    assert "not applied" in _text(proc.stderr)
    assert OVERLAY not in _text(proc.stdout)


def test_file_input_json_paths_unchanged(tmp_path):
    """Regression guard: a pure file-input --json run keeps string paths (no null)."""
    a = tmp_path / "a.bin"
    a.write_bytes(b"\x00\x01\x02\x03")
    proc = _run(["a.bin", "--json"], cwd=str(tmp_path))
    assert proc.returncode == 0
    doc = json.loads(proc.stdout)
    assert doc["paths"] == ["a.bin"]
    assert doc["files"] == ["a.bin"]
