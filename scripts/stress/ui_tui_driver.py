#!/usr/bin/env python3
# Copyright (c) 2026 Philip Cox
# SPDX-License-Identifier: Apache-2.0

"""Headless TUI stress driver for the multihex stress suite.

Drives the real Textual app via ``run_test`` at extreme terminal dimensions and
under a saturated overlay, with rapid navigation and toggles, asserting it
renders without raising. Never starts a real event loop.

Usage:  ui_tui_driver.py FILE_A FILE_B OVERLAY_JSON
Exit:   0 ok | 77 skip (textual not importable) | 1 a render raised
"""

import asyncio
import sys

from multihex import tui
from multihex.core import HexModel, load_files
from multihex.overlay import OverlayState

# Extreme terminal geometries: 1-column, 1-row, very wide, and a normal box.
SIZES = [(1, 24), (80, 1), (400, 24), (200, 50), (80, 24)]
# Immediate, dialog-free keys: navigation + render-affecting toggles.
KEYS = ["down", "pagedown", "end", "home", "c", "t", "v", "m", "pagedown", "up"]


async def _drive(files, overlay):
    for cols, rows in SIZES:
        model = HexModel(files, start_offset=0, width=16, length=None)
        app = tui.MultiHexApp(
            model,
            ascii_on=True,
            only_diff=False,
            color_on=True,
            name_mode="basename",
            overlay=overlay,
        )
        async with app.run_test(size=(cols, rows)) as pilot:
            await pilot.pause()
            # Rapid navigation/toggle churn forces many re-renders per size.
            for _ in range(3):
                for key in KEYS:
                    await pilot.press(key)
            await pilot.pause()
            if app.is_running is False:
                raise RuntimeError(f"app stopped unexpectedly at size {cols}x{rows}")


def main(argv):
    if tui._TEXTUAL_IMPORT_ERROR is not None:
        print(f"SKIP textual unavailable: {tui._TEXTUAL_IMPORT_ERROR}", file=sys.stderr)
        return 77
    if len(argv) < 4:
        print("usage: ui_tui_driver.py FILE_A FILE_B OVERLAY_JSON [OUT_DIR]", file=sys.stderr)
        return 2
    files = load_files([argv[1], argv[2]])
    overlay = OverlayState.load(argv[3], files)
    asyncio.run(_drive(files, overlay))
    print("OK tui rendered all extreme sizes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
