# shellcheck shell=bash
# Copyright (c) 2026 Philip Cox
# SPDX-License-Identifier: Apache-2.0

# Shared helpers for the multihex STRESS scripts.
#
# Source this file; do not execute it:
#     . "$(dirname "${BASH_SOURCE[0]}")/lib.sh"
#
# Builds on the integration-suite idioms (PASS/FAIL/SKIP counters, a
# KEEP_WORK-aware temp dir, exit-code+output assertions) and adds the machinery
# the stress dimensions need: resource measurement via measure.py, generous
# bound assertions, resource-availability guards that SKIP cleanly, a
# consolidated cleanup stack (so chmod/fifo/mount teardown always runs), and
# CHAR/FINDING verdicts for characterising known ceilings without failing by
# design. Stdlib-Python + bash only; Linux-only (procfs).

_STRESS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$_STRESS_DIR/../.." && pwd)"

PYTHON="${PYTHON:-python3}"
export PYTHONPATH="$REPO_ROOT/src${PYTHONPATH:+:$PYTHONPATH}"

# STRESS_FAST=1 shrinks every scale dimension so the harness itself can be
# smoke-tested quickly. Scripts call fast_pick to choose a value.
fast() { [ "${STRESS_FAST:-0}" = "1" ]; }
# fast_pick FULL FAST -> echoes FAST when STRESS_FAST=1, else FULL.
fast_pick() { if fast; then echo "$2"; else echo "$1"; fi; }

PASS_COUNT=0
FAIL_COUNT=0
SKIP_COUNT=0
FINDING_COUNT=0
CHAR_COUNT=0

pass() { PASS_COUNT=$((PASS_COUNT + 1)); printf 'PASS: %s\n' "$*"; }
fail() { FAIL_COUNT=$((FAIL_COUNT + 1)); printf 'FAIL: %s\n' "$*"; }
skip() { SKIP_COUNT=$((SKIP_COUNT + 1)); printf 'SKIP: %s\n' "$*"; }

# A FINDING is the *defined failure mode* of a probe (a documented hazard we are
# deliberately demonstrating: a hang, an uncaught-error traceback, an unbounded
# match list). It counts as a PASS for the suite's exit status -- the test has
# done its job by confirming the hazard -- but is printed distinctly so the
# report and a human reader can see it.
finding() { FINDING_COUNT=$((FINDING_COUNT + 1)); PASS_COUNT=$((PASS_COUNT + 1)); printf 'FINDING: %s\n' "$*"; }

# A CHAR line records an observed ceiling (RSS/time) for a known, generously
# bounded characterisation test. It is informational and counts as a PASS.
characterize() { CHAR_COUNT=$((CHAR_COUNT + 1)); PASS_COUNT=$((PASS_COUNT + 1)); printf 'CHAR: %s\n' "$*"; }

# --------------------------------------------------------------------------- #
# Work dir + consolidated cleanup stack
# --------------------------------------------------------------------------- #
_CLEANUPS=()
# register_cleanup CMD: run CMD on exit (in reverse registration order), before
# the work dir is removed. Use for chmod-restore, fifo removal, etc., so teardown
# happens even when a test fails midway.
register_cleanup() { _CLEANUPS+=("$*"); }

