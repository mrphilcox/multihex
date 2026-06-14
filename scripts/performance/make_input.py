#!/usr/bin/env python3
# Copyright (c) 2026 Philip Cox
# SPDX-License-Identifier: Apache-2.0

"""Write a deterministic synthetic binary for the performance characterizations.

The shell lane needs multi-megabyte inputs but must not commit binary blobs, so
it generates them at runtime here. The byte pattern matches ``tests_perf``'s
``perflib.make_binary``: ``(i * 37 + seed) & 0xFF``, a format-free permutation
with no magic numbers or alignment cues. A single 256-byte period is tiled so
even large files are cheap to produce.

Usage:
    make_input.py PATH SIZE_BYTES [SEED]
"""

import sys


def main(argv):
    if len(argv) not in (3, 4):
        sys.stderr.write("usage: make_input.py PATH SIZE_BYTES [SEED]\n")
        return 2
    path = argv[1]
    try:
        size = int(argv[2])
        seed = int(argv[3]) if len(argv) == 4 else 0
    except ValueError:
        sys.stderr.write("SIZE_BYTES and SEED must be integers\n")
        return 2
    if size < 0:
        sys.stderr.write("SIZE_BYTES must not be negative\n")
        return 2

    period = bytes(((i * 37 + seed) & 0xFF) for i in range(256))
    whole, rest = divmod(size, 256)
    with open(path, "wb") as fh:
        for _ in range(whole):
            fh.write(period)
        if rest:
            fh.write(period[:rest])
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
