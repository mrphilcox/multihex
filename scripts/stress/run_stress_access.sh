#!/usr/bin/env bash
# Copyright (c) 2026 Philip Cox
# SPDX-License-Identifier: Apache-2.0

# Stress dimension: hostile filesystem access.
#
# Permission and type failures must be clean non-zero exits with a message and
# NO traceback (cli.py catches OSError on stat/open). Two probes target known
# hazards: a FIFO with no writer (open() blocks -> hang) and truncate-after-mmap
# (touching a now-invalid page -> SIGBUS). Both run under measure.py so a hang
# cannot leak and a signal-killed child is reaped; their outcome is a FINDING.
set -uo pipefail
. "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

setup_workdir
CLI=("$PYTHON" -m multihex.cli)

# clean_error_case PATH TOKEN MSG: expect rc 1, a "multihex:" message containing
# TOKEN on stderr, and no traceback.
clean_error_case() {
  local path="$1" token="$2" msg="$3"
  if run_capture 1 "${CLI[@]}" "$path" \
      && grep -q "multihex:" "$LAST_ERR" \
      && grep -qi "$token" "$LAST_ERR" \
      && ! has_traceback "$LAST_ERR"; then
    pass "$msg (clean rc 1 + message, no traceback)"
  else
    fail "$msg (rc ${LAST_RC:-?})"
    sed 's/^/    | /' "$LAST_ERR" 2>/dev/null || true
  fi
}

is_root() { [ "$(id -u)" = "0" ]; }

# --- unreadable file (chmod 000) ---------------------------------------------
if is_root; then
  skip "unreadable file (running as root bypasses permissions)"
else
  printf 'secret' >"$WORK/unreadable.bin"
  chmod 000 "$WORK/unreadable.bin"
  register_cleanup "chmod 0644 '$WORK/unreadable.bin'"
  clean_error_case "$WORK/unreadable.bin" "permission denied" "unreadable file"
fi

# --- file inside an unreadable directory -------------------------------------
if is_root; then
  skip "file in unreadable dir (running as root bypasses permissions)"
else
  mkdir -p "$WORK/noread"
  printf 'x' >"$WORK/noread/f.bin"
  chmod 000 "$WORK/noread"
  register_cleanup "chmod 0755 '$WORK/noread'"
  clean_error_case "$WORK/noread/f.bin" "permission denied" "file in unreadable directory"
fi

# --- a directory passed where a regular file is expected ---------------------
mkdir -p "$WORK/adir"
clean_error_case "$WORK/adir" "is a directory" "directory-as-file"

# --- broken symlink ----------------------------------------------------------
ln -s "$WORK/does-not-exist" "$WORK/broken.lnk"
clean_error_case "$WORK/broken.lnk" "no such file" "broken symlink"

# --- looping symlink ---------------------------------------------------------
ln -s "$WORK/loop.lnk" "$WORK/loop.lnk"
clean_error_case "$WORK/loop.lnk" "too many levels" "looping symlink"

# --- FIFO with no writer: open() blocks (hang hazard) ------------------------
if need_cmd mkfifo; then
  mkfifo "$WORK/fifo"
  register_cleanup "rm -f '$WORK/fifo'"
  timeout_s="$(fast_pick 5 3)"
  CE="$WORK/fifo.err"
  run_measure --timeout "$timeout_s" --err "$CE" -- "${CLI[@]}" "$WORK/fifo"
  if [ "${M_SKIP}" = "1" ]; then
    skip "FIFO no-writer (measure unavailable: no procfs)"
  elif [ "$M_TIMED_OUT" = "1" ]; then
    finding "FIFO with no writer hangs: _open_buffer's open(path,'rb') blocks indefinitely (no regular-file check); killed after ${timeout_s}s"
  elif [ "$M_RC" != "0" ] && ! has_traceback "$CE"; then
    pass "FIFO no-writer: clean non-zero exit, no traceback"
  else
    fail "FIFO no-writer: unexpected outcome (rc $M_RC, timed_out $M_TIMED_OUT)"
  fi
fi

# --- TOCTOU: truncate a file after it is mmap'd, then touch a stale page ------
# Self-contained driver: load via the real core (mmap), shrink the underlying
# file, then access a now-invalid offset. Linux SIGBUSes the process.
big="$WORK/toctou.bin"
"$PYTHON" - "$big" <<'PY'
import sys
open(sys.argv[1], "wb").write(b"A" * 100000)
PY
CE="$WORK/toctou.err"
run_measure --timeout 15 --err "$CE" -- "$PYTHON" -c '
import os, sys
import multihex.core as core
p = sys.argv[1]
f = core.load_files([p])[0]
os.truncate(p, 0)          # underlying file shrinks beneath the live mapping
sys.stdout.write(str(f.byte_at(99999)))  # touch a stale page
' "$big"
if [ "${M_SKIP}" = "1" ]; then
  skip "truncate-after-mmap (measure unavailable: no procfs)"
elif [ "$M_TIMED_OUT" = "1" ]; then
  fail "truncate-after-mmap: child hung (unexpected)"
elif [ "$M_RC" = "-7" ]; then
  finding "truncate-after-mmap -> SIGBUS: a file shrunk beneath a live ACCESS_READ mmap crashes on access (documented mmap hazard; multihex has no guard). rc=$M_RC"
elif [ "$M_RC" = "0" ]; then
  characterize "truncate-after-mmap survived without SIGBUS on this kernel/FS (rc 0)"
else
  finding "truncate-after-mmap: child terminated abnormally (rc=$M_RC)"
fi

finish
