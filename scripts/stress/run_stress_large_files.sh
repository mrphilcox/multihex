#!/usr/bin/env bash
# Copyright (c) 2026 Philip Cox
# SPDX-License-Identifier: Apache-2.0

# Stress dimension: multi-GiB files (sparse, so ~no real disk is used).
#
# The display path mmaps with ACCESS_READ and only touches the visible window,
# so opening and navigating to EOF of an 8 GiB file must stay bounded (demand
# paging) -- the core invariant. Search is different: .find() reads every byte
# up to a match, faulting those pages into RSS, so a full scan for an ABSENT
# pattern faults the whole file (peak RSS ~ scanned bytes). That is bounded only
# by where the first match is found -- which --search-max-results can shortcut.
set -uo pipefail
. "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

setup_workdir

gib="$(fast_pick "${STRESS_LARGE_GIB:-8}" 1)"
need_cmd truncate stat || { finish; exit; }
if ! need_sparse "$WORK"; then finish; exit; fi
# Sparse files allocate ~no blocks, but require a tiny margin for metadata.
if ! need_free_bytes "$WORK" $((128 * 1024 * 1024)); then finish; exit; fi

HUGE="$WORK/huge.bin"
truncate -s "${gib}G" "$HUGE"
# Plant the known pattern twice, back to back, at offset 0 for the early-match
# test. Two adjacent copies matter: bounded search probes for one match beyond
# the requested cap to detect truncation, so --search-max-results 1 looks for a
# second match. A single planted copy would force that probe to scan the whole
# file (faulting every page) before giving up; two copies let the cap+1 probe
# satisfy itself within the first eight bytes and stop.
"$PYTHON" -c 'import sys; f=open(sys.argv[1],"r+b"); f.write(bytes.fromhex("DEADBEEFDEADBEEF")); f.close()' "$HUGE"
file_bytes=$((gib * 1024 * 1024 * 1024))

# --- open + navigate a window near EOF: bounded (mmap demand paging) ----------
eof_off=$((file_bytes - 0x40))
CE="$WORK/eof.err"
run_measure --timeout 20 --rss-cap-kb "$(mib_kb 256)" --out /dev/null --err "$CE" \
  -- "$PYTHON" -m multihex.cli --offset "$eof_off" --length 0x40 "$HUGE"
if [ "${M_SKIP}" = "1" ]; then
  skip "EOF window (measure unavailable: no procfs)"
elif [ "$M_RC" = "0" ] && rss_below "$(mib_kb 64)" && secs_below 10 && ! has_traceback "$CE"; then
  pass "${gib}GiB sparse: window near EOF is bounded (peak_kb=$M_PEAK_KB secs=$M_SECS) -- demand paging holds"
else
  fail "${gib}GiB EOF window (rc $M_RC peak_kb=$M_PEAK_KB secs=$M_SECS)"
  sed 's/^/    | /' "$CE" 2>/dev/null || true
fi

# --- navigate a window at a mid offset: also bounded -------------------------
mid_off=$((file_bytes / 2))
CE="$WORK/mid.err"
run_measure --timeout 20 --rss-cap-kb "$(mib_kb 256)" --out /dev/null --err "$CE" \
  -- "$PYTHON" -m multihex.cli --offset "$mid_off" --length 0x100 "$HUGE"
if [ "${M_SKIP}" = "1" ]; then
  skip "mid window (measure unavailable: no procfs)"
elif [ "$M_RC" = "0" ] && rss_below "$(mib_kb 64)" && ! has_traceback "$CE"; then
  pass "${gib}GiB sparse: window at a mid offset is bounded (peak_kb=$M_PEAK_KB)"
else
  fail "${gib}GiB mid window (rc $M_RC peak_kb=$M_PEAK_KB)"
fi

# --- early match + --search-max-results 1: scan stops, RSS stays bounded ------
# The planted DEADBEEF copies sit at offsets 0 and 4, so the cap+1 probe finds
# both within the first eight bytes and stops; almost none of the file is
# faulted. Capture stdout to confirm the early hit at offset 0.
CO="$WORK/early.out"; CE="$WORK/early.err"
run_measure --timeout 20 --rss-cap-kb "$(mib_kb 128)" --out "$CO" --err "$CE" \
  -- "$PYTHON" -m multihex.cli --search-hex "DE AD BE EF" --search-max-results 1 "$HUGE"
if [ "${M_SKIP}" = "1" ]; then
  skip "early match (measure unavailable: no procfs)"
elif [ "$M_RC" = "0" ] && rss_below "$(mib_kb 64)" \
    && grep -q "offset=0x00000000" "$CO" 2>/dev/null && ! has_traceback "$CE"; then
  pass "${gib}GiB sparse: early match with --search-max-results 1 is bounded (peak_kb=$M_PEAK_KB) -- scan stops at the first hit"
else
  fail "${gib}GiB early match (rc $M_RC peak_kb=$M_PEAK_KB)"
  sed 's/^/    | /' "$CE" 2>/dev/null || true
fi

# --- absent full-scan over the huge file: search faults the whole file --------
# Cap well below file size; an absent pattern forces a full scan whose page
# residency climbs with scan position -> the cap trips, confirming search RSS is
# NOT bounded for multi-GiB inputs (distinct from the match-list explosion).
low_cap="$(mib_kb 512)"
CE="$WORK/scan.err"
run_measure --timeout 120 --rss-cap-kb "$low_cap" --out /dev/null --err "$CE" \
  -- "$PYTHON" -m multihex.cli --search-hex "CA FE BA BE" "$HUGE"
if [ "${M_SKIP}" = "1" ]; then
  skip "absent full scan (measure unavailable: no procfs)"
elif [ "$M_RSS_EXCEEDED" = "1" ]; then
  finding "absent-pattern search over a ${gib}GiB file faults pages past a 512MB cap: full-scan RSS ~ scanned bytes, not bounded for multi-GiB inputs (mmap.find, no madvise/streaming)"
elif [ "$M_RC" = "0" ]; then
  characterize "absent-pattern search over ${gib}GiB completed under a 512MB cap: peak_kb=$M_PEAK_KB (host reclaimed faulted pages during the scan)"
else
  fail "absent full scan (rc $M_RC)"
fi

# --- characterize the full-scan slope on a moderate file (completes) ---------
mod_mib="$(fast_pick 512 64)"
truncate -s "${mod_mib}M" "$WORK/mod.bin"
CE="$WORK/mod.err"
run_measure --timeout 60 --rss-cap-kb "$(mib_kb 2048)" --out /dev/null --err "$CE" \
  -- "$PYTHON" -m multihex.cli --search-hex "CA FE BA BE" "$WORK/mod.bin"
if [ "${M_SKIP}" = "1" ]; then
  skip "full-scan slope (measure unavailable: no procfs)"
elif [ "$M_RC" = "0" ] && ! has_traceback "$CE"; then
  characterize "absent-pattern full scan over ${mod_mib}MiB: peak_kb=$M_PEAK_KB (~filesize; confirms search faults each scanned page)"
else
  fail "full-scan slope (rc $M_RC)"
fi

finish
