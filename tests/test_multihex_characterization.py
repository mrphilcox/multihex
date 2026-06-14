"""Characterization: post-refactor multihex output must equal the goldens.

Goldens were captured from the pre-refactor tool by tests/capture_goldens.py
and are the byte-for-byte contract. Fixtures are rebuilt deterministically into
a temp dir; the tool runs there (so no absolute paths leak into output).
"""

import os
import subprocess
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from fixtures import build_fixtures  # noqa: E402
from golden_cases import CASES  # noqa: E402

GOLDENS = os.path.join(HERE, "goldens")


def _run(fixture_dir, scenario_files, extra_args):
    cmd = [sys.executable, "-m", "multihex.cli", *scenario_files, *extra_args]
    proc = subprocess.run(
        cmd, cwd=fixture_dir, stdout=subprocess.PIPE, stderr=subprocess.PIPE
    )
    return proc.stdout


@pytest.fixture(scope="module")
def fixtures(tmp_path_factory):
    d = tmp_path_factory.mktemp("multihex_fixtures")
    return str(d), build_fixtures(d)


@pytest.mark.parametrize("name,scenario,extra", CASES, ids=[c[0] for c in CASES])
def test_stdout_matches_golden(fixtures, name, scenario, extra):
    fixture_dir, paths = fixtures
    golden_path = os.path.join(GOLDENS, name + ".out")
    with open(golden_path, "rb") as fh:
        expected = fh.read()
    got = _run(fixture_dir, paths[scenario], extra)
    assert got == expected, (
        f"{name}: stdout diverged from golden\n"
        f"--- expected ---\n{expected.decode('utf-8', 'replace')}\n"
        f"--- got ---\n{got.decode('utf-8', 'replace')}"
    )
