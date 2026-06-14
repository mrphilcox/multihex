# Copyright (c) 2026 Philip Cox
# SPDX-License-Identifier: Apache-2.0

"""CLI --byte-classes coverage: ANSI styling, color gating, and JSON safety.

Runs the real entry point as a subprocess (like the other CLI tests) over a tiny
purpose-built fixture so the expected escape sequences are unambiguous.
"""

import json
import os
import subprocess
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

# ANSI sequences emitted by multihex.cli for byte classes.
DIM = "\033[2m"
GREEN = "\033[32m"
CYAN = "\033[36m"
ESC = "\033["


@pytest.fixture(scope="module")
def fixture_dir(tmp_path_factory):
    d = tmp_path_factory.mktemp("byte_class_fixtures")
    # Two identical files (so no diffs steal the styling): one byte of each
    # interesting class -> zero, space (ws), 'A' (printable), 0xFF (other).
    data = bytes([0x00, 0x20, 0x41, 0xFF])
    for name in ("a.bin", "b.bin"):
        with open(os.path.join(str(d), name), "wb") as fh:
            fh.write(data)
    return str(d)


def _run(fixture_dir, args):
    cmd = [sys.executable, "-m", "multihex.cli", *args]
    return subprocess.run(
        cmd, cwd=fixture_dir, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True,
    )


def test_byte_classes_color_always_emits_class_styles(fixture_dir):
    out = _run(fixture_dir, ["--byte-classes", "--color", "always",
                             "a.bin", "b.bin"]).stdout
    # zero -> dim, space -> cyan, printable -> green, other -> no class color.
    assert DIM + "00" in out
    assert CYAN + "20" in out
    assert GREEN + "41" in out


def test_byte_classes_color_never_has_no_escapes(fixture_dir):
    out = _run(fixture_dir, ["--byte-classes", "--color", "never",
                             "a.bin", "b.bin"]).stdout
    assert ESC not in out


def test_byte_classes_json_schema_unchanged(fixture_dir):
    plain = _run(fixture_dir, ["--json", "a.bin", "b.bin"]).stdout
    classed = _run(fixture_dir, ["--json", "--byte-classes", "a.bin", "b.bin"]).stdout
    assert ESC not in classed
    # Identical JSON: byte-class is display-only and must not touch the schema.
    assert json.loads(plain) == json.loads(classed)


def test_default_output_unchanged_by_flag_when_color_off(fixture_dir):
    # With color disabled, --byte-classes must not change a thing.
    without = _run(fixture_dir, ["--color", "never", "a.bin", "b.bin"]).stdout
    with_flag = _run(fixture_dir, ["--color", "never", "--byte-classes",
                                   "a.bin", "b.bin"]).stdout
    assert without == with_flag
