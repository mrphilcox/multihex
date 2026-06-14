# Copyright (c) 2026 Philip Cox
# SPDX-License-Identifier: Apache-2.0

"""Minimal performance harness smoke tests.

These tests record timings so the opt-in performance lane has a working shape.
They are not benchmarks and intentionally avoid timing thresholds.
"""

from __future__ import annotations

import time
from pathlib import Path

from multihex.core import HexModel, load_files, name_column_width, render_row_text


def _write_deterministic_binary(path: Path, size: int, salt: int) -> None:
    data = bytes(((index * 37 + salt) & 0xFF) for index in range(size))
    path.write_bytes(data)


def test_core_render_performance_smoke(tmp_path, capsys):
    """Render a moderate deterministic window and report elapsed time."""
    size = 256 * 1024
    left = tmp_path / "left.bin"
    right = tmp_path / "right.bin"
    _write_deterministic_binary(left, size, salt=0x11)
    _write_deterministic_binary(right, size, salt=0x12)

    files = load_files([str(left), str(right)])
    try:
        model = HexModel(files, width=16, length=size)
        name_width = name_column_width(files)

        start = time.perf_counter()
        rendered_lines = []
        for row_index in range(model.row_count):
            row = model.build_row(row_index)
            rendered_lines.extend(
                render_row_text(row, files, name_width=name_width, ascii_on=True)
            )
        elapsed = time.perf_counter() - start
    finally:
        for hex_file in files:
            close = getattr(hex_file.data, "close", None)
            if close is not None:
                close()

    with capsys.disabled():
        print(
            "PERF_SMOKE core_render "
            f"bytes_per_file={size} rows={model.row_count} "
            f"lines={len(rendered_lines)} elapsed_s={elapsed:.6f}"
        )

    assert elapsed >= 0.0
    assert model.row_count == size // 16
    assert rendered_lines
    assert rendered_lines[0] == "0x00000000"
    assert any("!=" in line for line in rendered_lines)
