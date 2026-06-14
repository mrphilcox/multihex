"""Capture byte-exact stdout goldens from the CURRENT multihex CLI.

Run this BEFORE refactoring:  python tests/capture_goldens.py
It writes tests/goldens/<name>.out (raw stdout bytes) for every case in
golden_cases.CASES. These goldens are the contract the refactor must preserve.
"""

import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from fixtures import build_fixtures  # noqa: E402
from golden_cases import CASES  # noqa: E402


def run_case(fixture_dir, scenario_files, extra_args):
    cmd = [sys.executable, "-m", "multihex.cli", *scenario_files, *extra_args]
    proc = subprocess.run(
        cmd, cwd=fixture_dir, stdout=subprocess.PIPE, stderr=subprocess.PIPE
    )
    return proc.stdout


def main():
    fixture_dir = os.path.join(HERE, "_fixtures")
    os.makedirs(fixture_dir, exist_ok=True)
    paths = build_fixtures(fixture_dir)

    goldens = os.path.join(HERE, "goldens")
    os.makedirs(goldens, exist_ok=True)

    for name, scenario, extra in CASES:
        out = run_case(fixture_dir, paths[scenario], extra)
        with open(os.path.join(goldens, name + ".out"), "wb") as fh:
            fh.write(out)
        print(f"{name}: {len(out)} bytes")


if __name__ == "__main__":
    main()
