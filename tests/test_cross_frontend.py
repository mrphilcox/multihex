# Copyright (c) 2026 Philip Cox
# SPDX-License-Identifier: Apache-2.0

"""Cross-frontend consistency: the same flag means the same thing everywhere.

These assert agreement at the *core-facing* level (markers, model rows, overlay
applicability) rather than pixels, so they stay robust to per-frontend rendering
differences. They complement the per-frontend suites, which check each frontend
in isolation; here the point is that CLI, TUI, and GUI agree.

GUI parts importorskip PySide6; TUI parts skip without textual.
"""

import json
import os
import struct
import subprocess
import sys

import pytest

import multihex.tui as tui
from multihex.core import HexFile, HexModel, Marker, format_marker
from multihex.overlay import OverlayState

SCHEMA = {"name": "bintools.layout-overlay", "version": 1}


def _triple():
    """Three 64-byte blobs with known, ref-sensitive differences."""
    base = bytes((i * 7 + 3) & 0xFF for i in range(64))
    a = bytearray(base)
    b = bytearray(base)
    b[5] ^= 0xFF
    b[20] ^= 0x01
    c = bytearray(base)
    c[5] ^= 0xFF
    c[40] ^= 0x10
    return bytes(a), bytes(b), bytes(c)


def _write_triple(tmp_path):
    paths = []
    for name, data in zip(("a.bin", "b.bin", "c.bin"), _triple()):
        p = tmp_path / name
        p.write_bytes(data)
        paths.append(str(p))
    return paths


def _hexfiles():
    return [HexFile(n, d) for n, d in zip(("a.bin", "b.bin", "c.bin"), _triple())]


def _core_markers(ref):
    model = HexModel(_hexfiles(), width=16, ref=ref)
    return [
        (model.build_row(i).offset, [format_marker(m) for m in model.build_row(i).markers])
        for i in range(model.row_count)
    ]


def _cli_json_markers(paths, ref, length=None):
    args = ["--json"]
    if ref is not None:
        args += ["--ref", str(ref)]
    if length is not None:
        args += ["--length", str(length)]
    proc = subprocess.run(
        [sys.executable, "-m", "multihex.cli", *args, *paths],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )
    assert proc.returncode == 0, proc.stderr
    doc = json.loads(proc.stdout)
    return [(r["offset"], r["markers"]) for r in doc["rows"]]


def _model_markers(model):
    return [
        (model.build_row(i).offset, [format_marker(m) for m in model.build_row(i).markers])
        for i in range(model.row_count)
    ]


def _struct_mixed():
    """A deliberately unaligned, mixed-width record and a truncated sibling.

    Field widths span u8..u64 and both endiannesses, and every multi-byte field
    starts at an odd/unaligned offset, so nothing here implies a 4-byte/aligned
    canonical shape. The full record is 32 bytes; the sibling is truncated to 24
    bytes so the later fields are *missing* in it (and an overlay range over them
    extends past its EOF).
    """
    full = b"".join([
        bytes([0xA5]),                       # off 0:  u8
        struct.pack("<H", 0x1234),           # off 1:  u16le  (unaligned)
        struct.pack(">H", 0x1234),           # off 3:  u16be
        struct.pack("<I", 0x89ABCDEF),       # off 5:  u32le  (unaligned)
        struct.pack(">I", 0x89ABCDEF),       # off 9:  u32be
        struct.pack("<Q", 0x0102030405060708),  # off 13: u64le (unaligned)
        struct.pack(">Q", 0x0102030405060708),  # off 21: u64be
        bytes([0xDE, 0xAD, 0xBE]),           # off 29: 3 trailing bytes -> EOF 32
    ])
    assert len(full) == 32
    return full, full[:24]


