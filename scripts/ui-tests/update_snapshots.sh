#!/usr/bin/env bash
# Copyright (c) 2026 Philip Cox
# SPDX-License-Identifier: Apache-2.0

# Regenerate the TUI SVG snapshot baselines under tests_ui/__snapshots__/.
#
# Run this after an INTENTIONAL TUI rendering change, then review the SVG diff
# carefully before committing (treat it like tests/goldens/*.out). Extra args
# are forwarded to pytest, e.g. to update a single snapshot:
#
#     scripts/ui-tests/update_snapshots.sh -k snapshot_diff_view
#
# Requires:  pip install -e '.[ui-test]'   (needs pytest-textual-snapshot).
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO_ROOT"

export QT_QPA_PLATFORM="${QT_QPA_PLATFORM:-offscreen}"
# Keep snapshot regeneration in the same colour environment as normal compares.
unset NO_COLOR
export PYTHONPATH="$REPO_ROOT/src${PYTHONPATH:+:$PYTHONPATH}"

exec python3 -m pytest tests_ui --snapshot-update "$@"
