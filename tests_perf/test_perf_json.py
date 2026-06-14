# Copyright (c) 2026 Philip Cox
# SPDX-License-Identifier: Apache-2.0

"""Performance guardrail for JSON row building (``cli.build_json_row``).

``--json`` materialises every row before serialising, so its cost is
``row_count x ncols x nfiles`` and it holds all rows in memory at once. The
per-row builder is the in-process part and gets an advisory timing envelope here
(doubling the row count stays within the doubling envelope). Whole-file JSON
*memory* is deliberately not asserted in-process -- portable RSS gating is
unreliable -- and is instead characterised as a subprocess peak-RSS measurement
in ``scripts/performance/run_all.sh``.

``cli.build_json_row`` is imported directly: it is a pure ``(Row, names) -> dict``
function with no frontend state, so it needs no subprocess to measure scaling.
"""

from __future__ import annotations

import perflib

from multihex.cli import build_json_row
from multihex.core import HexFile, HexModel


def _model_and_names(rows, width=16, nfiles=2):
    size = rows * width
    files = [
        HexFile(path=f"f{i}.bin", data=perflib.make_binary(size, seed=i))
        for i in range(nfiles)
    ]
    model = HexModel(files, width=width, length=size)
    names = [f.display_name() for f in files]
    return model, names


def test_build_json_row_shape_is_sane():
    """A light correctness anchor so the timing test also exercises real output."""
    model, names = _model_and_names(rows=4)
    row = model.build_row(0)
    obj = build_json_row(row, names)
    assert set(obj) == {"offset", "markers", "files"}
    assert obj["offset"] == 0
    assert [f["name"] for f in obj["files"]] == names
    assert len(obj["markers"]) == 16
    assert all(set(f) == {"name", "bytes", "ascii"} for f in obj["files"])


def test_json_row_build_scaling_within_envelope(capsys):
    base_rows = 2000
    points = []
    for mult in (1, 2, 4):
        rows = base_rows * mult
        model, names = _model_and_names(rows)
        built = [model.build_row(i) for i in range(model.row_count)]

        def run():
            for row in built:
                build_json_row(row, names)

        points.append((rows, perflib.best_of(run, repeats=3)))
    with capsys.disabled():
        perflib.report_envelope("json_rows", points)
