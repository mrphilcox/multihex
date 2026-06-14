#!/usr/bin/env bash
# Copyright (c) 2026 Philip Cox
# SPDX-License-Identifier: Apache-2.0

# Stress dimension: zero-size and degenerate inputs.
#
# Empty, single-byte, and single-repeated-byte files (the worst case for diff:
# every column SAME), plus character devices passed where a regular file is
# expected. The contract is that none of these crash, hang, or read unboundedly:
# a size-0 device (st_size == 0) must be treated as an empty buffer, not slurped.
set -uo pipefail
. "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

setup_workdir
CLI=("$PYTHON" -m multihex.cli)

# --- empty file --------------------------------------------------------------
: >"$WORK/empty.bin"
if run_capture 0 "${CLI[@]}" "$WORK/empty.bin" && ! has_traceback "$LAST_ERR"; then
  pass "empty file renders cleanly (rc 0, no traceback)"
else
  fail "empty file (rc ${LAST_RC:-?})"
  sed 's/^/    | /' "$LAST_ERR" 2>/dev/null || true
fi

# --- empty vs non-empty: MISSING markers on every column ---------------------
printf 'ABCD' >"$WORK/four.bin"
if run_capture 0 "${CLI[@]}" "$WORK/empty.bin" "$WORK/four.bin" \
    && ! has_traceback "$LAST_ERR"; then
  pass "empty vs non-empty compares (all-missing) without crash"
else
  fail "empty vs non-empty (rc ${LAST_RC:-?})"
fi

# --- one-byte file -----------------------------------------------------------
printf 'Z' >"$WORK/one.bin"
if run_capture 0 "${CLI[@]}" "$WORK/one.bin" && ! has_traceback "$LAST_ERR"; then
  pass "single-byte file renders cleanly"
else
  fail "single-byte file (rc ${LAST_RC:-?})"
fi

# --- single repeated byte, two identical files (worst case for diff) ---------
# Every column is SAME across both files; bound the window so output stays small.
size="$(fast_pick $((1024 * 1024)) 4096)"
"$PYTHON" - "$WORK/rep_a.bin" "$size" <<'PY'
import sys
open(sys.argv[1], "wb").write(b"\x41" * int(sys.argv[2]))
PY
cp "$WORK/rep_a.bin" "$WORK/rep_b.bin"
if run_capture 0 "${CLI[@]}" --length 0x1000 "$WORK/rep_a.bin" "$WORK/rep_b.bin" \
    && ! has_traceback "$LAST_ERR" \
    && grep -q "41 41 41 41" "$LAST_OUT"; then
  pass "single-repeated-byte identical files (all-SAME) render"
else
  fail "single-repeated-byte files (rc ${LAST_RC:-?})"
fi

# --- single repeated byte differing in exactly one position ------------------
"$PYTHON" - "$WORK/rep_c.bin" "$size" <<'PY'
import sys
b = bytearray(b"\x41" * int(sys.argv[2]))
b[10] = 0x42
open(sys.argv[1], "wb").write(b)
PY
if run_capture 0 "${CLI[@]}" --length 0x20 "$WORK/rep_a.bin" "$WORK/rep_c.bin" \
    && ! has_traceback "$LAST_ERR" \
    && grep -q "!=" "$LAST_OUT"; then
  pass "single-differing-byte in a repeated field marks a diff column"
else
  fail "single-differing-byte (rc ${LAST_RC:-?})"
fi

# --- /dev/zero: size-0 char device must be treated as empty, not slurped -----
# Guard with a hard timeout: an infinite read would trip it (would be a FINDING).
if need_char_dev /dev/zero; then
  CO="$WORK/zero.out"; CE="$WORK/zero.err"
  run_measure --timeout 10 --rss-cap-kb "$(mib_kb 256)" --out "$CO" --err "$CE" \
    -- "${CLI[@]}" /dev/zero
  if [ "${M_SKIP}" = "1" ]; then
    skip "/dev/zero (measure unavailable: no procfs)"
  elif [ "$M_TIMED_OUT" = "1" ] || [ "$M_RSS_EXCEEDED" = "1" ]; then
    finding "/dev/zero is read unboundedly (timed_out=$M_TIMED_OUT rss_exceeded=$M_RSS_EXCEEDED)"
  elif [ "$M_RC" = "0" ] && ! has_traceback "$CE"; then
    pass "/dev/zero treated as empty (rc 0, bounded, no traceback)"
  else
    fail "/dev/zero (rc $M_RC)"
    sed 's/^/    | /' "$CE" 2>/dev/null || true
  fi
fi

# --- /dev/null: size-0, trivially empty --------------------------------------
if need_char_dev /dev/null; then
  if run_capture 0 "${CLI[@]}" /dev/null && ! has_traceback "$LAST_ERR"; then
    pass "/dev/null treated as empty (rc 0, no traceback)"
  else
    fail "/dev/null (rc ${LAST_RC:-?})"
  fi
fi

finish