def _struct_overlay_doc():
    # Ranges mirror the field layout, including a u64be that runs [21, 29) and a
    # tail [29, 32) ending exactly at the full file's EOF.
    return {
        "schema": SCHEMA,
        "name": "struct_mixed",
        "source_size": 32,
        "ranges": [
            {"path": "tag", "offset": 0, "length": 1, "type": "u8"},
            {"path": "a", "offset": 1, "length": 2, "type": "u16le"},
            {"path": "b", "offset": 3, "length": 2, "type": "u16be"},
            {"path": "c", "offset": 5, "length": 4, "type": "u32le"},
            {"path": "d", "offset": 9, "length": 4, "type": "u32be"},
            {"path": "e", "offset": 13, "length": 8, "type": "u64le"},
            {"path": "f", "offset": 21, "length": 8, "type": "u64be"},
            {"path": "tail", "offset": 29, "length": 3, "type": "bytes"},
        ],
    }


# --------------------------------------------------------------------------- #
# --ref / --offset / --width produce the same markers in every frontend
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("ref", [None, 0, 1, 2])
def test_ref_markers_agree_cli_and_gui_with_core(tmp_path, ref):
    pytest.importorskip("PySide6")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    import multihex.gui as gui

    paths = _write_triple(tmp_path)
    core = _core_markers(ref)
    assert _cli_json_markers(paths, ref) == core

    QApplication.instance() or QApplication([])
    w = gui.MainWindow(ref=ref)
    assert w.load_paths(paths) is True
    try:
        assert _model_markers(w.model) == core
    finally:
        w.close()


# --------------------------------------------------------------------------- #
# An unaligned, varied-width fixture compares identically across frontends
# --------------------------------------------------------------------------- #


def _write_struct_pair(tmp_path):
    full, short = _struct_mixed()
    paths = []
    for name, data in (("full.bin", full), ("short.bin", short)):
        p = tmp_path / name
        p.write_bytes(data)
        paths.append(str(p))
    return paths


def test_unaligned_varied_width_markers_agree(tmp_path):
    # The truncated sibling makes the trailing fields MISSING; assert the CLI and
    # GUI agree with the core model on the marker grid for this non-4-byte,
    # unaligned layout (so MISSING/diff handling is not frontend-specific).
    #
    # The batch CLI defaults --length to the *shortest* file while the TUI/core
    # derive the window from the *largest* (a documented, intentional divergence).
    # Pin an explicit length so all frontends use the same window and the
    # truncation surfaces as MISSING in every one of them.
    pytest.importorskip("PySide6")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    import multihex.gui as gui

    paths = _write_struct_pair(tmp_path)
    full, short = _struct_mixed()
    files = [HexFile("full.bin", full), HexFile("short.bin", short)]
    window = len(full)  # 32: extends past the 24-byte sibling's EOF
    core = _model_markers(HexModel(files, width=16, length=window))

    assert _cli_json_markers(paths, None, length=window) == core
    # The truncation must actually surface as a MISSING ("--") column.
    missing = format_marker(Marker.MISSING)
    assert any(missing in markers for _, markers in core)

    QApplication.instance() or QApplication([])
    w = gui.MainWindow()
    assert w.load_paths(paths) is True
    try:
        # The GUI/TUI model is largest-file derived; with this fixture that is
        # exactly the explicit window above, so the grids must match.
        assert _model_markers(w.model) == core
    finally:
        w.close()


def test_struct_overlay_past_eof_applicability_agrees(tmp_path):
    # An overlay whose later ranges run past the truncated file's EOF stays
    # applicable (out-of-bounds is a warning), and the shared gate agrees with
    # what the GUI sees.
    pytest.importorskip("PySide6")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    import multihex.gui as gui

    paths = _write_struct_pair(tmp_path)
    full, short = _struct_mixed()
    files = [HexFile("full.bin", full), HexFile("short.bin", short)]
    ov_path = _overlay_files(tmp_path, _struct_overlay_doc())

    state = OverlayState.load(ov_path, files)
    assert state.applicable is True
    assert any("range-out-of-bounds" in line for line in state.diagnostic_lines())

    QApplication.instance() or QApplication([])
    w = gui.MainWindow()
    w.load_paths(paths)
    try:
        w.load_overlay(ov_path)
        assert w.overlay is not None
        assert w.overlay.applicable is True
    finally:
        w.close()


# --------------------------------------------------------------------------- #
# Display-only flags never mutate the compared model, in any frontend
# --------------------------------------------------------------------------- #


