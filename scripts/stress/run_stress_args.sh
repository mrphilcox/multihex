#!/usr/bin/env bash
# Copyright (c) 2026 Philip Cox
# SPDX-License-Identifier: Apache-2.0

# Stress dimension: argument extremes.
#
# Offsets at the 2^31 / 2^32 / 2^63-1 boundaries must render an all-missing
# window without overflow or crash (Python ints are unbounded; byte_at returns
# None past EOF). --width and --length have no upper bound in the CLI: huge
# values are characterized (they complete but cost memory/time proportional to
# the value, not the file), each paired with the bounded variant that holds.
set -uo pipefail
. "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

setup_workdir
CLI=("$PYTHON" -m multihex.cli)

printf 'ABCDEFGHIJKLMNOP' >"$WORK/f.bin"

# --- extreme start offsets: all-missing window, no overflow/crash ------------
for off in 0x7fffffff 0x80000000 0xffffffff 0x100000000 0x7fffffffffffffff; do
  if run_capture 0 "${CLI[@]}" --offset "$off" --length 0x40 "$WORK/f.bin" \
      && ! has_traceback "$LAST_ERR" \
      && grep -q -e '--' "$LAST_OUT"; then
    pass "extreme offset $off renders all-missing window (rc 0, no overflow)"
  else
    fail "extreme offset $off (rc ${LAST_RC:-?})"
    sed 's/^/    | /' "$LAST_ERR" 2>/dev/null || true
  fi
done

# --- extreme offset in --json (numbers must serialize, not crash) ------------
if run_capture 0 "${CLI[@]}" --offset 0x7fffffffffffffff --length 0x20 --json "$WORK/f.bin" \
    && ! has_traceback "$LAST_ERR" \
    && grep -q '"offset": 9223372036854775807' "$LAST_OUT"; then
  pass "extreme offset serializes in --json without overflow"
else
  fail "extreme offset --json (rc ${LAST_RC:-?})"
fi

# --- huge --width: one row, no upper bound (CHAR) ----------------------------
wide="$(fast_pick 2000000 100000)"
CE="$WORK/wide.err"
run_measure --timeout 60 --rss-cap-kb "$(mib_kb 1024)" --out /dev/null --err "$CE" \
  -- "${CLI[@]}" --width "$wide" --length "$wide" "$WORK/f.bin"
if [ "${M_SKIP}" = "1" ]; then
  skip "huge --width (measure unavailable: no procfs)"
elif [ "$M_RSS_EXCEEDED" = "1" ] || [ "$M_TIMED_OUT" = "1" ]; then
  finding "huge --width=$wide blew past guardrail (peak_kb=$M_PEAK_KB timed_out=$M_TIMED_OUT); no upper bound on --width"
elif [ "$M_RC" = "0" ] && ! has_traceback "$CE"; then
  characterize "huge --width=$wide builds a single wide row: peak_kb=$M_PEAK_KB secs=$M_SECS (no upper bound on --width)"
else
  fail "huge --width=$wide (rc $M_RC)"
  sed 's/^/    | /' "$CE" 2>/dev/null || true
fi

# --- huge --length with NO --limit-rows: render work scales with --length ----
# main() iterates range(model.row_count) and build_row for every row even on the
# default path, so a huge --length over a tiny file is O(length/width) work.
len="$(fast_pick 0x300000 0x4000)"   # 3 MiB -> ~196k rows  (fast: 16 KiB -> 1k)
CE="$WORK/len.err"
run_measure --timeout 120 --rss-cap-kb "$(mib_kb 512)" --out /dev/null --err "$CE" \
  -- "${CLI[@]}" --length "$len" "$WORK/f.bin"
if [ "${M_SKIP}" = "1" ]; then
  skip "huge --length (measure unavailable: no procfs)"
elif [ "$M_TIMED_OUT" = "1" ] || [ "$M_RSS_EXCEEDED" = "1" ]; then
  finding "huge --length=$len did not complete under guardrail (secs=$M_SECS peak_kb=$M_PEAK_KB); render work scales with --length, not file size"
elif [ "$M_RC" = "0" ] && ! has_traceback "$CE"; then
  characterize "huge --length=$len over a 16-byte file builds every row: secs=$M_SECS peak_kb=$M_PEAK_KB (O(length/width); no --limit-rows guard)"
else
  fail "huge --length=$len (rc $M_RC)"
fi

# --- paired bounded variant: same huge --length WITH --limit-rows is fast ----
CE="$WORK/lenlim.err"
run_measure --timeout 15 --out /dev/null --err "$CE" \
  -- "${CLI[@]}" --length "$len" --limit-rows 16 "$WORK/f.bin"
if [ "${M_SKIP}" = "1" ]; then
  skip "huge --length + --limit-rows (measure unavailable: no procfs)"
elif [ "$M_RC" = "0" ] && secs_below 5 && ! has_traceback "$CE"; then
  pass "huge --length + --limit-rows 16 is bounded (secs=$M_SECS): the limit stops the row loop early"
else
  fail "huge --length + --limit-rows (rc $M_RC secs=$M_SECS)"
fi

finish
