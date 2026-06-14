# Copyright (c) 2026 Philip Cox
# SPDX-License-Identifier: Apache-2.0

"""Deterministic fixture binaries for multihex characterization/parity tests.

The byte content is fully deterministic so goldens captured from the current
multihex.py stay valid across machines and runs. Files are written with short
basenames and the tools are always invoked with cwd set to the fixture dir, so
no absolute paths leak into stdout (keeps --json "paths"/"files" stable).
"""

import os


def _w(root, name, data):
    with open(os.path.join(root, name), "wb") as fh:
        fh.write(data)


def build_fixtures(root):
    """Write every fixture set under ``root``; return {scenario: [basenames]}.

    The basename order within each scenario is meaningful: it is the argv
    order, which determines the no-ref pivot (column[0]) and --ref indexing.
    """
    root = str(root)
    paths = {}

    # -- equal-length set: 70 bytes each, a handful of divergences ---------- #
    base = bytes((i * 7 + 3) & 0xFF for i in range(70))
    a = bytearray(base)
    b = bytearray(base)
    b[5] ^= 0xFF
    b[20] ^= 0x01
    b[33] ^= 0x80
    c = bytearray(base)
    c[5] ^= 0xFF
    c[40] ^= 0x10
    c[69] ^= 0x55
    _w(root, "eqA", bytes(a))
    _w(root, "eqB", bytes(b))
    _w(root, "eqC", bytes(c))
    paths["equal"] = ["eqA", "eqB", "eqC"]

    # -- single-file scenario: reuses eqA (no comparison partner) ------------- #
    # A lone file has no other column to compare against, so the marker strip is
    # pure "==" noise; the default rendering hides it. This scenario locks that.
    paths["single"] = ["eqA"]

    # -- unequal-length set: 20 / 50 / 100 bytes ---------------------------- #
    long_ = bytes((i * 3 + 1) & 0xFF for i in range(100))
    mid = bytearray(long_[:50])
    mid[10] ^= 0x20
    mid[25] ^= 0x40
    short = bytearray(long_[:20])
    short[2] ^= 0x08
    _w(root, "u_long", long_)
    _w(root, "u_mid", bytes(mid))
    _w(root, "u_short", bytes(short))
    paths["unequal"] = ["u_short", "u_mid", "u_long"]

    # -- all-identical: three copies of 64 bytes ---------------------------- #
    same = bytes((i * 11 + 5) & 0xFF for i in range(64))
    for n in ("idA", "idB", "idC"):
        _w(root, n, same)
    paths["identical"] = ["idA", "idB", "idC"]

    # -- all-differing: every column distinct across files ------------------ #
    _w(root, "dX", bytes([0x00] * 48))
    _w(root, "dY", bytes([0x11] * 48))
    _w(root, "dZ", bytes([0x22] * 48))
    paths["differing"] = ["dX", "dY", "dZ"]

    # -- empty + non-empty (exercises 0-length mmap edge + missing) --------- #
    _w(root, "e_empty", b"")
    _w(root, "e_data", bytes((i * 5 + 9) & 0xFF for i in range(32)))
    paths["empty"] = ["e_empty", "e_data"]

    return paths
