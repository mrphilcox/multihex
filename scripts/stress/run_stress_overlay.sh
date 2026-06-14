#!/usr/bin/env bash
# Copyright (c) 2026 Philip Cox
# SPDX-License-Identifier: Apache-2.0

# Stress dimension: layout overlays at scale and with hostile structure.
#
# OverlayState.covers() is a linear scan over all ranges, called per rendered
# cell when colour is on, so render cost grows O(ranges) -- characterized via a
# 10x range-count step. Extreme offsets must not overflow. A deeply nested JSON
# document confirms a known gap: OverlayState.load catches only OSError/
# JSONDecodeError, so a RecursionError from json.load escapes as a traceback.
set -uo pipefail
. "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

setup_workdir
CLI=("$PYTHON" -m multihex.cli)
GEN=("$PYTHON" "$(dirname "${BASH_SOURCE[0]}")/gen_overlay.py")

# 256-byte target; --color always so the overlay highlight path (covers()) runs.
"$PYTHON" -c 'import sys; open(sys.argv[1],"wb").write(b"Z"*256)' "$WORK/t.bin"

# --- covers() O(n) render slope: 10x ranges -> ~10x render time ---------------
n_small="$(fast_pick 10000 2000)"
n_large="$(fast_pick 100000 20000)"
declare -A SLOPE
for n in "$n_small" "$n_large"; do
  "${GEN[@]}" ranges -n "$n" --out "$WORK/r$n.json"
  CE="$WORK/r$n.err"
  run_measure --timeout 120 --rss-cap-kb "$(mib_kb 1024)" --out /dev/null --err "$CE" \
    -- "${CLI[@]}" --overlay "$WORK/r$n.json" --color always --length 0x100 "$WORK/t.bin"
  if [ "${M_SKIP}" = "1" ]; then
    skip "overlay $n ranges (measure unavailable: no procfs)"
    continue
  fi
  if [ "$M_RC" = "0" ] && ! has_traceback "$CE"; then
    SLOPE[$n]="$M_SECS"
    characterize "overlay $n ranges, 256-byte window render: secs=$M_SECS peak_kb=$M_PEAK_KB (covers() is O(ranges) per cell)"
  else
    fail "overlay $n ranges render (rc $M_RC)"
    sed 's/^/    | /' "$CE" 2>/dev/null || true
  fi
done
# Confirm the render stayed bounded (completed) at the large count -- a HARD gate
# next to the characterization (it must not hang or OOM under the 1GiB cap).
if [ -n "${SLOPE[$n_large]:-}" ]; then
  pass "overlay $n_large ranges renders bounded (completes under a 1GiB cap, no traceback)"
fi

# --- extreme offsets: no overflow/crash --------------------------------------
"${GEN[@]}" extreme --out "$WORK/x.json"
if run_capture 0 "${CLI[@]}" --overlay "$WORK/x.json" --color always --length 0x20 "$WORK/t.bin" \
    && ! has_traceback "$LAST_ERR" \
    && grep -q "range-out-of-bounds" "$LAST_ERR"; then
  pass "overlay with extreme offsets (2^31/2^32/2^63-1) loads + renders without overflow (out-of-bounds reported as warnings)"
else
  fail "overlay extreme offsets (rc ${LAST_RC:-?})"
  sed 's/^/    | /' "$LAST_ERR" 2>/dev/null || true
fi

# --- heavily overlapping ranges: load + validate + render completes ----------
n_ov="$(fast_pick 10000 2000)"
"${GEN[@]}" overlap -n "$n_ov" --out "$WORK/ov.json"
CE="$WORK/ov.err"
run_measure --timeout 60 --rss-cap-kb "$(mib_kb 512)" --out /dev/null --err "$CE" \
  -- "${CLI[@]}" --overlay "$WORK/ov.json" --color always --length 0x200 "$WORK/t.bin"
if [ "${M_SKIP}" = "1" ]; then
  skip "overlapping ranges (measure unavailable: no procfs)"
elif [ "$M_RC" = "0" ] && ! has_traceback "$CE"; then
  characterize "$n_ov fully-overlapping ranges load + validate + render: secs=$M_SECS peak_kb=$M_PEAK_KB"
else
  fail "overlapping ranges (rc $M_RC)"
fi

# --- deeply nested JSON: RecursionError escapes OverlayState.load (FINDING) ---
depth="$(fast_pick 200000 50000)"
"${GEN[@]}" nested -n "$depth" --out "$WORK/nested.json"
CE="$WORK/nested.err"
run_measure --timeout 30 --rss-cap-kb "$(mib_kb 512)" --out /dev/null --err "$CE" \
  -- "${CLI[@]}" --overlay "$WORK/nested.json" --color always "$WORK/t.bin"
if [ "${M_SKIP}" = "1" ]; then
  skip "nested JSON (measure unavailable: no procfs)"
elif grep -q "RecursionError" "$CE" 2>/dev/null; then
  finding "deeply nested overlay JSON (depth $depth) raises RecursionError: OverlayState.load catches only OSError/JSONDecodeError, so it escapes as a traceback (rc $M_RC)"
elif [ "$M_RC" = "0" ]; then
  fail "nested JSON: expected a RecursionError-mode failure but the overlay loaded cleanly (behaviour changed -- revisit OverlayState.load)"
else
  characterize "nested JSON (depth $depth): non-zero exit rc=$M_RC without a RecursionError trace (json depth handling differs on this build)"
fi

# --- pathologically large overlay file: bounded load -------------------------
n_big="$(fast_pick 100000 10000)"
"${GEN[@]}" big -n "$n_big" --out "$WORK/big.json"
big_mb="$(( $(stat -c %s "$WORK/big.json") / 1024 / 1024 ))"
CE="$WORK/big.err"
run_measure --timeout 60 --rss-cap-kb "$(mib_kb 1024)" --out /dev/null --err "$CE" \
  -- "${CLI[@]}" --overlay "$WORK/big.json" --color always --length 0x40 "$WORK/t.bin"
if [ "${M_SKIP}" = "1" ]; then
  skip "large overlay file (measure unavailable: no procfs)"
elif [ "$M_RC" = "0" ] && ! has_traceback "$CE"; then
  characterize "${big_mb}MB overlay file ($n_big padded ranges) loads bounded: secs=$M_SECS peak_kb=$M_PEAK_KB"
else
  fail "large overlay file (rc $M_RC)"
fi

finish
