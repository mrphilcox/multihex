# Copyright (c) 2026 Philip Cox
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for multihex.tui_config: path discovery, load/validate, save.

Pure-module tests (no Textual). They cover the documented loading rules
(missing/invalid/versioned configs) and the atomic, complete save + round-trip.
"""

import os
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from multihex.tui_config import (  # noqa: E402
    SUPPORTED_CONFIG_VERSION,
    TuiSettings,
    default_config_path,
    load_settings,
    save_settings,
)


# -- path discovery --------------------------------------------------------- #
def test_default_path_uses_home_config(monkeypatch, tmp_path):
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    assert default_config_path() == tmp_path / ".config" / "multihex" / "tui.toml"


def test_xdg_config_home_overrides_default(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    assert default_config_path() == tmp_path / "xdg" / "multihex" / "tui.toml"


# -- loading rules ---------------------------------------------------------- #
def test_missing_file_is_not_an_error(tmp_path):
    settings, warnings = load_settings(tmp_path / "nope.toml", TuiSettings())
    assert settings == TuiSettings()
    assert warnings == []


def test_valid_v1_loads(tmp_path):
    p = tmp_path / "tui.toml"
    p.write_text(
        'config_version = 1\n'
        '[display]\n'
        'layout = "side-by-side"\n'
        'ascii = false\n'
        'byte_classes = true\n'
        'color = "never"\n'
        'names = "path"\n'
        '[view]\n'
        'width = 8\n'
        'only_diff = true\n'
    )
    settings, warnings = load_settings(p, TuiSettings())
    assert settings == TuiSettings(
        layout="side-by-side", ascii=False, byte_classes=True, color="never",
        names="path", width=8, only_diff=True,
    )
    assert warnings == []


@pytest.mark.parametrize("mode", ["single", "repeat", "none"])
def test_markers_valid_values_load(tmp_path, mode):
    p = tmp_path / "tui.toml"
    p.write_text(f'config_version = 1\n[display]\nmarkers = "{mode}"\n')
    settings, warnings = load_settings(p, TuiSettings())
    assert settings.markers == mode
    assert warnings == []


def test_missing_markers_defaults_to_single(tmp_path):
    p = tmp_path / "tui.toml"
    p.write_text('config_version = 1\n[display]\nlayout = "stacked"\n')
    settings, warnings = load_settings(p, TuiSettings())
    assert settings.markers == "single"
    assert warnings == []


def test_invalid_markers_falls_back_to_base(tmp_path):
    p = tmp_path / "tui.toml"
    p.write_text('config_version = 1\n[display]\nmarkers = "sometimes"\n')
    base = TuiSettings(markers="repeat")
    settings, warnings = load_settings(p, base)
    assert settings.markers == "repeat"       # invalid -> kept base
    assert warnings and any("markers" in w for w in warnings)


def test_missing_config_version_is_ignored_with_warning(tmp_path):
    p = tmp_path / "tui.toml"
    p.write_text('[display]\nlayout = "side-by-side"\n')
    settings, warnings = load_settings(p, TuiSettings())
    assert settings == TuiSettings()           # config wholly ignored
    assert warnings and "config_version" in warnings[0]


def test_future_config_version_is_ignored_with_warning(tmp_path):
    p = tmp_path / "tui.toml"
    p.write_text(
        f'config_version = {SUPPORTED_CONFIG_VERSION + 1}\n'
        '[display]\nlayout = "side-by-side"\n'
    )
    settings, warnings = load_settings(p, TuiSettings())
    assert settings == TuiSettings()
    assert warnings and "unsupported config_version" in warnings[0]


def test_unknown_keys_do_not_crash(tmp_path):
    p = tmp_path / "tui.toml"
    p.write_text(
        'config_version = 1\nbogus = 3\n'
        '[display]\nlayout = "stacked"\nmystery = 1\n'
    )
    settings, warnings = load_settings(p, TuiSettings())
    assert settings.layout == "stacked"        # valid keys still applied
    assert any("bogus" in w for w in warnings)
    assert any("mystery" in w for w in warnings)


def test_invalid_values_fall_back_to_base(tmp_path):
    p = tmp_path / "tui.toml"
    p.write_text(
        'config_version = 1\n'
        '[display]\nlayout = "sideways"\ncolor = "rainbow"\n'
        '[view]\nwidth = -4\n'
    )
    base = TuiSettings()
    settings, warnings = load_settings(p, base)
    assert settings.layout == base.layout      # invalid -> kept base
    assert settings.color == base.color
    assert settings.width == base.width
    assert len(warnings) == 3


def test_width_true_is_rejected_as_non_int(tmp_path):
    # bool is an int subclass; width must be a real positive int.
    p = tmp_path / "tui.toml"
    p.write_text('config_version = 1\n[view]\nwidth = true\n')
    settings, warnings = load_settings(p, TuiSettings())
    assert settings.width == 16
    assert warnings


def test_parse_error_falls_back_with_warning(tmp_path):
    p = tmp_path / "tui.toml"
    p.write_text("this is not = valid = toml ==\n")
    settings, warnings = load_settings(p, TuiSettings())
    assert settings == TuiSettings()
    assert warnings and "parse" in warnings[0]


def test_unreadable_config_warns_and_uses_base(tmp_path):
    # A path that exists but cannot be read as a file (here, a directory) is an
    # OSError on open; the config is ignored with a warning rather than crashing.
    base = TuiSettings()
    settings, warnings = load_settings(tmp_path, base)
    assert settings == base
    assert warnings and "could not read" in warnings[0]


def test_non_table_sections_are_ignored(tmp_path):
    # [display] / [view] given as scalars instead of tables are skipped with a
    # warning each; the rest of the (here empty) config still loads cleanly.
    p = tmp_path / "tui.toml"
    p.write_text("config_version = 1\ndisplay = 123\nview = 456\n")
    base = TuiSettings()
    settings, warnings = load_settings(p, base)
    assert settings == base
    assert any("[display]: not a table" in w for w in warnings)
    assert any("[view]: not a table" in w for w in warnings)


def test_width_zero_rejected_as_non_positive(tmp_path):
    # The off-by-one boundary: 0 is an int but not a positive width, so it is
    # dropped in favour of the base value.
    p = tmp_path / "tui.toml"
    p.write_text("config_version = 1\n[view]\nwidth = 0\n")
    settings, warnings = load_settings(p, TuiSettings())
    assert settings.width == TuiSettings().width
    assert warnings


# -- saving ----------------------------------------------------------------- #
def test_save_is_complete_and_versioned(tmp_path):
    p = tmp_path / "tui.toml"
    save_settings(TuiSettings(), p)
    text = p.read_text()
    # Every supported key is present, even at default values.
    for key in ("layout", "ascii", "byte_classes", "color", "names", "markers",
                "width", "only_diff"):
        assert key in text
    assert "config_version = 1" in text
    assert 'multihex_version = "0.1.0"' in text


def test_save_creates_parent_dirs(tmp_path):
    p = tmp_path / "a" / "b" / "c" / "tui.toml"
    save_settings(TuiSettings(), p)
    assert p.exists()


def test_save_then_load_round_trips(tmp_path):
    p = tmp_path / "tui.toml"
    original = TuiSettings(
        layout="side-by-side", ascii=False, byte_classes=True, color="always",
        names="path", markers="repeat", width=32, only_diff=True,
    )
    save_settings(original, p)
    loaded, warnings = load_settings(p, TuiSettings())
    assert loaded == original
    assert warnings == []


def test_save_failure_propagates(tmp_path):
    # Parent path is a file, so makedirs/replace cannot succeed.
    blocker = tmp_path / "afile"
    blocker.write_text("x")
    with pytest.raises(OSError):
        save_settings(TuiSettings(), blocker / "tui.toml")


def test_save_failure_after_temp_write_cleans_up(tmp_path, monkeypatch):
    # If the atomic replace fails after the temp file has been written, the
    # error propagates and the temp file is removed rather than left behind.
    import multihex.tui_config as tc

    def boom(*a, **k):
        raise OSError("replace failed")

    monkeypatch.setattr(tc.os, "replace", boom)
    p = tmp_path / "tui.toml"
    with pytest.raises(OSError):
        save_settings(TuiSettings(), p)
    assert not p.exists()
    leftovers = list(tmp_path.glob(".tui-*.toml.tmp"))
    assert leftovers == []
