# Copyright (c) 2026 Philip Cox
# SPDX-License-Identifier: Apache-2.0

"""Tiny deterministic binary fixtures for the UI visual-regression suite.

The shapes are intentionally varied so no single binary format becomes
canonical for the tests: there is no magic field, a deliberately short
(3-byte) identifier, an unaligned payload, printable text mixed with NUL and
high bytes, and a pair that differs in exactly one localized spot. Every blob
is fixed (never random) so snapshots stay byte-stable across runs and
machines.

Two consumption styles are provided:

* in-memory (`hexfile`/`model`) for the Textual TUI, which takes a pre-built
  :class:`core.HexModel`;
* on-disk (`write`) for the PySide6 GUI, which loads file *paths* via
  ``MainWindow.load_paths``.

Both reuse the real ``core.HexFile``/``core.HexModel`` -- the tests never
re-implement model building.
"""

from typing import List, Optional

from multihex import core

# --------------------------------------------------------------------------- #
# Raw byte shapes (deterministic; no format-specific assumptions)
# --------------------------------------------------------------------------- #


def blob_no_magic() -> bytes:
    """48 bytes with no recognizable header/identifier at the front."""
    return bytes((i * 37 + 11) & 0xFF for i in range(48))


def blob_short_id() -> bytes:
    """A short, non-4-byte (3-byte) identifier prefix, then filler."""
    return b"ID\x07" + bytes((i * 13 + 1) & 0xFF for i in range(45))


def blob_unaligned() -> bytes:
    """Filler then a payload that starts at an odd (unaligned) offset."""
    head = bytes((i * 5 + 2) & 0xFF for i in range(7))  # 7 -> next byte is unaligned
    payload = bytes((0xA0 + (i & 0x0F)) for i in range(41))
    return head + payload


def blob_mixed() -> bytes:
    """Printable text interleaved with NUL and high bytes."""
    return b"name=\x00alpha\x80\x81\xffbeta\x00\x00gamma\x7f\x10done\xc3\xa9!!"


def diff_pair() -> tuple:
    """Two equal-length blobs identical except one localized differing byte."""
    base = bytes((i * 7 + 3) & 0xFF for i in range(64))
    other = bytearray(base)
    other[21] ^= 0xFF  # single localized difference -> drives a diff marker
    return bytes(base), bytes(other)


def overlay_target() -> bytes:
    """A 16-byte blob sized to match ``data/overlay_sample.json``.

    The sample overlay's last range runs past the end of this blob on purpose,
    so loading it produces a non-error *warning* (out-of-bounds) while the
    overlay stays applicable -- exercising the status display.
    """
    return bytes((i * 17 + 5) & 0xFF for i in range(16))


# --------------------------------------------------------------------------- #
# In-memory helpers (TUI)
# --------------------------------------------------------------------------- #


def hexfile(name: str, data: bytes) -> "core.HexFile":
    return core.HexFile(name, data)


def model(
    *blobs: bytes,
    width: int = 16,
    ref: Optional[int] = None,
    names: Optional[List[str]] = None,
) -> "core.HexModel":
    """Build a :class:`core.HexModel` from raw byte blobs."""
    if names is None:
        names = [f"sample{i}.bin" for i in range(len(blobs))]
    files = [hexfile(n, d) for n, d in zip(names, blobs)]
    return core.HexModel(files, width=width, ref=ref)


# --------------------------------------------------------------------------- #
# On-disk helpers (GUI)
# --------------------------------------------------------------------------- #


def write(tmp_path, name: str, data: bytes) -> str:
    """Write ``data`` to ``tmp_path/name`` and return the path as a string."""
    p = tmp_path / name
    p.write_bytes(data)
    return str(p)
