# shellcheck shell=bash
# Copyright (c) 2026 Philip Cox
# SPDX-License-Identifier: Apache-2.0

# Shared helpers for the multihex integration scripts.
#
# Source this file; do not execute it:
#     . "$(dirname "$0")/lib.sh"
#
# It defines PASS/FAIL/SKIP reporting, a self-cleaning temp dir (honouring
# KEEP_WORK=1), and small assertion helpers. REPO_ROOT is resolved from this
# file's location so the scripts work from any CWD, and src/ is put on
# PYTHONPATH so `python3 -m multihex.*` resolves without an editable install
# (the core and the layout-overlay validator are stdlib-only).

# Resolve the repository root: this file lives in scripts/integration/.
_LIB_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$_LIB_DIR/../.." && pwd)"

PYTHON="${PYTHON:-python3}"
export PYTHONPATH="$REPO_ROOT/src${PYTHONPATH:+:$PYTHONPATH}"

PASS_COUNT=0
FAIL_COUNT=0
SKIP_COUNT=0

pass() { PASS_COUNT=$((PASS_COUNT + 1)); printf 'PASS: %s\n' "$*"; }
fail() { FAIL_COUNT=$((FAIL_COUNT + 1)); printf 'FAIL: %s\n' "$*"; }
skip() { SKIP_COUNT=$((SKIP_COUNT + 1)); printf 'SKIP: %s\n' "$*"; }

# setup_workdir: create $WORK (a fresh mktemp -d) and arrange cleanup on exit.
# Set KEEP_WORK=1 to preserve it for debugging (the path is printed instead).
setup_workdir() {
  WORK="$(mktemp -d "${TMPDIR:-/tmp}/multihex-it.XXXXXX")"
  if [ "${KEEP_WORK:-0}" = "1" ]; then
    trap 'printf "KEEP_WORK=1: left work dir at %s\n" "$WORK"' EXIT
  else
    trap 'rm -rf "$WORK"' EXIT
  fi
}

# finish: print a one-line summary and exit non-zero if anything failed.
finish() {
  printf -- '---- %d passed, %d failed, %d skipped\n' \
    "$PASS_COUNT" "$FAIL_COUNT" "$SKIP_COUNT"
  [ "$FAIL_COUNT" -eq 0 ]
}

# run_capture WANT CMD...: run CMD, capturing stdout to $LAST_OUT and stderr to
# $LAST_ERR, and set $LAST_RC. Returns 0 when the exit code equals WANT. Callers
# pair this with a grep over "$LAST_OUT" so each case asserts both the exit code
# and an output contract, not just the status.
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
