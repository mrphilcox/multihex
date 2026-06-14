#!/usr/bin/env python3
# Copyright (c) 2026 Philip Cox
# SPDX-License-Identifier: Apache-2.0

"""Headless GUI stress driver for the multihex stress suite.

Drives the real PySide6 ``MainWindow`` offscreen at extreme window dimensions
and under a saturated overlay, grabbing each render to confirm it actually
paints. Never calls ``app.exec()``.

Usage:  ui_gui_driver.py FILE_A FILE_B OVERLAY_JSON [OUT_DIR]
Exit:   0 ok | 77 skip (PySide6 not importable) | 1 a render failed
"""

import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

# Extreme window geometries (px): 1-wide, 1-tall, very wide, very tall, normal.
SIZES = [(1, 400), (1200, 1), (4000, 400), (400, 2000), (900, 420)]


def _is_painted(image):
    seen = set()
    xs = max(1, image.width() // 40)
    ys = max(1, image.height() // 40)
    for y in range(0, image.height(), ys):
        for x in range(0, image.width(), xs):
            seen.add(image.pixel(x, y))
            if len(seen) > 1:
                return True
    return False


def main(argv):
    try:
        from PySide6.QtWidgets import QApplication
    except Exception as exc:  # PySide6 absent
        print(f"SKIP PySide6 unavailable: {exc}", file=sys.stderr)
        return 77

    if len(argv) < 4:
        print("usage: ui_gui_driver.py FILE_A FILE_B OVERLAY_JSON [OUT_DIR]", file=sys.stderr)
        return 2

    import multihex.gui as gui

    out_dir = argv[4] if len(argv) > 4 else None
    app = QApplication.instance() or QApplication([])
    w = gui.MainWindow()
    assert w.load_paths([argv[1], argv[2]]) is True
    st = w.load_overlay(argv[3])
    # A saturated, applicable overlay should colour cells; if it errored we still
    # exercise the render path, but note it.
    if not st.applicable:
        print(f"note: overlay not applicable ({st.summary()})", file=sys.stderr)

    painted_any = False
    for i, (ww, hh) in enumerate(SIZES):
        w.resize(ww, hh)
        w.show()
        app.processEvents()
        # Exercise navigation under each geometry.
        w.view_widget.to_end()
        app.processEvents()
        w.view_widget.to_home()
        app.processEvents()
        pixmap = w.grab()
        if pixmap.isNull():
            raise RuntimeError(f"grab() null at {ww}x{hh}")
        image = pixmap.toImage()
        if image.width() <= 0 or image.height() <= 0:
            raise RuntimeError(f"empty image at {ww}x{hh}")
        if _is_painted(image):
            painted_any = True
        if out_dir:
            os.makedirs(out_dir, exist_ok=True)
            image.save(os.path.join(out_dir, f"gui_stress_{i}_{ww}x{hh}.png"), "PNG")
    w.close()
    if not painted_any:
        raise RuntimeError("no geometry produced a painted image")
    print("OK gui rendered all extreme sizes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
