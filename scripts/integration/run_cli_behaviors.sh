#!/usr/bin/env bash
# Exercise batch CLI behavior that is too end-to-end for unit tests but broader
# than the smoke script: JSON shape, search contracts, and common failures.
set -euo pipefail
. "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

setup_workdir

"$PYTHON" - "$WORK" <<'PY'
from pathlib import Path
import sys

work = Path(sys.argv[1])
(work / "short.bin").write_bytes(bytes(range(5)))
(work / "long.bin").write_bytes(bytes(range(12)))
(work / "search_a.bin").write_bytes(b"....Content-Type: text/plain....RIFF....RIFF")
(work / "search_b.bin").write_bytes(b"xxxxriffxxxxBBBB")
(work / "plain.bin").write_bytes(bytes([0x00, 0x11, 0x22, 0x33]))
PY

json_check() {
  if run_capture 0 "$PYTHON" -m multihex.cli --json --offset 0x02 --length 0x06 \
      --width 4 --ref 0 "$WORK/short.bin" "$WORK/long.bin" \
      && "$PYTHON" -c '
import json, sys
data = json.load(open(sys.argv[1], encoding="utf-8"))
assert data["offset"] == 2
assert data["length"] == 6
assert data["width"] == 4
assert data["ref"] == 0
assert data["files"] == ["short.bin", "long.bin"]
assert data["paths"] == [sys.argv[2], sys.argv[3]]
assert len(data["rows"]) == 2
assert any(b is None for row in data["rows"] for f in row["files"] for b in f["bytes"])
' "$LAST_OUT" "$WORK/short.bin" "$WORK/long.bin"; then
    pass "cli: JSON output is parseable and preserves shape"
  else
    fail "cli: JSON output shape"
    sed 's/^/    | /' "$LAST_OUT" "$LAST_ERR" 2>/dev/null || true
  fi
}

search_check() {
  local name="$1" token="$2"; shift 2
  if run_capture 0 "$PYTHON" -m multihex.cli "$@" && grep -q -- "$token" "$LAST_OUT"; then
    pass "cli search: $name"
  else
    fail "cli search: $name (exit ${LAST_RC:-?}, wanted '$token')"
    sed 's/^/    | /' "$LAST_OUT" "$LAST_ERR" 2>/dev/null || true
  fi
}

error_check() {
  local name="$1" token="$2"; shift 2
  if run_capture 1 "$PYTHON" -m multihex.cli "$@" && grep -q -- "$token" "$LAST_ERR"; then
    pass "cli error: $name"
  else
    fail "cli error: $name (exit ${LAST_RC:-?}, wanted '$token')"
    sed 's/^/    | /' "$LAST_OUT" "$LAST_ERR" 2>/dev/null || true
  fi
}

argparse_error_check() {
  local name="$1" token="$2"; shift 2
  if run_capture 2 "$PYTHON" -m multihex.cli "$@" && grep -q -- "$token" "$LAST_ERR"; then
    pass "cli error: $name"
  else
    fail "cli error: $name (exit ${LAST_RC:-?}, wanted '$token')"
    sed 's/^/    | /' "$LAST_OUT" "$LAST_ERR" 2>/dev/null || true
  fi
}

json_check

search_check "text match" "offset=0x00000004" \
  --search-text "Content-Type" "$WORK/search_a.bin"
search_check "hex match" "match=52 49 46 46" \
  --search-hex "52 49 46 46" "$WORK/search_a.bin"
search_check "ASCII case-insensitive text" "offset=0x00000004" \
  --search-text "content-type" --search-ignore-case "$WORK/search_a.bin"
search_check "restricted to selected file" "file=1 path=search_b.bin" \
  --search-hex "42 42" --search-file 1 "$WORK/search_a.bin" "$WORK/search_b.bin"
search_check "context renders comparison rows" "0x00000020" \
  --search-hex "52 49 46 46" --search-context 1 "$WORK/search_a.bin"

if run_capture 0 "$PYTHON" -m multihex.cli --search-text absent "$WORK/search_a.bin" \
    && [ ! -s "$LAST_OUT" ] && grep -q "no matches" "$LAST_ERR"; then
  pass "cli search: no match exits zero with stderr note"
else
  fail "cli search: no match contract"
  sed 's/^/    | /' "$LAST_OUT" "$LAST_ERR" 2>/dev/null || true
fi

if run_capture 1 "$PYTHON" -m multihex.cli --search-hex GG "$WORK/search_a.bin" \
    && grep -q 'invalid hex byte "GG"' "$LAST_ERR"; then
  pass "cli search: invalid hex exits non-zero"
else
  fail "cli search: invalid hex error"
  sed 's/^/    | /' "$LAST_OUT" "$LAST_ERR" 2>/dev/null || true
fi

error_check "width zero" "--width must be >= 1" --width 0 "$WORK/plain.bin"
error_check "negative offset" "--offset must be >= 0" --offset -1 "$WORK/plain.bin"
error_check "negative length" "--length must be >= 0" --length -1 "$WORK/plain.bin"
error_check "ref out of range" "--ref 9 out of range" --ref 9 "$WORK/plain.bin"
argparse_error_check "invalid around" "--around expects OFF:N" \
  --around bad "$WORK/plain.bin"
error_check "bad search context" "--search-context must be >= 0" \
  --search-hex 00 --search-context -1 "$WORK/plain.bin"

if run_capture 0 "$PYTHON" -m multihex.cli --help \
    && ! grep -q -- "--config" "$LAST_OUT" \
    && ! grep -q -- "--no-config" "$LAST_OUT"; then
  pass "cli: help stays config-free"
else
  fail "cli: help should not advertise config flags"
  sed 's/^/    | /' "$LAST_OUT" "$LAST_ERR" 2>/dev/null || true
fi

for exe in multihex multihex-tui multihex-gui; do
  if command -v "$exe" >/dev/null 2>&1; then
    if run_capture 0 "$exe" --help && grep -qi "usage" "$LAST_OUT"; then
      pass "entrypoint: $exe --help"
    else
      fail "entrypoint: $exe --help (exit ${LAST_RC:-?})"
      sed 's/^/    | /' "$LAST_OUT" "$LAST_ERR" 2>/dev/null || true
    fi
  else
    skip "entrypoint: $exe not on PATH"
  fi
done

finish