_run_cleanups() {
  local i
  for (( i=${#_CLEANUPS[@]}-1 ; i>=0 ; i-- )); do
    eval "${_CLEANUPS[$i]}" 2>/dev/null || true
  done
}

_on_exit() {
  _run_cleanups
  if [ -n "${WORK:-}" ]; then
    if [ "${KEEP_WORK:-0}" = "1" ]; then
      printf 'KEEP_WORK=1: left work dir at %s\n' "$WORK"
    else
      rm -rf "$WORK"
    fi
  fi
}

setup_workdir() {
  WORK="$(mktemp -d "${TMPDIR:-/tmp}/multihex-stress.XXXXXX")"
  trap _on_exit EXIT
}

# finish: print a one-line summary and exit non-zero if anything FAILed.
# FINDING/CHAR are folded into the pass count but also reported separately.
finish() {
  printf -- '---- %d passed, %d failed, %d skipped  (%d findings, %d characterizations)\n' \
    "$PASS_COUNT" "$FAIL_COUNT" "$SKIP_COUNT" "$FINDING_COUNT" "$CHAR_COUNT"
  [ "$FAIL_COUNT" -eq 0 ]
}

# --------------------------------------------------------------------------- #
# Plain command capture (exit code + output), as in integration/lib.sh
# --------------------------------------------------------------------------- #
# run_capture WANT CMD...: run CMD, capture stdout->$LAST_OUT, stderr->$LAST_ERR,
# set $LAST_RC. Returns 0 iff the exit code equals WANT.
run_capture() {
  local want="$1"; shift
  LAST_OUT="$WORK/.out"
  LAST_ERR="$WORK/.err"
  set +e
  "$@" >"$LAST_OUT" 2>"$LAST_ERR"
  LAST_RC=$?
  set -e
  [ "$LAST_RC" -eq "$want" ]
}

# --------------------------------------------------------------------------- #
# Resource measurement via measure.py
# --------------------------------------------------------------------------- #
# run_measure MEASURE_ARGS... -- CMD...: run a command under measure.py and parse
# its result line into globals:
#   M_RC M_SECS M_PEAK_KB M_TIMED_OUT M_RSS_EXCEEDED   (and M_SKIP=1 if no procfs)
# Pass --out/--err so the test can grep the child's own stdout/stderr.
run_measure() {
  local line rc
  M_SKIP=0
  M_RC=""; M_SECS=""; M_PEAK_KB=""; M_TIMED_OUT=""; M_RSS_EXCEEDED=""
  set +e
  line="$("$PYTHON" "$_STRESS_DIR/measure.py" "$@" 2>"$WORK/.measure.err")"
  rc=$?
  set -e
  if [ "$rc" -eq 77 ]; then
    M_SKIP=1
    return 0
  fi
  local kv
  for kv in $line; do
    case "$kv" in
      rc=*)           M_RC="${kv#rc=}" ;;
      secs=*)         M_SECS="${kv#secs=}" ;;
      peak_kb=*)      M_PEAK_KB="${kv#peak_kb=}" ;;
      timed_out=*)    M_TIMED_OUT="${kv#timed_out=}" ;;
      rss_exceeded=*) M_RSS_EXCEEDED="${kv#rss_exceeded=}" ;;
    esac
  done
}

# Predicates over the last measurement (no verdict printed; caller decides).
rss_below()  { [ -n "$M_PEAK_KB" ] && [ "$M_PEAK_KB" -le "$1" ]; }
secs_below() { awk -v a="$M_SECS" -v b="$1" 'BEGIN{exit !(a+0 < b+0)}'; }
has_traceback() { grep -q 'Traceback (most recent call last)' "$1" 2>/dev/null; }

# mib_kb N -> N MiB expressed in kB (for RSS bounds and cap args).
mib_kb() { echo $(( $1 * 1024 )); }

# --------------------------------------------------------------------------- #
# Resource-availability guards (SKIP cleanly before doing anything destructive)
# --------------------------------------------------------------------------- #
need_cmd() {
  local c
  for c in "$@"; do
    if ! command -v "$c" >/dev/null 2>&1; then
      skip "required command not found: $c"
      return 1
    fi
  done
}

# need_char_dev PATH: skip unless PATH exists and is a character device.
need_char_dev() {
  if [ ! -c "$1" ]; then
    skip "character device not available: $1"
    return 1
  fi
}

# need_free_bytes DIR N: skip unless DIR's filesystem has >= N bytes free.
need_free_bytes() {
  local dir="$1" want="$2" free
  free="$("$PYTHON" -c 'import os,sys; s=os.statvfs(sys.argv[1]); print(s.f_bavail*s.f_frsize)' "$dir" 2>/dev/null)"
  if [ -z "$free" ]; then
    skip "cannot statvfs $dir"
    return 1
  fi
  if [ "$free" -lt "$want" ]; then
    skip "insufficient free space in $dir ($free < $want bytes)"
    return 1
  fi
}

# need_sparse DIR: skip unless DIR's filesystem supports sparse files (a hole-y
# truncate does not allocate real blocks).
need_sparse() {
  local dir="$1" f="$dir/.sparsetest" actual
  if ! truncate -s 64M "$f" 2>/dev/null; then
    rm -f "$f"
    skip "truncate/sparse unsupported in $dir"
    return 1
  fi
  actual="$(stat -c %b "$f" 2>/dev/null)"  # allocated 512B blocks
  rm -f "$f"
  if [ -z "$actual" ] || [ "$actual" -ge 2048 ]; then
    skip "filesystem not sparse-capable in $dir (allocated ${actual:-?} blocks)"
    return 1
  fi
}
