#!/usr/bin/env bash
# Copyright (c) 2026 Philip Cox
# SPDX-License-Identifier: Apache-2.0

# Stress dimension: headless TUI and GUI under extreme geometry + saturated
# overlay. The TUI is driven via Textual's run_test at 1-column / 1-row / very
# wide terminals with rapid navigation/toggle churn; the GUI is rendered
# offscreen (QT_QPA_PLATFORM=offscreen) at extreme window sizes and grabbed to
# confirm it paints. Both run under measure.py so a hang is caught by timeout and
# a runaway by the RSS cap. Skips cleanly when textual / PySide6 are absent.
set -uo pipefail
. "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

setup_workdir
DRIVER_DIR="$(dirname "${BASH_SOURCE[0]}")"
export QT_QPA_PLATFORM="${QT_QPA_PLATFORM:-offscreen}"

# Fixtures: two differing files + a saturated overlay covering the window.
"$PYTHON" - "$WORK" <<'PY'
import os, sys
work = sys.argv[1]
a = bytes((i * 7) % 256 for i in range(4096))
b = bytearray(a)
for off in (100, 2000, 4000):
    b[off] ^= 0xFF
open(os.path.join(work, "a.bin"), "wb").write(a)
open(os.path.join(work, "b.bin"), "wb").write(bytes(b))
PY
nranges="$(fast_pick 2000 500)"
"$PYTHON" "$DRIVER_DIR/gen_overlay.py" ranges -n "$nranges" --out "$WORK/ov.json"

# run_ui_driver LABEL DRIVER.py : run a driver under measure.py and verdict it.
run_ui_driver() {
  local label="$1" driver="$2"
  local CO="$WORK/$label.out" CE="$WORK/$label.err"
  run_measure --timeout 90 --rss-cap-kb "$(mib_kb 1024)" --out "$CO" --err "$CE" \
    -- "$PYTHON" "$DRIVER_DIR/$driver" "$WORK/a.bin" "$WORK/b.bin" "$WORK/ov.json" "$WORK/png"
  if [ "${M_SKIP}" = "1" ]; then
    skip "$label (measure unavailable: no procfs)"
    return
  fi
  if [ "$M_RC" = "77" ]; then
    skip "$label ($(head -1 "$CE" 2>/dev/null))"
  elif [ "$M_TIMED_OUT" = "1" ]; then
    fail "$label: render hung at an extreme geometry (killed after timeout)"
  elif [ "$M_RSS_EXCEEDED" = "1" ]; then
    finding "$label: render blew past the 1GiB cap under a saturated overlay (peak_kb=$M_PEAK_KB)"
  elif [ "$M_RC" = "0" ] && grep -q "^OK " "$CO" 2>/dev/null && ! has_traceback "$CE"; then
    pass "$label: renders all extreme geometries + saturated overlay (peak_kb=$M_PEAK_KB, no exception)"
  else
    fail "$label: rc=$M_RC (no OK / traceback present)"
    sed 's/^/    | /' "$CE" 2>/dev/null | tail -8 || true
  fi
}

run_ui_driver tui ui_tui_driver.py
run_ui_driver gui ui_gui_driver.py

finish
