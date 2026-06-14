#!/usr/bin/env bash
# Copyright (c) 2026 Philip Cox
# SPDX-License-Identifier: Apache-2.0

# Run the opt-in performance lane.
#
#     scripts/performance/run_all.sh
#     scripts/performance/run_all.sh -q -k render        # forwarded to pytest
#
# Two stages:
#   1) In-process pytest guardrails (tests_perf/): deterministic operation-count
#      gates plus advisory timing envelopes. Extra args are forwarded to pytest.
#      Set PERF_STRICT=1 to turn the advisory ratio checks into assertions.
#   2) Subprocess CLI characterizations: drive the real `multihex` entry points
#      under scripts/stress/measure.py to record wall-clock seconds and peak RSS
#      for end-to-end paths that only matter as a whole process (`--json`
#      whole-file memory, big-file case-insensitive search). These are reported,
#      never pass/fail, and SKIP cleanly where procfs is unavailable.
#
# This is a SEPARATE validation lane: it is NOT part of a bare
# `python3 -m pytest`, NOT part of scripts/integration/run_all.sh, NOT part of
# scripts/ui-tests/run_ui_tests.sh, and NOT part of scripts/stress/run_all.sh.
set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO_ROOT"

# Allow `import multihex` (and `python3 -m multihex.cli`) without an editable
# install; the measured child processes inherit this environment.
export PYTHONPATH="$REPO_ROOT/src${PYTHONPATH:+:$PYTHONPATH}"

PYTHON="${PYTHON:-python3}"
MEASURE="$REPO_ROOT/scripts/stress/measure.py"
MAKE_INPUT="$REPO_ROOT/scripts/performance/make_input.py"

# Search scans a large file cheaply (a few MB of RSS), so it gets the big input.
PERF_SEARCH_MB="${PERF_SEARCH_MB:-16}"
# `--json` materializes every byte as a Python object before serializing, so its
# RSS is hundreds of times the input. Keep the JSON input deliberately small so
# the lane stays quick and bounded while still exposing that blow-up; raise it
# (and PERF_JSON_RSS_CAP_MB) for a heavier sweep on a roomy host.
PERF_JSON_MB="${PERF_JSON_MB:-2}"
# Safety ceiling for the JSON child's peak RSS (MiB): measure.py kills the group
# if it is exceeded and reports rss_exceeded=1, so a pathological host can never
# be OOM'd. Sized well above a healthy run at PERF_JSON_MB=2.
PERF_JSON_RSS_CAP_MB="${PERF_JSON_RSS_CAP_MB:-4096}"
# Generous wall-clock ceiling for the measured child (seconds). This bounds a
# hang; it is not a perf threshold.
PERF_TIMEOUT="${PERF_TIMEOUT:-180}"

# ---- stage 1: in-process pytest guardrails -------------------------------- #
printf '==== performance tests (pytest guardrails) ====\n'
if ! "$PYTHON" -m pytest tests_perf "$@"; then
  echo "FAIL performance pytest guardrails"
  exit 1
fi

# ---- stage 2: subprocess CLI characterizations ---------------------------- #
printf '\n==== performance characterizations (subprocess) ====\n'

WORK="$(mktemp -d "${TMPDIR:-/tmp}/multihex-perf.XXXXXX")"
cleanup() { rm -rf "$WORK"; }
trap cleanup EXIT

# Small inputs for the memory-hungry JSON path; one large input for search.
json_bytes=$((PERF_JSON_MB * 1024 * 1024))
search_bytes=$((PERF_SEARCH_MB * 1024 * 1024))
json_cap_kb=$((PERF_JSON_RSS_CAP_MB * 1024))
json1="$WORK/json1.bin"; json2="$WORK/json2.bin"; json3="$WORK/json3.bin"
search1="$WORK/search1.bin"
"$PYTHON" "$MAKE_INPUT" "$json1" "$json_bytes" 17
"$PYTHON" "$MAKE_INPUT" "$json2" "$json_bytes" 18
"$PYTHON" "$MAKE_INPUT" "$json3" "$json_bytes" 19
"$PYTHON" "$MAKE_INPUT" "$search1" "$search_bytes" 20

# Run one CLI invocation under measure.py and print a PERF_CHAR line.
#   characterize LABEL [MEASURE_ARG...] -- CMD ARG...
# Args before `--` are passed to measure.py (e.g. --rss-cap-kb); the rest is the
# command to measure.
characterize() {
  local label="$1"; shift
  local measure_args=()
  while [ "$#" -gt 0 ] && [ "$1" != "--" ]; do
    measure_args+=("$1"); shift
  done
  [ "$1" = "--" ] && shift
  local out rc line
  out="$("$PYTHON" "$MEASURE" --timeout "$PERF_TIMEOUT" --out /dev/null \
    "${measure_args[@]}" -- "$@")"
  rc=$?
  if [ "$rc" -eq 77 ]; then
    echo "PERF_CHAR $label SKIP reason=no-procfs"
    return 0
  fi
  line="$(printf '%s\n' "$out" | grep -E '^rc=' | tail -1)"
  if [ -z "$line" ]; then
    echo "PERF_CHAR $label SKIP reason=no-measurement"
    return 0
  fi
  echo "PERF_CHAR $label $line"
}

# JSON over three whole files: materializes every row before serializing, so its
# peak RSS dwarfs the input -- the point of interest. The RSS cap keeps a
# pathological run from OOM'ing the host (rss_exceeded=1 if hit).
characterize json_whole_file --rss-cap-kb "$json_cap_kb" -- \
  "$PYTHON" -m multihex.cli --json "$json1" "$json2" "$json3"

# Case-insensitive search over a large file: folds a full copy of the file
# before scanning. Needle is absent, forcing a full scan.
characterize search_ci_big -- \
  "$PYTHON" -m multihex.cli --search-text zzzperfprobe --search-ignore-case "$search1"

echo
echo "Performance characterizations are informational (no pass/fail thresholds)."
echo "PERF_CHAR fields: rc=child-exit secs=wall-clock peak_kb=peak-RSS."
