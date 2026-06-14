"""Smoke tests for the TUI frontend.

The TUI must import and parse args without crashing, and the lazy-import guard
must keep `--help` working even when `textual` is not installed.
"""

import builtins
import importlib.util
import os
import subprocess
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
TUI_PATH = os.path.join(REPO, "multihex-tui.py")


def _load_tui(module_name):
    """Import multihex-tui.py under a given module name (filename has a hyphen)."""
    spec = importlib.util.spec_from_file_location(module_name, TUI_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def test_imports_with_textual_present():
    mod = _load_tui("multihex_tui_present")
    # textual is installed in the venv, so the guard should be clear
    assert mod._TEXTUAL_IMPORT_ERROR is None
    args = mod.parse_args(["a", "b", "--offset", "0x10", "--ref", "0"])
    assert args.offset == 0x10
    assert args.ref == 0
    sys.modules.pop("multihex_tui_present", None)


def test_help_exits_zero():
    proc = subprocess.run(
        [sys.executable, TUI_PATH, "--help"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    assert proc.returncode == 0
    assert b"usage" in proc.stdout.lower()


def test_runs_without_textual_installed(monkeypatch):
    """Simulate `textual` not being installed: import must still succeed,
    --help still works, and main() degrades cleanly with exit code 2."""
    real_import = builtins.__import__

    def blocking_import(name, *a, **kw):
        if name == "textual" or name.startswith("textual."):
            raise ImportError("No module named 'textual' (simulated)")
        return real_import(name, *a, **kw)

    # Drop any cached textual + tui modules so the guard re-evaluates.
    for m in list(sys.modules):
        if m == "textual" or m.startswith("textual.") or m.startswith("multihex_tui_"):
            sys.modules.pop(m, None)

    monkeypatch.setattr(builtins, "__import__", blocking_import)
    mod = _load_tui("multihex_tui_no_textual")

    assert mod._TEXTUAL_IMPORT_ERROR is not None

    # --help must still work (argparse runs before the textual check).
    with pytest.raises(SystemExit) as exc:
        mod.parse_args(["--help"])
    assert exc.value.code == 0

    # Attempting to actually run returns 2 with a helpful message.
    rc = mod.main(["somefile"])
    assert rc == 2

    sys.modules.pop("multihex_tui_no_textual", None)
