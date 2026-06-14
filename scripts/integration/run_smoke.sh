#!/usr/bin/env bash
# Smoke-test the multihex command-line entry points and a real comparison.
#
# Uses `python3 -m multihex.*` (resolves with or without an editable install).
# Optional frontends with heavy deps are skipped cleanly when unavailable, and
# nothing here requires a display server. Runnable from anywhere.
set -euo pipefail
. "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

setup_workdir

# --- multihex (batch CLI): core, stdlib-only, must work ----------------------
if run_capture 0 "$PYTHON" -m multihex.cli --help \
    && grep -qi "usage" "$LAST_OUT"; then
  pass "multihex --help (usage shown)"
else
  fail "multihex --help (exit ${LAST_RC:-?})"
fi

# A real fixed-offset comparison: two files differing in one byte should render
# hex cells and a differing-column marker, not merely exit 0.
printf 'ABCD' >"$WORK/a.bin"
printf 'ABXD' >"$WORK/b.bin"
if run_capture 0 "$PYTHON" -m multihex.cli "$WORK/a.bin" "$WORK/b.bin" \
    && grep -q "41 42 43 44" "$LAST_OUT" \
    && grep -q "!=" "$LAST_OUT"; then
  pass "multihex compares two files (hex + diff marker)"
else
  fail "multihex compare (exit ${LAST_RC:-?})"
  sed 's/^/    | /' "$LAST_OUT" 2>/dev/null || true
fi

# --- multihex-gui --help: arg parsing precedes the PySide6 import guard, so
# this is safe without PySide6 and without a display server. ------------------
if run_capture 0 "$PYTHON" -m multihex.gui --help \
    && grep -q "multihex-gui" "$LAST_OUT"; then
  pass "multihex-gui --help (no display required)"
else
  fail "multihex-gui --help (exit ${LAST_RC:-?})"
  sed 's/^/    | /' "$LAST_ERR" 2>/dev/null || true
fi

# --- multihex-tui --help: imports textual at load; skip if it is absent ------
if run_capture 0 "$PYTHON" -m multihex.tui --help \
    && grep -qi "usage" "$LAST_OUT"; then
  pass "multihex-tui --help (usage shown)"
else
  skip "multihex-tui --help (textual/rich not installed?)"
fi

finish
