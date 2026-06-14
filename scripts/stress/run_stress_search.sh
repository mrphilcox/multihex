#!/usr/bin/env bash
# Copyright (c) 2026 Philip Cox
# SPDX-License-Identifier: Apache-2.0

# Stress dimension: search under worst-case inputs.
#
# search_files() materializes ALL matches into a list, so searching an all-zero
# file for a single zero byte grows RSS ~linearly with the file (no streaming).
# The designed safety valve is --search-max-results, which MUST stay bounded
# regardless of file content. Case-insensitive text search additionally copies
# the whole file (bytes(f.data).translate), a documented cost we characterize.
# All heavy cases run under a measure.py RSS cap so an explosion is contained.
set -uo pipefail
. "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

setup_workdir

# mk_zero PATH KIB: create a KIB-kibibyte all-zero (sparse) file.
mk_zero() { truncate -s "${2}K" "$1"; }

# --- repeated-byte match explosion: CHARACTERIZE the slope (capped by guard) --
# Every byte of an all-zero file matches the needle 00, so match count == size.
cap_kb="$(mib_kb 1536)"
small_kib="$(fast_pick 256 64)"
large_kib="$(fast_pick 1024 256)"
for kib in "$small_kib" "$large_kib"; do
  mk_zero "$WORK/z.bin" "$kib"
  CE="$WORK/exp.err"
  run_measure --timeout 120 --rss-cap-kb "$cap_kb" --out /dev/null --err "$CE" \
    -- "$PYTHON" -m multihex.cli --search-hex 00 "$WORK/z.bin"
  if [ "${M_SKIP}" = "1" ]; then
    skip "match explosion ${kib}KiB (measure unavailable: no procfs)"
  elif [ "$M_RSS_EXCEEDED" = "1" ]; then
    finding "uncapped 00-search on a ${kib}KiB all-zero file exceeded ${cap_kb}kB: the match list grows ~linearly with file size (no streaming)"
  elif [ "$M_RC" = "0" ]; then
    characterize "uncapped 00-search, ${kib}KiB all-zero -> ~$((kib * 1024)) matches: peak_kb=$M_PEAK_KB secs=$M_SECS (match list ~linear in file size)"
  else
    fail "match explosion ${kib}KiB (rc $M_RC)"
  fi
done

# --- confirm the explosion is real: a larger uncapped search trips the cap ----
boom_mib="$(fast_pick 4 2)"
mk_zero "$WORK/boom.bin" $((boom_mib * 1024))
CE="$WORK/boom.err"
run_measure --timeout 60 --rss-cap-kb "$(mib_kb 768)" --out /dev/null --err "$CE" \
  -- "$PYTHON" -m multihex.cli --search-hex 00 "$WORK/boom.bin"
if [ "${M_SKIP}" = "1" ]; then
  skip "match-explosion confirm (measure unavailable: no procfs)"
elif [ "$M_RSS_EXCEEDED" = "1" ]; then
  finding "uncapped 00-search on a ${boom_mib}MiB all-zero file blows past a 768MB cap (~${boom_mib}M matches): unbounded match list confirmed"
else
  characterize "uncapped 00-search ${boom_mib}MiB completed under the 768MB cap: peak_kb=$M_PEAK_KB (lower slope than expected on this host)"
fi

# --- paired safety valve: --search-max-results stays bounded (HARD) -----------
mk_zero "$WORK/z2.bin" $((boom_mib * 1024))
CE="$WORK/cap.err"
run_measure --timeout 30 --rss-cap-kb "$(mib_kb 256)" --out /dev/null --err "$CE" \
  -- "$PYTHON" -m multihex.cli --search-hex 00 --search-max-results 1000 "$WORK/z2.bin"
if [ "${M_SKIP}" = "1" ]; then
  skip "capped search (measure unavailable: no procfs)"
elif [ "$M_RC" = "0" ] && [ "$M_RSS_EXCEEDED" = "0" ] && rss_below "$(mib_kb 128)" \
    && ! has_traceback "$CE"; then
  pass "capped search (--search-max-results 1000) stays bounded on a ${boom_mib}MiB all-match file (peak_kb=$M_PEAK_KB)"
else
  fail "capped search (rc $M_RC peak_kb=$M_PEAK_KB rss_exceeded=$M_RSS_EXCEEDED)"
fi

# --- case-insensitive text search copies the whole file: CHARACTERIZE --------
# Sparse zeros (size matters, not content); search a pattern that never matches
# so we isolate the bytes(f.data).translate copy cost from any match explosion.
ci_mib="$(fast_pick "${STRESS_SEARCH_MIB:-256}" 32)"
if need_sparse "$WORK" && need_free_bytes "$WORK" $((64 * 1024 * 1024)); then
  truncate -s "${ci_mib}M" "$WORK/ci.bin"
  # case-insensitive (full-file copy)
  CE="$WORK/ci.err"
  run_measure --timeout 120 --rss-cap-kb "$(mib_kb 2048)" --out /dev/null --err "$CE" \
    -- "$PYTHON" -m multihex.cli --search-text ZZZZZZZZ --search-ignore-case "$WORK/ci.bin"
  ci_peak="$M_PEAK_KB"; ci_skip="$M_SKIP"; ci_rc="$M_RC"; ci_exc="$M_RSS_EXCEEDED"
  # case-sensitive baseline (mmap.find, no copy)
  run_measure --timeout 120 --rss-cap-kb "$(mib_kb 2048)" --out /dev/null --err "$WORK/cs.err" \
    -- "$PYTHON" -m multihex.cli --search-text ZZZZZZZZ "$WORK/ci.bin"
  cs_peak="$M_PEAK_KB"
  if [ "$ci_skip" = "1" ] || [ "${M_SKIP}" = "1" ]; then
    skip "case-insensitive copy (measure unavailable: no procfs)"
  elif [ "$ci_exc" = "1" ]; then
    finding "case-insensitive search on a ${ci_mib}MiB file exceeded the 2GiB cap (whole-file copy)"
  elif [ "$ci_rc" = "0" ]; then
    characterize "case-insensitive vs sensitive over ${ci_mib}MiB: insensitive peak_kb=$ci_peak vs sensitive peak_kb=$cs_peak -> the ASCII-fold copies the whole file (~filesize extra)"
  else
    fail "case-insensitive copy (rc $ci_rc)"
  fi
fi

# --- boundary guards (thin: not a re-test of search correctness) -------------
printf '....RIFF' >"$WORK/tail.bin"   # match ends exactly at EOF
if run_capture 0 "$PYTHON" -m multihex.cli --search-hex "52 49 46 46" "$WORK/tail.bin" \
    && grep -q "offset=" "$LAST_OUT" && ! has_traceback "$LAST_ERR"; then
  pass "match at the last byte is found (no off-by-one at EOF)"
else
  fail "match-at-last-byte (rc ${LAST_RC:-?})"
fi

printf 'AB' >"$WORK/tiny.bin"          # pattern longer than the whole file
if run_capture 0 "$PYTHON" -m multihex.cli --search-hex "DE AD BE EF" "$WORK/tiny.bin" \
    && grep -qi "no matches" "$LAST_ERR" && ! has_traceback "$LAST_ERR"; then
  pass "pattern longer than file: clean 'no matches' (rc 0, no traceback)"
else
  fail "pattern-longer-than-file (rc ${LAST_RC:-?})"
fi

finish
