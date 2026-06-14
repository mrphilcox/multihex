"""Packaging metadata checks for console script entry points."""

from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python < 3.11
    import tomli as tomllib


def test_console_scripts_include_gui_launcher():
    data = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))

    assert data["project"]["scripts"]["multihex-gui"] == "multihex.gui:main"

