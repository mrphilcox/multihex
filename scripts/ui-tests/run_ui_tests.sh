#!/usr/bin/env bash
# Run the opt-in UI visual-regression suite (tests_ui/).
#
# This is a SEPARATE, heavier validation lane from the default unit tests --
# it is never part of a bare `pytest` run (testpaths = ["tests"]) nor of the
# shell integration runner. Extra args are forwarded to pytest, e.g.:
#
#     scripts/ui-tests/run_ui_tests.sh -k snapshot -q
#
# Requires the optional UI/test deps:  pip install -e '.[ui-test]'
# Tests skip cleanly when textual / PySide6 / pytest-textual-snapshot are absent.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO_ROOT"

# Render Qt headlessly (conftest also sets this; export here for safety).
export QT_QPA_PLATFORM="${QT_QPA_PLATFORM:-offscreen}"
# Allow `import multihex` without an editable install.
export PYTHONPATH="$REPO_ROOT/src${PYTHONPATH:+:$PYTHONPATH}"

exec python3 -m pytest tests_ui "$@"
