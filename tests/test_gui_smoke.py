"""Smoke tests for the GUI frontend.

The GUI must import and parse args without crashing, ``--help`` must work even
when PySide6 is absent (argparse runs before the import guard), and ``main()``
must degrade cleanly with a helpful message when PySide6 is not installed.
"""

import builtins
import importlib
import subprocess
import sys

import pytest

import multihex.gui as gui_mod


def test_parse_args_basic():
    args = gui_mod.parse_args(["a", "b", "--offset", "0x10", "--ref", "0"])
    assert args.offset == 0x10
    assert args.ref == 0
    assert args.files == ["a", "b"]
    assert args.names == "basename"
    assert args.only_diff is False
    assert args.no_ascii is False
    assert args.markers == "single"


def test_parse_args_allows_zero_files():
    # nargs="*" so the GUI can open an empty window and pick files from the menu.
    args = gui_mod.parse_args([])
    assert args.files == []


def test_parse_args_all_options():
    args = gui_mod.parse_args(
        ["f1", "f2", "--width", "0x20", "--no-ascii", "--only-diff",
         "--markers", "none", "--names", "path", "--ref", "1"]
    )
    assert args.files == ["f1", "f2"]
    assert args.width == 0x20
    assert args.no_ascii is True
    assert args.only_diff is True
    assert args.markers == "none"
    assert args.names == "path"
    assert args.ref == 1


def test_main_rejects_bad_width_and_offset():
    # These checks live in main() after the PySide6 guard, so they only fire when
    # PySide6 is importable; gate the test on it (otherwise main() returns 2 for
    # the missing-dependency reason instead and the assertion is meaningless).
    pytest.importorskip("PySide6")
    assert gui_mod.main(["--width", "0", "x"]) == 2
    assert gui_mod.main(["--offset", "-1", "x"]) == 2


def test_help_exits_zero():
    proc = subprocess.run(
        [sys.executable, "-m", "multihex.gui", "--help"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    assert proc.returncode == 0
    assert b"usage" in proc.stdout.lower()


def test_qt_classes_present_when_pyside6_installed():
    pytest.importorskip("PySide6")
    assert gui_mod._PYSIDE6_IMPORT_ERROR is None
    assert hasattr(gui_mod, "MainWindow")
    assert hasattr(gui_mod, "HexCompareView")


def test_runs_without_pyside6_installed(monkeypatch):
    """Simulate PySide6 not being installed: import still succeeds, --help still
    works, and main() degrades cleanly with exit code 2."""
    real_import = builtins.__import__

    def blocking_import(name, *a, **kw):
        if name == "PySide6" or name.startswith("PySide6."):
            raise ImportError("No module named 'PySide6' (simulated)")
        return real_import(name, *a, **kw)

    for m in list(sys.modules):
        if m == "PySide6" or m.startswith("PySide6.") or m == "multihex.gui":
            sys.modules.pop(m, None)

    monkeypatch.setattr(builtins, "__import__", blocking_import)
    mod = importlib.import_module("multihex.gui")

    assert mod._PYSIDE6_IMPORT_ERROR is not None
    # Qt-free helpers must remain available even without PySide6.
    assert hasattr(mod, "ViewState")
    assert hasattr(mod, "format_status")

    # --help must still work (argparse runs before the PySide6 check).
    with pytest.raises(SystemExit) as exc:
        mod.parse_args(["--help"])
    assert exc.value.code == 0

    # Attempting to actually run returns 2 with a helpful message.
    rc = mod.main(["somefile"])
    assert rc == 2

    # Restore the real module for other tests (undo the import block first).
    monkeypatch.undo()
    sys.modules.pop("multihex.gui", None)
    importlib.import_module("multihex.gui")
