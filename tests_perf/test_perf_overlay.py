# Copyright (c) 2026 Philip Cox
# SPDX-License-Identifier: Apache-2.0

"""Performance guardrails for overlay range lookup (``OverlayState.covers`` /
``ranges_at``).

Range lookup is a linear scan over the overlay's ranges (no index), so it is
O(nranges) per queried offset -- the one render-adjacent path with a real
complexity smell, since a frontend calls it once per rendered byte. Two tiers
guard it:

* a deterministic **comparison-count gate** -- a single lookup invokes
  ``OverlayRange.covers`` at most ``nranges`` times (== ``nranges`` on a miss,
  short-circuiting on a hit). An accidental nested scan would make this
  O(nranges^2) and fail here, with no dependence on wall-clock speed; and
* an advisory **timing envelope** -- doubling ``nranges`` keeps per-query time
  within the doubling envelope.

The overlay is built as a real ``bintools.layout-overlay`` v1 document and loaded
through ``OverlayState.load`` so the production parse/validate path is exercised.
"""

from __future__ import annotations

import json

import perflib

from multihex.overlay import OverlayRange, OverlayState

SPAN = 8  # per-range stride; ranges are [i*SPAN, i*SPAN + 4), non-overlapping


def _write_overlay(tmp_path, nranges):
    doc = {
        "schema": {"name": "bintools.layout-overlay", "version": 1},
        "name": "perf",
        "ranges": [
            {"path": f"r{i}", "offset": i * SPAN, "length": 4} for i in range(nranges)
        ],
    }
    p = tmp_path / f"overlay_{nranges}.json"
    p.write_text(json.dumps(doc))
    return str(p)


def _miss_offset(nranges):
    # Past every range, so covers()/ranges_at() must scan the whole list.
    return nranges * SPAN + 100


# -- comparison-count gate (deterministic) ----------------------------------- #
def test_lookup_scans_at_most_nranges_comparisons(tmp_path, monkeypatch):
    nranges = 200
    st = OverlayState.load(_write_overlay(tmp_path, nranges))
    assert st.applicable
    assert st.range_count == nranges

    calls = {"n": 0}
    original = OverlayRange.covers

    def counting_covers(self, offset):
        calls["n"] += 1
        return original(self, offset)

    monkeypatch.setattr(OverlayRange, "covers", counting_covers)

    # Miss: covers() scans every range exactly once (one compare per range, no
    # nesting). This is the O(nranges) lock -- a regression to a nested scan
    # would make this ~nranges**2.
    calls["n"] = 0
    assert st.covers(_miss_offset(nranges)) is False
    assert calls["n"] == nranges

    # Hit in the first range: any() short-circuits, so far fewer comparisons.
    calls["n"] = 0
    assert st.covers(0) is True
    assert 1 <= calls["n"] <= nranges

    # ranges_at() has no short-circuit (it collects all hits), so a miss still
    # visits each range exactly once.
    calls["n"] = 0
    assert st.ranges_at(_miss_offset(nranges)) == []
    assert calls["n"] == nranges


# -- advisory timing envelope ------------------------------------------------ #
def test_covers_scaling_over_range_count(capsys, tmp_path):
    base = 256
    queries = 2000
    points = []
    for mult in (1, 2, 4):
        nranges = base * mult
        st = OverlayState.load(_write_overlay(tmp_path, nranges))
        assert st.applicable
        miss = _miss_offset(nranges)

        def run():
            for _ in range(queries):
                st.covers(miss)

        points.append((nranges, perflib.best_of(run, repeats=3)))
    with capsys.disabled():
        perflib.report_envelope("overlay_covers", points)


def test_ranges_at_scaling_over_range_count(capsys, tmp_path):
    base = 256
    queries = 2000
    points = []
    for mult in (1, 2, 4):
        nranges = base * mult
        st = OverlayState.load(_write_overlay(tmp_path, nranges))
        assert st.applicable
        miss = _miss_offset(nranges)

        def run():
            for _ in range(queries):
                st.ranges_at(miss)

        points.append((nranges, perflib.best_of(run, repeats=3)))
    with capsys.disabled():
        perflib.report_envelope("overlay_ranges_at", points)
