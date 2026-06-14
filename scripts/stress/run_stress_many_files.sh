#!/usr/bin/env bash
# Copyright (c) 2026 Philip Cox
# SPDX-License-Identifier: Apache-2.0

# Stress dimension: many files at once, and file-descriptor exhaustion.
#
# load_files() opens every file up front (one FD each) and _markers() is O(files)
# per column, so a few hundred files should still render bounded. Past the FD
# limit the failure mode must be a clean OSError exit ("Too many open files"),
# not a crash or traceback.
set -uo pipefail
. "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

setup_workdir
CLI=("$PYTHON" -m multihex.cli)

nfiles="$(fast_pick 512 128)"
"$PYTHON" - "$WORK" "$nfiles" <<'PY'
import os, sys
work, n = sys.argv[1], int(sys.argv[2])
d = os.path.join(work, "many")
os.makedirs(d, exist_ok=True)
for i in range(n):
    with open(os.path.join(d, f"f{i:04d}.bin"), "wb") as fh:
        fh.write(bytes([i % 256]) * 4)
PY
mapfile -t MANY < <(printf '%s\n' "$WORK"/many/f*.bin | sort)

# --- many files render bounded -----------------------------------------------
CE="$WORK/many.err"
run_measure --timeout 60 --rss-cap-kb "$(mib_kb 512)" --out /dev/null --err "$CE" \
  -- "${CLI[@]}" --length 0x10 "${MANY[@]}"
if [ "${M_SKIP}" = "1" ]; then
  skip "many files (measure unavailable: no procfs)"
elif [ "$M_RC" = "0" ] && ! has_traceback "$CE" && rss_below "$(mib_kb 512)"; then
  pass "$nfiles files render bounded (rc 0, peak_kb=$M_PEAK_KB, no traceback)"
else
  fail "$nfiles files (rc $M_RC peak_kb=$M_PEAK_KB)"
  sed 's/^/    | /' "$CE" 2>/dev/null || true
fi

# --- FD exhaustion past a lowered open-file limit ----------------------------
# The RLIMIT_NOFILE is set in the *child* by measure.py (--nofile), so the
# harness shell's own descriptors are never touched. With more files than FDs,
# load_files()'s up-front opens must fail as a clean OSError exit, not a crash.
if [ "${#MANY[@]}" -le 64 ]; then
  skip "FD exhaustion (only ${#MANY[@]} files generated; need > 64)"
else
  CE="$WORK/fd.err"
  run_measure --timeout 30 --nofile 64 --out /dev/null --err "$CE" \
    -- "${CLI[@]}" --length 0x10 "${MANY[@]}"
  if [ "${M_SKIP}" = "1" ]; then
    skip "FD exhaustion (measure unavailable: no procfs)"
  elif [ "$M_RC" = "1" ] \
      && grep -qi "too many open files" "$CE" \
      && ! has_traceback "$CE"; then
    pass "FD exhaustion past RLIMIT_NOFILE=64: clean 'Too many open files' exit (rc 1, no traceback)"
  elif has_traceback "$CE"; then
    finding "FD exhaustion: open() past the FD limit escapes as a traceback (rc $M_RC) instead of a clean OSError exit"
  else
    fail "FD exhaustion: unexpected outcome (rc $M_RC)"
    sed 's/^/    | /' "$CE" 2>/dev/null || true
  fi
fi

finish
