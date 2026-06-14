#!/usr/bin/env bash
# Copyright (c) 2026 Philip Cox
# SPDX-License-Identifier: Apache-2.0

# Run the full local validation suite.
#
# Correctness-oriented layers run by default:
#   lint, default pytest, integration, UI/visual, and stress.
#
# Performance tests are environment-sensitive timing/resource measurements and
# run only when explicitly requested with --include-performance.
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

include_performance=0
keep_going=0

usage() {
  cat <<EOF
Usage: scripts/run-full-test-suite.sh [--include-performance] [--keep-going]

Runs lint, default pytest tests, integration tests, UI/visual tests, and stress
tests. Stress tests are correctness/robustness tests for edge cases and hostile
inputs, so they are included in the default full suite.

Performance tests measure timing, throughput, and resource behavior. They are
environment-sensitive and skipped by default; pass --include-performance to run
scripts/performance/run_all.sh.
EOF
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --include-performance)
      include_performance=1
      ;;
    --keep-going)
      keep_going=1
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown option: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
  shift
done

cd "$REPO_ROOT" || exit 1

names=()
statuses=()
details=()
failed=0

record_result() {
  names+=("$1")
  statuses+=("$2")
  details+=("$3")
}

run_layer() {
  local name="$1"
  shift

  if [ "$failed" -ne 0 ] && [ "$keep_going" -eq 0 ]; then
    printf '\n==== %s ====\n' "$name"
    echo "SKIP $name; previous required layer failed (use --keep-going to continue)"
    record_result "$name" "SKIP" "previous required layer failed"
    return
  fi

  printf '\n==== %s ====\n' "$name"
  printf 'Command:'
  printf ' %q' "$@"
  printf '\n\n'

  if "$@"; then
    echo "PASS $name"
    record_result "$name" "PASS" ""
  else
    local rc=$?
    echo "FAIL $name (exit $rc)"
    record_result "$name" "FAIL" "exit $rc"
    failed=1
  fi
}

echo "Full test suite for multihex"
echo "Stress tests are correctness tests and run by default."
echo "Performance tests are timing/resource measurements and are opt-in."

run_layer "lint" ruff check .
run_layer "default pytest tests" python3 -m pytest
run_layer "integration tests" scripts/integration/run_all.sh
run_layer "UI/visual tests" scripts/ui-tests/run_ui_tests.sh
run_layer "stress tests" scripts/stress/run_all.sh

if [ "$include_performance" -eq 1 ]; then
  run_layer "performance tests" scripts/performance/run_all.sh
else
  printf '\n==== performance tests ====\n'
  echo "SKIP performance tests; use --include-performance to run them"
  record_result "performance tests" "SKIP" "use --include-performance to run them"
fi

printf '\n========================\n'
printf 'Full suite summary\n'
printf '========================\n'

for i in "${!names[@]}"; do
  if [ -n "${details[$i]}" ]; then
    printf '%-24s %s (%s)\n' "${names[$i]}" "${statuses[$i]}" "${details[$i]}"
  else
    printf '%-24s %s\n' "${names[$i]}" "${statuses[$i]}"
  fi
done

if [ "$failed" -eq 0 ]; then
  echo
  echo "Full suite passed."
  exit 0
fi

echo
echo "Full suite failed."
exit 1
