# Copyright (c) 2026 Philip Cox
# SPDX-License-Identifier: Apache-2.0

"""Precedence tests for multihex.tui.build_startup_settings.

Exercises the chain *defaults -> config file -> CLI args* by parsing real argv
through parse_args and resolving with build_startup_settings -- no app launch.
"""

import os
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import multihex.tui as tui  # noqa: E402
from multihex.tui_config import TuiSettings, default_config_path, save_settings  # noqa: E402


def _resolve(argv, *, nfiles=None):
    return tui.build_startup_settings(tui.parse_args(argv), nfiles=nfiles)


def test_defaults_when_no_config_no_args(tmp_path, monkeypatch):
    # Point the default path somewhere empty so no real user config interferes.
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    settings, active, warnings = _resolve(["a.bin", "b.bin"])
    assert settings == TuiSettings()
    assert active == default_config_path()
    assert warnings == []


def test_config_overrides_defaults(tmp_path):
    cfg = tmp_path / "c.toml"
    save_settings(TuiSettings(layout="side-by-side", width=8), cfg)
    settings, active, _ = _resolve(["--config", str(cfg), "a.bin"])
    assert settings.layout == "side-by-side"
    assert settings.width == 8
    assert active == cfg               # --config is the active save target


def test_cli_overrides_config(tmp_path):
    cfg = tmp_path / "c.toml"
    save_settings(TuiSettings(layout="stacked", width=8), cfg)
    settings, _, _ = _resolve(
        ["--config", str(cfg), "--layout", "side-by-side", "--width", "32", "a.bin"]
    )
    assert settings.layout == "side-by-side"   # CLI wins
    assert settings.width == 32


def test_cli_width_wins_over_invalid_config_value(tmp_path):
    cfg = tmp_path / "c.toml"
    cfg.write_text("config_version = 1\n[view]\nwidth = -4\n")
    settings, _, warnings = _resolve(["--config", str(cfg), "--width", "32", "a.bin"])
    assert settings.width == 32                # invalid config dropped, CLI wins
    assert warnings                            # but the invalid value was reported


def test_no_config_ignores_file_but_honors_cli(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    # Even a real default config is bypassed by --no-config.
    save_settings(TuiSettings(layout="side-by-side"), default_config_path())
    settings, active, warnings = _resolve(
        ["--no-config", "--width", "32", "a.bin"]
    )
    assert settings.layout == "stacked"        # config ignored -> default
    assert settings.width == 32                # CLI still honored
    assert active == default_config_path()     # save target = default path
    assert warnings == []


def test_one_way_bool_flags_force_on(tmp_path):
    cfg = tmp_path / "c.toml"
    save_settings(TuiSettings(only_diff=False, byte_classes=False, ascii=True), cfg)
    settings, _, _ = _resolve(
        ["--config", str(cfg), "--only-diff", "--byte-classes", "--no-ascii", "a.bin"]
    )
    assert settings.only_diff is True
    assert settings.byte_classes is True
    assert settings.ascii is False


def test_config_and_no_config_are_mutually_exclusive():
    with pytest.raises(SystemExit):
        tui.parse_args(["--config", "x.toml", "--no-config", "a.bin"])


# -- one-file marker startup default ---------------------------------------- #
def test_one_file_no_markers_flag_defaults_none(tmp_path, monkeypatch):
    # A single file with no --markers flag starts with the strip hidden.
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    settings, _, _ = _resolve(["a.bin"], nfiles=1)
    assert settings.markers == "none"


def test_one_file_explicit_markers_flag_wins(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    settings, _, _ = _resolve(["--markers", "single", "a.bin"], nfiles=1)
    assert settings.markers == "single"


def test_multiple_files_keep_single_default(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    settings, _, _ = _resolve(["a.bin", "b.bin"], nfiles=2)
    assert settings.markers == "single"


def test_one_file_default_overrides_config_markers(tmp_path):
    # The one-file startup default deliberately beats a config preference when no
    # --markers flag is given (documented behavior); runtime cycling still works.
    cfg = tmp_path / "c.toml"
    save_settings(TuiSettings(markers="repeat"), cfg)
    settings, _, _ = _resolve(["--config", str(cfg), "a.bin"], nfiles=1)
    assert settings.markers == "none"


def test_config_markers_kept_for_multiple_files(tmp_path):
    cfg = tmp_path / "c.toml"
    save_settings(TuiSettings(markers="repeat"), cfg)
    settings, _, _ = _resolve(["--config", str(cfg), "a.bin", "b.bin"], nfiles=2)
    assert settings.markers == "repeat"
