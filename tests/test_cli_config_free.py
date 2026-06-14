# Copyright (c) 2026 Philip Cox
# SPDX-License-Identifier: Apache-2.0

"""Regression: the batch CLI is config-free.

`multihex` must never grow `--config`/`--no-config` or read the TUI config file;
this keeps scripted output explicit and repeatable. (TUI config lives only in
multihex.tui / multihex.tui_config.)
"""

import os
import subprocess
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from fixtures import build_fixtures  # noqa: E402, I001


@pytest.fixture(scope="module")
def fixtures(tmp_path_factory):
    d = tmp_path_factory.mktemp("config_free_fixtures")
    return str(d), build_fixtures(d)


def _run(fixture_dir, args):
    cmd = [sys.executable, "-m", "multihex.cli", *args]
    return subprocess.run(
        cmd, cwd=fixture_dir, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True,
    )


def test_cli_rejects_config_flag(fixtures):
    fixture_dir, _ = fixtures
    proc = _run(fixture_dir, ["--config", "x.toml", "eqA"])
    assert proc.returncode != 0
    assert "unrecognized arguments" in proc.stderr or "--config" in proc.stderr


def test_cli_rejects_no_config_flag(fixtures):
    fixture_dir, _ = fixtures
    proc = _run(fixture_dir, ["--no-config", "eqA"])
    assert proc.returncode != 0


def test_cli_help_has_no_config_options(fixtures):
    fixture_dir, _ = fixtures
    proc = _run(fixture_dir, ["--help"])
    assert proc.returncode == 0
    assert "--config" not in proc.stdout
    assert "--no-config" not in proc.stdout
