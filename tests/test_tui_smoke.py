# Copyright (c) 2026 Philip Cox
# SPDX-License-Identifier: Apache-2.0

"""Smoke tests for the TUI frontend.

The TUI must import and parse args without crashing, and the lazy-import guard
must keep `--help` working even when `textual` is not installed.
"""

import builtins
import subprocess
import sys

import pytest

import multihex.tui as tui_mod


def test_imports_with_textual_present():
    # textual is installed in the venv, so the guard should be clear
    assert tui_mod._TEXTUAL_IMPORT_ERROR is None
    args = tui_mod.parse_args(["a", "b", "--offset", "0x10", "--ref", "0"])
    assert args.offset == 0x10
    assert args.ref == 0


def test_help_exits_zero():
    proc = subprocess.run(
        [sys.executable, "-m", "multihex.tui", "--help"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    assert proc.returncode == 0
    assert b"usage" in proc.stdout.lower()


def test_runs_without_textual_installed(monkeypatch):
    """Simulate `textual` not being installed: import must still succeed,
    --help still works, and main() degrades cleanly with exit code 2."""
    import importlib

    real_import = builtins.__import__

    def blocking_import(name, *a, **kw):
        if name == "textual" or name.startswith("textual."):
            raise ImportError("No module named 'textual' (simulated)")
        return real_import(name, *a, **kw)

    # Drop cached textual + tui modules so the guard re-evaluates.
    for m in list(sys.modules):
        if m == "textual" or m.startswith("textual.") or m == "multihex.tui":
            sys.modules.pop(m, None)

    monkeypatch.setattr(builtins, "__import__", blocking_import)
    mod = importlib.import_module("multihex.tui")

    assert mod._TEXTUAL_IMPORT_ERROR is not None

    # --help must still work (argparse runs before the textual check).
    with pytest.raises(SystemExit) as exc:
        mod.parse_args(["--help"])
    assert exc.value.code == 0

    # Attempting to actually run returns 2 with a helpful message.
    rc = mod.main(["somefile"])
    assert rc == 2

    # Restore the real module for other tests.
    sys.modules.pop("multihex.tui", None)
    importlib.import_module("multihex.tui")