def test_cli_markers_and_byte_classes_are_display_only(tmp_path):
    paths = _write_triple(tmp_path)
    base = _cli_json_markers(paths, None)

    def _markers(extra):
        proc = subprocess.run(
            [sys.executable, "-m", "multihex.cli", "--json", *extra, *paths],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        )
        assert proc.returncode == 0, proc.stderr
        doc = json.loads(proc.stdout)
        return [(r["offset"], r["markers"]) for r in doc["rows"]]

    assert _markers(["--markers", "none"]) == base
    assert _markers(["--byte-classes"]) == base


@pytest.mark.skipif(
    tui._TEXTUAL_IMPORT_ERROR is not None, reason="textual not installed"
)
def test_tui_display_toggles_do_not_change_model():
    import asyncio

    async def go():
        model = HexModel(_hexfiles(), width=16)
        app = tui.MultiHexApp(
            model, ascii_on=True, only_diff=False, color_on=True,
            name_mode="basename",
        )
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            before = _model_markers(app.model)
            for key in ("t", "m", "c", "v"):     # byte-classes, markers, color, layout
                await pilot.press(key)
                await pilot.pause()
            assert _model_markers(app.model) == before
            assert app.search_matches == []      # never seeded a search

    asyncio.run(go())


def test_gui_display_toggles_do_not_change_model(tmp_path):
    pytest.importorskip("PySide6")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    import multihex.gui as gui

    paths = _write_triple(tmp_path)
    QApplication.instance() or QApplication([])
    w = gui.MainWindow()
    w.load_paths(paths)
    try:
        before = _model_markers(w.model)
        w.trigger_action("toggle_byte_classes")
        w.trigger_action("cycle_markers")
        w.trigger_action("toggle_color")
        assert _model_markers(w.model) == before
    finally:
        w.close()


# --------------------------------------------------------------------------- #
# Overlay applicability gates highlighting identically across frontends
# --------------------------------------------------------------------------- #


def _overlay_files(tmp_path, doc, name="ov.json"):
    p = tmp_path / name
    p.write_text(json.dumps(doc))
    return str(p)


@pytest.mark.parametrize(
    "doc, expected_applicable",
    [
        (
            {"schema": SCHEMA, "name": "ok",
             "ranges": [{"path": "magic", "offset": 0, "length": 2}]},
            True,
        ),
        (
            {"schema": SCHEMA, "name": "dup",
             "ranges": [
                 {"path": "x", "offset": 0, "length": 2},
                 {"path": "x", "offset": 4, "length": 2},
             ]},
            False,
        ),
    ],
)
def test_overlay_applicability_agrees_across_frontends(tmp_path, doc, expected_applicable):
    pytest.importorskip("PySide6")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    import multihex.gui as gui

    path = _overlay_files(tmp_path, doc)
    files = _hexfiles()

    # The shared gate: OverlayState.load(...).applicable.
    direct = OverlayState.load(path, files).applicable
    assert direct is expected_applicable

    # GUI consults the same gate.
    paths = _write_triple(tmp_path)
    QApplication.instance() or QApplication([])
    w = gui.MainWindow()
    w.load_paths(paths)
    try:
        w.load_overlay(path)
        assert w.overlay is not None
        assert w.overlay.applicable is expected_applicable
    finally:
        w.close()


@pytest.mark.skipif(
    tui._TEXTUAL_IMPORT_ERROR is not None, reason="textual not installed"
)
def test_tui_overlay_applicability_matches_gate(tmp_path):
    import asyncio

    path = _overlay_files(tmp_path, {
        "schema": SCHEMA, "name": "dup",
        "ranges": [
            {"path": "x", "offset": 0, "length": 2},
            {"path": "x", "offset": 4, "length": 2},
        ],
    })
    files = _hexfiles()
    expected = OverlayState.load(path, files).applicable
    assert expected is False

    async def go():
        model = HexModel(_hexfiles(), width=16)
        app = tui.MultiHexApp(
            model, ascii_on=True, only_diff=False, color_on=True,
            name_mode="basename",
        )
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            app._apply_overlay(path)
            await pilot.pause()
            assert app.overlay is not None
            assert app.overlay.applicable is expected

    asyncio.run(go())
