"""Generate a binary sample and a set of layout-overlay-v1 JSON files.

Usage:
    python3 make_overlay_samples.py OUTDIR

Writes ``sample.bin`` plus one overlay JSON per scenario into OUTDIR. The
integration script (scripts/integration/run_layout_overlay.sh) feeds these to
``python3 -m multihex.layout_overlay_v1`` and asserts the resulting exit code
and diagnostic code for each.

The layout is deliberately *non-canonical* so the corpus does not bake in any
"one true format" shape: a 3-byte (not 4-byte) ASCII magic, a 1-byte field at
an odd offset, a big-endian 16-bit scalar, and a payload at a nonstandard
offset. stdlib only.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

SCHEMA = {"name": "bintools.layout-overlay", "version": 1}

# sample.bin layout (16 bytes), chosen to avoid fixed magic width / endianness /
# alignment assumptions:
#   offset 0  len 3  "MHX"          ascii magic (non-4-byte identifying field)
#   offset 3  len 1  0x02           u8 version at an odd, unaligned offset
#   offset 4  len 2  0x0003         u16be count (big-endian scalar)
#   offset 6  len 1  0xff           u8 flag
#   offset 7  len 9  payload        bytes at a nonstandard offset
SAMPLE = b"MHX" + bytes([0x02]) + bytes([0x00, 0x03]) + bytes([0xFF]) \
    + bytes(range(0x10, 0x19))
assert len(SAMPLE) == 16


def _overlay(ranges: list[dict], **top: object) -> dict:
    doc: dict[str, object] = {"schema": SCHEMA}
    doc.update(top)
    doc["ranges"] = ranges
    return doc


def _valid() -> dict:
    return _overlay(
        [
            {"path": "header.magic", "offset": 0, "length": 3, "kind": "identifier",
             "label": "format magic", "type": "ascii", "raw_hex_preview": "4d4858",
             "decoded": "MHX", "status": "ok"},
            {"path": "header.version", "offset": 3, "length": 1, "label": "version",
             "type": "u8", "raw_hex_preview": "02", "decoded": 2, "status": "ok"},
            {"path": "header.count", "offset": 4, "length": 2, "kind": "count",
             "label": "record count", "type": "u16be", "raw_hex_preview": "0003",
             "decoded": 3, "status": "ok"},
            {"path": "header.flag", "offset": 6, "length": 1, "label": "flag",
             "type": "u8", "raw_hex_preview": "ff"},
            {"path": "payload", "offset": 7, "length": 9, "kind": "payload",
             "label": "payload bytes", "type": "bytes", "status": "unchecked"},
        ],
        name="multihex_sample",
        source_file="sample.bin",
        source_size=len(SAMPLE),
    )


def _minimal() -> dict:
    # Smallest structurally valid overlay: schema + a single labelled range.
    return _overlay([{"offset": 0, "length": 3, "label": "magic"}])


def _unknown_type() -> dict:
    # u24le is not in the recognised type vocabulary -> warning unknown-type.
    return _overlay(
        [{"path": "header.count", "offset": 4, "length": 3, "type": "u24le",
          "label": "count"}]
    )


def _out_of_bounds() -> dict:
    # 14 + 8 = 22 > 16 -> warning range-out-of-bounds (file-aware).
    return _overlay(
        [{"path": "trailer", "offset": 14, "length": 8, "label": "past EOF"}]
    )


def _preview_mismatch() -> dict:
    # raw_hex_preview disagrees with the actual bytes (4d4858) -> warning.
    return _overlay(
        [{"path": "header.magic", "offset": 0, "length": 3, "type": "ascii",
          "raw_hex_preview": "000000", "label": "magic"}]
    )


def _duplicate_path() -> dict:
    # Two ranges share a path -> error duplicate-path (structural).
    return _overlay(
        [
            {"path": "header.magic", "offset": 0, "length": 3, "label": "magic a"},
            {"path": "header.magic", "offset": 4, "length": 2, "label": "magic b"},
        ]
    )


CASES = {
    "valid.overlay.json": _valid,
    "minimal.overlay.json": _minimal,
    "unknown-type.overlay.json": _unknown_type,
    "oob.overlay.json": _out_of_bounds,
    "preview-mismatch.overlay.json": _preview_mismatch,
    "duplicate-path.overlay.json": _duplicate_path,
}


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(__doc__, file=sys.stderr)
        return 2
    outdir = Path(argv[1])
    outdir.mkdir(parents=True, exist_ok=True)

    (outdir / "sample.bin").write_bytes(SAMPLE)
    for name, build in CASES.items():
        (outdir / name).write_text(json.dumps(build(), indent=2) + "\n",
                                   encoding="utf-8")
    print(f"wrote sample.bin + {len(CASES)} overlays to {outdir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
