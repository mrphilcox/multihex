#!/usr/bin/env bash
# Copyright (c) 2026 Philip Cox
# SPDX-License-Identifier: Apache-2.0

# Structurally validate the committed example overlays under examples/layouts/.
#
# These examples are intentionally PARTIAL and not tied to any real file, so they
# are validated without a binary (-b): structural-only validation must be clean
# (exit 0). Runnable from anywhere.
set -euo pipefail
. "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

setup_workdir

EX_DIR="$REPO_ROOT/examples/layouts"
if [ ! -d "$EX_DIR" ]; then
  skip "examples/layouts not present"
  finish
  exit $?
fi

shopt -s nullglob
overlays=("$EX_DIR"/*.overlay.json)
if [ "${#overlays[@]}" -eq 0 ]; then
  skip "no *.overlay.json under examples/layouts"
  finish
  exit $?
fi

for ov in "${overlays[@]}"; do
  name="$(basename "$ov")"
  if run_capture 0 "$PYTHON" -m multihex.layout_overlay_v1 "$ov"; then
    pass "example validates structurally: $name"
  else
    fail "example $name (exit ${LAST_RC:-?})"
    sed 's/^/    | /' "$LAST_OUT" "$LAST_ERR" 2>/dev/null || true
  fi
done

finish
