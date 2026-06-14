#!/usr/bin/env bash
# Copyright (c) 2026 Philip Cox
# SPDX-License-Identifier: Apache-2.0

# Run every multihex STRESS script and aggregate the result.
#
#     scripts/stress/run_all.sh
#
# This is a SEPARATE, opt-in lane: it is NOT part of `pytest`, NOT part of
# scripts/integration/run_all.sh, and NOT wired into any automatic CI lane. It
# probes scale / resource pressure / hostile inputs. Each sub-script owns its
# own temp dir, cleanup, and PASS/FAIL/SKIP/FINDING/CHAR output; this wrapper
# runs them and exits non-zero iff any sub-script failed.
#
# Env knobs (see README.md): KEEP_WORK=1, STRESS_FAST=1, STRESS_LARGE_GIB,
# STRESS_SEARCH_MIB, PYTHON. KEEP_WORK is passed through the environment.
set -uo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

SCRIPTS=(
  run_stress_degenerate.sh
  run_stress_output.sh
  run_stress_access.sh
  run_stress_args.sh
  run_stress_many_files.sh
  run_stress_search.sh
  run_stress_large_files.sh
  run_stress_overlay.sh
  run_stress_ui.sh
)

failed=0
ran=0
for s in "${SCRIPTS[@]}"; do
  [ -x "$DIR/$s" ] || continue
  printf '\n==== %s ====\n' "$s"
  ran=$((ran + 1))
  if ! "$DIR/$s"; then
    failed=$((failed + 1))
  fi
done

printf '\n========================\n'
if [ "$ran" -eq 0 ]; then
  echo "No stress scripts found to run."
  exit 1
fi
if [ "$failed" -eq 0 ]; then
  echo "All $ran stress script(s) passed (findings/characterizations are expected, not failures)."
else
  echo "==> $failed of $ran stress script(s) failed."
fi
exit "$( [ "$failed" -eq 0 ] && echo 0 || echo 1 )"
