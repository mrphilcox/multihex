#!/usr/bin/env bash
# Copyright (c) 2026 Philip Cox
# SPDX-License-Identifier: Apache-2.0

# Stress dimension: output and signal pressure on the batch CLI.
#
# A closed downstream pipe (SIGPIPE) must be a clean exit (the CLI catches
# BrokenPipeError). A write to a full destination (/dev/full -> ENOSPC) and an
# interrupt mid-dump (SIGINT) exercise error paths that are NOT BrokenPipeError;
# the defined criterion is a clean non-zero exit with no traceback. A bare
# Traceback is a FINDING (an uncaught write OSError / unhandled KeyboardInterrupt).
set -uo pipefail
. "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

setup_workdir
CLI=("$PYTHON" -m multihex.cli)

# A file large enough that a dump is still in flight when a reader/​signal hits.
big_bytes="$(fast_pick $((4 * 1024 * 1024)) $((256 * 1024)))"
"$PYTHON" - "$WORK/big.bin" "$big_bytes" <<'PY'
import sys
open(sys.argv[1], "wb").write(bytes(int(sys.argv[2])))
PY

# --- SIGPIPE: closed pipe is a clean exit (BrokenPipeError is handled) --------
# --width 1 makes a very long dump so `head -n1` closes the pipe mid-stream.
"${CLI[@]}" --width 1 "$WORK/big.bin" 2>"$WORK/sp.err" | head -n1 >/dev/null
sp_rc="${PIPESTATUS[0]}"
if [ "$sp_rc" -eq 0 ] && ! has_traceback "$WORK/sp.err"; then
  pass "SIGPIPE: closed downstream pipe exits cleanly (rc 0, no traceback)"
else
  fail "SIGPIPE: CLI rc=$sp_rc (expected clean 0)"
  sed 's/^/    | /' "$WORK/sp.err" 2>/dev/null || true
fi

# --- /dev/full as stdout: ENOSPC on write ------------------------------------
if need_char_dev /dev/full; then
  CE="$WORK/full.err"
  run_measure --timeout 30 --out /dev/full --err "$CE" -- "${CLI[@]}" "$WORK/big.bin"
  if [ "${M_SKIP}" = "1" ]; then
    skip "/dev/full stdout (measure unavailable: no procfs)"
  elif [ "$M_TIMED_OUT" = "1" ]; then
    fail "/dev/full stdout: CLI hung writing to a full destination"
  elif has_traceback "$CE"; then
    finding "/dev/full stdout: uncaught write OSError (ENOSPC) prints a traceback (rc $M_RC); only BrokenPipeError is handled in cli.py write path"
  elif [ "$M_RC" != "0" ]; then
    pass "/dev/full stdout: clean non-zero exit, no traceback"
  else
    fail "/dev/full stdout: exited 0 despite ENOSPC (silently dropped output)"
  fi
fi

# --- /dev/full as stderr: the diagnostic-message write path ------------------
# A no-match search prints "no matches" to stderr; if stderr is full the write
# itself can ENOSPC. We cannot observe the (full) stderr, so the criterion is
# weaker: it must terminate, not hang.
if need_char_dev /dev/full; then
  run_measure --timeout 30 --out /dev/null --err /dev/full \
    -- "${CLI[@]}" --search-hex DEADBEEF "$WORK/big.bin"
  if [ "${M_SKIP}" = "1" ]; then
    skip "/dev/full stderr (measure unavailable: no procfs)"
  elif [ "$M_TIMED_OUT" = "1" ]; then
    fail "/dev/full stderr: CLI hung writing a diagnostic to a full stderr"
  else
    pass "/dev/full stderr: diagnostic write to a full stderr terminates (rc $M_RC)"
  fi
fi

# --- SIGINT mid-dump ---------------------------------------------------------
delay="$(fast_pick 0.3 0.1)"
CE="$WORK/si.err"
run_measure --timeout 20 --sigint-after "$delay" --out /dev/null --err "$CE" \
  -- "${CLI[@]}" --width 1 "$WORK/big.bin"
if [ "${M_SKIP}" = "1" ]; then
  skip "SIGINT mid-dump (measure unavailable: no procfs)"
elif [ "$M_TIMED_OUT" = "1" ]; then
  fail "SIGINT mid-dump: CLI did not stop on interrupt (hung)"
elif grep -q 'KeyboardInterrupt' "$CE" 2>/dev/null || has_traceback "$CE"; then
  finding "SIGINT mid-dump: interrupt prints a KeyboardInterrupt traceback (rc $M_RC); no clean Ctrl-C handling in cli.py"
else
  pass "SIGINT mid-dump: clean interrupt, no traceback (rc $M_RC)"
fi

finish
