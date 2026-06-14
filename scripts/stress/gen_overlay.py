#!/usr/bin/env python3
# Copyright (c) 2026 Philip Cox
# SPDX-License-Identifier: Apache-2.0

"""Generate synthetic bintools.layout-overlay v1 JSON for the stress suite.

multihex consumes overlays; it never authors them. These are deliberately
adversarial documents -- huge range counts, heavy overlap, extreme offsets,
pathological JSON nesting -- used only to probe multihex's loader/validator
under scale and hostile structure. Nothing here is committed; the suite writes
to a temp dir at runtime.

Stdlib only. Writes JSON to stdout (or to --out PATH).

Modes:
    ranges      N evenly spaced 16-byte ranges (default N=100000)
    overlap     N ranges all covering the same small window (worst case for
                ranges_at()'s per-call sort)
    extreme     ranges anchored at 2^31, 2^32, 2^63-1 and other boundaries
    nested      a JSON document with deeply nested arrays (default depth
                200000) -- probes recursion handling in json.load
    big         N ranges padded with large string fields to inflate file size
"""

import argparse
import json
import sys

SCHEMA = {"name": "bintools.layout-overlay", "version": 1}

EXTREME_OFFSETS = [
    2 ** 31 - 1,
    2 ** 31,
    2 ** 32 - 1,
    2 ** 32,
    2 ** 63 - 1 - 16,  # leave room for length without exceeding 2^63-1
]


def _doc(ranges, name="stress"):
    return {"schema": dict(SCHEMA), "name": name, "ranges": ranges}


def build_ranges(n, stride=64, length=16):
    return _doc(
        [
            {"path": f"r{i}", "offset": i * stride, "length": length}
            for i in range(n)
        ],
        name=f"ranges-{n}",
    )


def build_overlap(n, base=0x100, length=64):
    return _doc(
        [
            {"path": f"ov{i}", "offset": base, "length": length}
            for i in range(n)
        ],
        name=f"overlap-{n}",
    )


def build_extreme():
    ranges = [
        {"path": f"x{i}", "offset": off, "length": 8}
        for i, off in enumerate(EXTREME_OFFSETS)
    ]
    return _doc(ranges, name="extreme-offsets")


def build_big(n, pad=512):
    filler = "A" * pad
    return _doc(
        [
            {"path": f"b{i}", "offset": i * 64, "length": 16, "note": filler}
            for i in range(n)
        ],
        name=f"big-{n}",
    )


def _emit_nested(out, depth):
    """Stream a deeply nested JSON array without building it in Python.

    Building a depth-200000 structure in Python would itself recurse on
    json.dumps; instead we write the raw brackets so json.load on the *reader*
    side is what gets stressed.
    """
    out.write("[" * depth)
    out.write("0")
    out.write("]" * depth)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="gen_overlay.py")
    parser.add_argument("mode",
                        choices=["ranges", "overlap", "extreme", "nested", "big"])
    parser.add_argument("-n", type=int, default=None,
                        help="count (ranges/overlap/big) or depth (nested)")
    parser.add_argument("--out", default=None, help="write to PATH (default stdout)")
    args = parser.parse_args(argv)

    fh = open(args.out, "w", encoding="utf-8") if args.out else sys.stdout
    try:
        if args.mode == "nested":
            _emit_nested(fh, args.n if args.n is not None else 200000)
        else:
            if args.mode == "ranges":
                doc = build_ranges(args.n if args.n is not None else 100000)
            elif args.mode == "overlap":
                doc = build_overlap(args.n if args.n is not None else 10000)
            elif args.mode == "extreme":
                doc = build_extreme()
            elif args.mode == "big":
                doc = build_big(args.n if args.n is not None else 100000)
            json.dump(doc, fh)
        fh.write("\n")
    finally:
        if fh is not sys.stdout:
            fh.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
