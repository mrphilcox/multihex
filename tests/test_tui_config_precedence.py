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


def _resolve(argv):
    return tui.build_startup_settings(tui.parse_args(argv))


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
