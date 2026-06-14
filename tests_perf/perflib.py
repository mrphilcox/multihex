# Copyright (c) 2026 Philip Cox
# SPDX-License-Identifier: Apache-2.0

"""Shared helpers for the opt-in performance lane (``tests_perf/``).

The lane has two tiers of signal, and these helpers serve both:

* **Deterministic operation-count proxies** are the only *hard* gates. They are
  pure counts (no clock), so they cannot flake and they lock in algorithmic
  complexity: see :class:`CountingBuffer` (counts the byte reads a render issues)
  and the planted-corpus / overlay-doc builders that make match and comparison
  counts exact.

* **Self-normalising timing ratios** are *advisory*. :func:`best_of` takes the
  least-perturbed sample of an operation, and :func:`report_envelope` checks that
  doubling the input keeps the runtime within a generous complexity envelope. A
  ratio of two same-host, same-process measurements is not a host-speed
  threshold, so it stays meaningful across machines -- but it is only *asserted*
  when ``PERF_STRICT`` is set, and even then only when the measured times are
  comfortably above timer resolution.

Everything here is stdlib only and lives entirely test-side: the perf lane never
touches ``src/multihex``.
"""

from __future__ import annotations

import os
import time
from typing import Callable, List, Sequence, Tuple

# A doubling of the input should, for a linear operation, roughly double the
# runtime (ratio ~2.0). The default ceiling sits well above that so ordinary
# host jitter never trips a strict run, while a genuine super-linear regression
# (a doubling that, say, quadruples the time) still stands out.
DEFAULT_CEILING = 3.0

# Below this many seconds a measurement is dominated by timer resolution and
# scheduling noise; ratios built from such samples are not trustworthy, so the
# strict assertion is skipped (the numbers are still printed for the human).
MIN_TRUSTWORTHY_SECONDS = 5e-4


def perf_strict() -> bool:
    """True when ``PERF_STRICT`` is set to a non-empty, non-zero value.

    Off by default: the advisory timing ratios are measured and printed but not
    asserted, so the lane stays green on a loaded or slow host. Set
    ``PERF_STRICT=1`` on an idle machine to turn the envelope checks into gates.
    """
    val = os.environ.get("PERF_STRICT", "").strip().lower()
    return val not in ("", "0", "false", "no", "off")


# --------------------------------------------------------------------------- #
# Deterministic synthetic inputs (seeded, runtime-generated, no committed blobs)
# --------------------------------------------------------------------------- #
def make_binary(size: int, seed: int = 0) -> bytes:
    """Return ``size`` deterministic bytes from a seeded, format-free pattern.

    The pattern is ``(i * 37 + seed) & 0xFF``. 37 is coprime with 256, so each
    aligned 256-byte block is a permutation of all byte values: there are no
    magic numbers, headers, or alignment cues for any code path to exploit, and
    two different seeds differ in every byte. Built by tiling a single 256-byte
    period so multi-megabyte inputs are cheap to generate.
    """
    if size <= 0:
        return b""
    period = bytes(((i * 37 + seed) & 0xFF) for i in range(256))
    whole, rest = divmod(size, 256)
    return period * whole + period[:rest]


def write_binary(path, size: int, seed: int = 0) -> str:
    """Write :func:`make_binary` output to ``path`` and return it as ``str``."""
    with open(path, "wb") as fh:
        fh.write(make_binary(size, seed))
    return str(path)


def plant(
    needle: bytes, count: int, *, gap: int = 64, fill: int = 0x00
) -> Tuple[bytes, List[int]]:
    """Build a corpus with exactly ``count`` non-overlapping copies of ``needle``.

    Each copy is preceded by ``gap`` bytes of ``fill``. ``fill`` must not occur
    in ``needle`` (asserted), so the needle's bytes appear *only* in the planted
    copies and never straddle a copy/fill boundary -- a non-overlapping search
    therefore finds precisely ``count`` matches at the returned offsets. This is
    what makes the search match-count gate deterministic rather than a property
    of the pseudo-random filler.
    """
    if fill in needle:
        raise ValueError("fill byte must not appear in needle")
    block = bytes([fill]) * gap + needle
    data = block * count
    offsets = [gap + i * len(block) for i in range(count)]
    return data, offsets


# --------------------------------------------------------------------------- #
# Operation-count instrumentation
# --------------------------------------------------------------------------- #
class CountingBuffer:
    """A read-only bytes-like buffer that counts single-byte reads.

    Used as a ``HexFile.data`` backing buffer so a render's per-byte
    ``byte_at`` accesses are counted *without modifying core*: ``HexFile.byte_at``
    does ``self.data[offset]`` after a ``len`` bounds check, so every in-bounds
    byte read lands here as an integer ``__getitem__``. Slice reads (used by
    search, not by the render path) are supported but not counted.
    """

    __slots__ = ("_data", "reads")

    def __init__(self, data: bytes) -> None:
        self._data = bytes(data)
        self.reads = 0

    def __len__(self) -> int:
        return len(self._data)

    def __getitem__(self, key):
        if isinstance(key, slice):
            return self._data[key]
        self.reads += 1
        return self._data[key]


# --------------------------------------------------------------------------- #
# Advisory timing
# --------------------------------------------------------------------------- #
def best_of(fn: Callable[[], None], repeats: int = 5) -> float:
    """Run ``fn`` ``repeats`` times after one warm-up; return the minimum seconds.

    The minimum is the sample least perturbed by the scheduler, page faults, or
    background load: noise can only *add* time, so the fastest run is the closest
    estimate of the work's intrinsic cost and the most reproducible signal.
    """
    fn()  # warm up caches / imports; not timed
    best = float("inf")
    for _ in range(max(1, repeats)):
        start = time.perf_counter()
        fn()
        best = min(best, time.perf_counter() - start)
    return best


def report_envelope(
    name: str,
    points: Sequence[Tuple[int, float]],
    *,
    ceiling: float = DEFAULT_CEILING,
) -> str:
    """Print a ``PERF`` line for ``points`` and, under ``PERF_STRICT``, assert.

    ``points`` is ``[(scale, seconds), ...]`` sorted by ascending ``scale`` where
    each scale doubles the previous (N, 2N, 4N, ...). For each doubling the
    ratio ``seconds[i+1] / seconds[i]`` is reported; when ``PERF_STRICT`` is set
    and both samples are above the trustworthy floor, each ratio is asserted to
    be at most ``ceiling`` (catching a super-linear regression). The formatted
    line is returned so callers can also surface it.
    """
    pts = list(points)
    scales = " ".join(f"n={n}:{s:.6f}s" for n, s in pts)
    ratios: List[float] = []
    for (n0, s0), (n1, s1) in zip(pts, pts[1:]):
        ratios.append(s1 / s0 if s0 > 0 else float("inf"))
    ratio_str = " ".join(f"{r:.2f}x" for r in ratios) or "n/a"
    strict = perf_strict()
    line = (
        f"PERF {name} {scales} | doubling_ratios={ratio_str} "
        f"ceiling={ceiling:.1f} strict={int(strict)}"
    )
    print(line)

    if strict:
        for (n0, s0), (n1, s1), ratio in zip(pts, pts[1:], ratios):
            if s0 < MIN_TRUSTWORTHY_SECONDS or s1 < MIN_TRUSTWORTHY_SECONDS:
                # Below timer resolution: report but do not gate on noise.
                continue
            assert ratio <= ceiling, (
                f"{name}: doubling n={n0}->{n1} grew {ratio:.2f}x "
                f"(> {ceiling:.1f}x envelope); s0={s0:.6f} s1={s1:.6f}"
            )
    return line
