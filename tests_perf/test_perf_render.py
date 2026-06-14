# Copyright (c) 2026 Philip Cox
# SPDX-License-Identifier: Apache-2.0

"""Performance guardrails for the render path (``build_row`` + ``render_row_text``).

The render path is the workhorse: it runs ``row_count`` (= file size / width)
times, each row touching ``ncols x nfiles`` bytes. Two tiers guard it:

* a deterministic **op-count gate** -- a full render reads each in-bounds byte
  exactly once and never touches a missing byte, locking in O(ncols x nfiles)
  per row with no accidental re-scan; and
* an advisory **timing envelope** -- doubling the row count keeps the runtime
  within a generous complexity envelope.

This module replaces the old single-smoke stub and folds its structural checks
into :func:`test_render_structural_smoke`.
"""

from __future__ import annotations

import perflib

from multihex.core import (
    HexFile,
    HexModel,
    load_files,
    name_column_width,
    render_row_text,
)


def _counting_files(sizes):
    """HexFiles backed by CountingBuffers so byte reads are counted."""
    return [
        HexFile(path=f"f{i}.bin", data=perflib.CountingBuffer(perflib.make_binary(n, seed=i)))
        for i, n in enumerate(sizes)
    ]


def _memory_files(size, nfiles):
    """Plain in-memory HexFiles for timing (no disk, no counting overhead)."""
    return [
        HexFile(path=f"f{i}.bin", data=perflib.make_binary(size, seed=i))
        for i in range(nfiles)
    ]


# -- op-count gates (deterministic; never timed) ----------------------------- #
def test_build_row_reads_each_in_bounds_byte_once():
    """A full equal-size render reads every byte exactly once across all files.

    This is the core complexity gate: total reads == file size per file means no
    row re-reads bytes and no per-row work scales with file size. A regression
    that re-scanned (e.g. recomputing markers from the buffer) would inflate the
    count and fail here, with zero dependence on wall-clock speed.
    """
    size = 4096
    width = 16
    files = _counting_files([size, size, size])
    model = HexModel(files, width=width, length=size)

    for idx in range(model.row_count):
        model.build_row(idx)

    for f in files:
        assert f.data.reads == size


def test_build_row_does_not_read_missing_bytes():
    """Bytes past a shorter file's end cost no read (they render as missing).

    With ``length=None`` the window spans the largest file; the smaller file's
    out-of-range offsets are short-circuited by ``byte_at``'s bounds check before
    any indexing, so its read count equals its own size, not the window size.
    """
    big, small = 4096, 1024
    width = 16
    files = _counting_files([big, small])
    model = HexModel(files, width=width)  # length=None -> derives from largest

    for idx in range(model.row_count):
        model.build_row(idx)

    assert files[0].data.reads == big
    assert files[1].data.reads == small


# -- advisory timing envelope ------------------------------------------------ #
def test_render_scaling_is_within_envelope(capsys):
    """Rendering N, 2N, 4N rows stays within the doubling envelope (advisory)."""
    width = 16
    nfiles = 2
    base_rows = 2000
    points = []
    for mult in (1, 2, 4):
        rows = base_rows * mult
        size = rows * width
        files = _memory_files(size, nfiles)
        model = HexModel(files, width=width, length=size)
        name_width = name_column_width(files)

        def render():
            for idx in range(model.row_count):
                row = model.build_row(idx)
                render_row_text(row, files, name_width=name_width, ascii_on=True)

        secs = perflib.best_of(render, repeats=3)
        points.append((rows, secs))

    with capsys.disabled():
        perflib.report_envelope("render_rows", points)


def test_render_filecount_cost_reported(capsys):
    """Report render cost at 2 vs 8 files at a fixed row count (advisory, no gate).

    File count multiplies per-row work; this records the 2->8 (4x) cost so a
    regression in the per-file segment loop is visible in the PERF line, without
    asserting a ratio (4x is not a doubling).
    """
    width = 16
    rows = 4000
    size = rows * width
    points = []
    for nfiles in (2, 8):
        files = _memory_files(size, nfiles)
        model = HexModel(files, width=width, length=size)
        name_width = name_column_width(files)

        def render():
            for idx in range(model.row_count):
                row = model.build_row(idx)
                render_row_text(row, files, name_width=name_width, ascii_on=True)

        secs = perflib.best_of(render, repeats=3)
        points.append((nfiles, secs))

    with capsys.disabled():
        print(
            "PERF render_filecount "
            + " ".join(f"files={n}:{s:.6f}s" for n, s in points)
        )


# -- structural smoke (folded from the former stub) -------------------------- #
def test_render_structural_smoke(tmp_path, capsys):
    """Render a real mmap-backed window and assert the layout is well formed."""
    size = 256 * 1024
    left = perflib.write_binary(tmp_path / "left.bin", size, seed=0x11)
    right = perflib.write_binary(tmp_path / "right.bin", size, seed=0x12)

    files = load_files([left, right])
    try:
        model = HexModel(files, width=16, length=size)
        name_width = name_column_width(files)

        lines = []
        for idx in range(model.row_count):
            row = model.build_row(idx)
            lines.extend(render_row_text(row, files, name_width=name_width, ascii_on=True))
    finally:
        for f in files:
            close = getattr(f.data, "close", None)
            if close is not None:
                close()

    assert model.row_count == size // 16
    assert lines
    assert lines[0].startswith("0x00000000  left.bin")
    # The two seeds differ in every byte, so every column diffs.
    assert any("!=" in line for line in lines)
    # Continuation lines are indented by the offset gutter, not a bare offset.
    gutter = " " * len("0x00000000")
    assert lines[1].startswith(gutter)
    assert all(line.strip() != "0x00000000" for line in lines)

    with capsys.disabled():
        print(
            "PERF render_smoke "
            f"bytes_per_file={size} rows={model.row_count} lines={len(lines)}"
        )
