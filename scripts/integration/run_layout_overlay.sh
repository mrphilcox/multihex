#!/usr/bin/env bash
# Copyright (c) 2026 Philip Cox
# SPDX-License-Identifier: Apache-2.0

# Exercise the bintools.layout-overlay v1 validator end-to-end from the CLI.
#
# A generated, deliberately non-canonical corpus (sample.bin + overlay JSONs) is
# fed to `python3 -m multihex.layout_overlay_v1`; each case asserts the exit code
# AND the exact diagnostic code in the output. Runnable from anywhere.
set -euo pipefail
. "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

setup_workdir

VALIDATOR=("$PYTHON" -m multihex.layout_overlay_v1)
GEN="$REPO_ROOT/tests/integration/generators/make_overlay_samples.py"

"$PYTHON" "$GEN" "$WORK" >/dev/null
BIN="$WORK/sample.bin"

# case NAME EXPECTED_RC EXPECTED_TOKEN -- validator args...
case_check() {
  local name="$1" want_rc="$2" token="$3"; shift 3
  [ "$1" = "--" ] && shift
  if run_capture "$want_rc" "${VALIDATOR[@]}" "$@" \
      && grep -q -- "$token" "$LAST_OUT"; then
    pass "layout-overlay: $name (exit $want_rc, '$token')"
  else
    fail "layout-overlay: $name (got exit ${LAST_RC:-?}, wanted $want_rc / '$token')"
    sed 's/^/    | /' "$LAST_OUT" "$LAST_ERR" 2>/dev/null || true
  fi
}

case_check "valid + matching binary"    0 "ok: no diagnostics" -- \
  "$WORK/valid.overlay.json" -b "$BIN"
case_check "minimal structural-only"    0 "ok: no diagnostics" -- \
  "$WORK/minimal.overlay.json"
case_check "unknown type"               1 "unknown-type" -- \
  "$WORK/unknown-type.overlay.json"
case_check "out-of-bounds range"        1 "range-out-of-bounds" -- \
  "$WORK/oob.overlay.json" -b "$BIN"
case_check "raw preview mismatch"       1 "raw-preview-mismatch" -- \
  "$WORK/preview-mismatch.overlay.json" -b "$BIN"
case_check "duplicate path"             2 "duplicate-path" -- \
  "$WORK/duplicate-path.overlay.json"

# --- viewer consumption: multihex --overlay -------------------------------- #
# The batch CLI loads + validates an overlay, prints a summary and diagnostics to
# stderr, and applies the highlight when loadable. Errors are reported but never
# abort the comparison (exit stays 0). Each case asserts the stderr contract.

# Every entry point advertises --overlay in its help.
for mod in multihex.cli multihex.gui multihex.tui; do
  if run_capture 0 "$PYTHON" -m "$mod" --help && grep -q -- "--overlay" "$LAST_OUT"; then
    pass "overlay: $mod --help advertises --overlay"
  else
    # textual/PySide6 may be absent; --help for those still parses args first.
    if [ "$mod" = "multihex.cli" ]; then
      fail "overlay: $mod --help missing --overlay (exit ${LAST_RC:-?})"
    else
      skip "overlay: $mod --help unavailable (optional dep missing?)"
    fi
  fi
done

# overlay_check NAME STREAM TOKEN -- multihex args...
# Runs `multihex.cli ...` (always exit 0) and greps the chosen stream for TOKEN.
overlay_check() {
  local name="$1" stream="$2" token="$3"; shift 3
  [ "$1" = "--" ] && shift
  local file; [ "$stream" = "err" ] && file="$LAST_ERR" || file="$LAST_OUT"
  if run_capture 0 "$PYTHON" -m multihex.cli "$@" \
      && { [ "$stream" = "err" ] && grep -q -- "$token" "$LAST_ERR" \
           || grep -q -- "$token" "$LAST_OUT"; }; then
    pass "overlay: $name"
  else
    fail "overlay: $name (got exit ${LAST_RC:-?}, wanted '$token' on $stream)"
    sed 's/^/    | /' "$LAST_OUT" "$LAST_ERR" 2>/dev/null || true
  fi
}

overlay_check "valid overlay loads cleanly"   err "Loaded layout overlay" -- \
  --overlay "$WORK/valid.overlay.json" "$BIN" "$BIN"
overlay_check "valid overlay renders bytes"   out "4d 48 58" -- \
  --overlay "$WORK/valid.overlay.json" "$BIN" "$BIN"
overlay_check "warning overlay is reported"   err "unknown-type" -- \
  --overlay "$WORK/unknown-type.overlay.json" "$BIN" "$BIN"
overlay_check "error overlay reports + skips" err "duplicate-path" -- \
  --overlay "$WORK/duplicate-path.overlay.json" "$BIN" "$BIN"
overlay_check "error overlay not applied"     err "not applied" -- \
  --overlay "$WORK/duplicate-path.overlay.json" "$BIN" "$BIN"

# No-overlay path is byte-identical to a plain run (overlay never leaks in).
run_capture 0 "$PYTHON" -m multihex.cli "$BIN" "$BIN" && cp "$LAST_OUT" "$WORK/.plain"
run_capture 0 "$PYTHON" -m multihex.cli --overlay "$WORK/valid.overlay.json" \
  "$BIN" "$BIN"
if diff -q "$WORK/.plain" "$LAST_OUT" >/dev/null; then
  pass "overlay: stdout unchanged vs plain run (highlight needs color)"
else
  fail "overlay: stdout differs from plain run without color"
fi

finish
