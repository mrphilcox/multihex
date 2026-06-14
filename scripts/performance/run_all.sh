#!/usr/bin/env bash
# Copyright (c) 2026 Philip Cox
# SPDX-License-Identifier: Apache-2.0

# Run the opt-in performance smoke tests.
#
#     scripts/performance/run_all.sh
#     scripts/performance/run_all.sh -q -k core_render
#
# This is a SEPARATE validation lane: it is NOT part of a bare
# `python3 -m pytest`, NOT part of scripts/integration/run_all.sh, NOT part of
# scripts/ui-tests/run_ui_tests.sh, and NOT part of scripts/stress/run_all.sh.
# Extra args are forwarded to pytest.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO_ROOT"

# Allow `import multihex` without an editable install.
export PYTHONPATH="$REPO_ROOT/src${PYTHONPATH:+:$PYTHONPATH}"

printf '==== performance tests ====\n'
exec python3 -m pytest tests_perf "$@"
