#!/usr/bin/env python3
# Copyright (c) 2026 Philip Cox
# SPDX-License-Identifier: Apache-2.0

"""Smoke/regression tests for the layout-overlay-v1 validator contract.

Dependency-free: run directly with `python3 test_layout_overlay_v1.py`
(exit 0 = all pass, 1 = failures). Also collectible under pytest if dropped
in a tests/ directory.

Contract under test: `ok` means *loadable/usable* (no error-severity
diagnostics), NOT *perfectly clean*. Advisory problems (unknown-type,
unsafe-integer, malformed-hex, range-out-of-bounds, source-* mismatches)
are warnings and leave ok == True.
"""

import hashlib
import sys

from multihex.layout_overlay_v1 import Diagnostic, validate

NAME = "bintools.layout-overlay"


def ok_codes(doc, data=None):
    """Return (ok, sorted_codes). `ok` is loadable, not pristine."""
    r = validate(doc, data)
    return (r.ok, sorted(d.code for d in r.diagnostics))


def severities(doc, data=None):
    """Return {code: severity} to assert on severity, not just presence."""
    r = validate(doc, data)
    return {d.code: d.severity for d in r.diagnostics}


GOOD_MAIN = {
    "schema": {"name": "bintools.layout-overlay", "version": 1},
    "name": "example_layout", "source_file": "sample.bin", "source_size": 20,
    "ranges": [
        {"path": "header.identifier", "offset": 0, "length": 3,
         "kind": "identifier", "label": "format identifier", "type": "ascii",
         "raw_hex_preview": "464d54", "decoded": "FMT",
         "expected_hex": "464d54", "status": "ok"},
        {"path": "header.record_count", "offset": 3, "length": 2,
         "kind": "count", "label": "record count", "type": "u16be",
         "raw_hex_preview": "0002", "decoded": 2, "status": "ok"},
        {"path": "header.padding", "offset": 5, "length": 2, "kind": "padding",
         "label": "alignment padding", "type": "bytes",
         "raw_hex_preview": "0000", "status": "unchecked"},
        {"path": "payload", "offset": 7, "length": 13, "kind": "payload",
         "label": "payload bytes", "type": "bytes", "status": "unchecked"},
    ],
    "diagnostics": [],
}

GOOD_MIN = {
    "schema": {"name": "bintools.layout-overlay", "version": 1},
    "ranges": [
        {"offset": 0, "length": 4, "label": "file marker"},
        {"offset": 4, "length": 4, "label": "version", "type": "u32le"},
        {"offset": 8, "length": 56, "label": "page header", "kind": "reserved"},
    ],
}

# The 20-byte file the main example describes.
MAIN_BYTES = (bytes.fromhex("464d54") + b"\x00\x02" + b"\x00\x00"
              + bytes.fromhex("00112233445566778899aabbcc"))


def _sch(ranges, **top):
    d = {"schema": {"name": "bintools.layout-overlay", "version": 1},
         "ranges": ranges}
    d.update(top)
    return d


_fails = 0


def check(name, got, want):
    global _fails
    if got == want:
        print(f"PASS: {name}")
    else:
        print(f"FAIL: {name}\n   got:  {got}\n   want: {want}")
        _fails += 1


def run():
    # --- clean cases: loadable AND no diagnostics ---
    check("main example clean", ok_codes(GOOD_MAIN), (True, []))
    check("minimal example clean", ok_codes(GOOD_MIN), (True, []))
    check("main example file-aware clean",
          ok_codes(GOOD_MAIN, MAIN_BYTES), (True, []))

    # --- hard structural errors: NOT loadable ---
    check("wrong name", ok_codes(_sch([], schema={"name": "nope", "version": 1})),
          (False, ["wrong-schema-name"]))
    check("bad version",
          ok_codes(_sch([], schema={"name": "bintools.layout-overlay",
                                    "version": 2})),
          (False, ["unsupported-version"]))
    check("missing ranges",
          ok_codes({"schema": {"name": "bintools.layout-overlay",
                               "version": 1}}),
          (False, ["missing-ranges"]))
    check("missing offset+length", ok_codes(_sch([{"label": "x"}])),
          (False, ["bad-length", "bad-offset"]))
    check("duplicate path",
          ok_codes(_sch([{"offset": 0, "length": 1, "path": "a"},
                         {"offset": 1, "length": 1, "path": "a"}])),
          (False, ["duplicate-path"]))
    check("bad path",
          ok_codes(_sch([{"offset": 0, "length": 1, "path": "a..b"}])),
          (False, ["bad-path"]))
    check("bad status",
          ok_codes(_sch([{"offset": 0, "length": 1, "status": "green"}])),
          (False, ["bad-status"]))
    check("bool offset rejected",
          ok_codes(_sch([{"offset": True, "length": 1}])),
          (False, ["bad-offset"]))
    check("zero-length carrying bytes",
          ok_codes(_sch([{"offset": 4, "length": 0,
                          "raw_hex_preview": "00", "type": "u32le"}])),
          (False, ["zero-length-bytes", "zero-length-scalar"]))

    # --- advisory warnings: STILL loadable (ok == True) ---
    check("unknown type loadable",
          ok_codes(_sch([{"offset": 0, "length": 4, "type": "f32le"}])),
          (True, ["unknown-type"]))
    check("malformed hex loadable",
          ok_codes(_sch([{"offset": 0, "length": 2,
                          "raw_hex_preview": "xyz"}])),
          (True, ["malformed-hex"]))
    check("unsafe integer loadable",
          ok_codes(_sch([{"offset": 0, "length": 8, "type": "u64le",
                          "decoded": 2 ** 60}])),
          (True, ["unsafe-integer"]))
    check("preview length mismatch loadable",
          ok_codes(_sch([{"offset": 0, "length": 4,
                          "raw_hex_preview": "00"}])),
          (True, ["preview-length-mismatch"]))

    # --- file-aware warnings: loadable ---
    check("out of bounds loadable", ok_codes(GOOD_MIN, b"\x00" * 10),
          (True, ["range-out-of-bounds"]))
    check("preview mismatch loadable",
          ok_codes(_sch([{"offset": 0, "length": 2,
                          "raw_hex_preview": "dead"}]), b"\xbe\xef"),
          (True, ["raw-preview-mismatch"]))
    check("size+sha mismatch loadable",
          ok_codes(_sch([], source_size=99, source_sha256="0" * 64),
                   b"\x00\x00"),
          (True, ["source-sha256-mismatch", "source-size-mismatch"]))

    # --- severity-aware contract assertions ---
    sevs = severities(_sch([{"offset": 0, "length": 4, "type": "f32le"}]))
    check("unknown-type is a warning", sevs.get("unknown-type"), "warning")
    sevs = severities(_sch([{"offset": 0, "length": 8, "type": "u64le",
                             "decoded": 2 ** 60}]))
    check("unsafe-integer is a warning (SHOULD, not MUST)",
          sevs.get("unsafe-integer"), "warning")
    sevs = severities(_sch([{"offset": 0, "length": 1, "path": "a"},
                            {"offset": 1, "length": 1, "path": "a"}]))
    check("duplicate-path is an error", sevs.get("duplicate-path"), "error")

    # --- malformed top-level document shape ---
    # A non-object root is fatal and short-circuits every other check, so the
    # validator never trusts e.g. a bare array or string as an overlay.
    for label, root in (("array", []), ("string", "x"), ("null", None),
                        ("number", 5), ("bool", True)):
        check(f"non-object root: {label}", ok_codes(root),
              (False, ["not-an-object"]))
    # `diagnostics`, when present, must be an array; a scalar is an error.
    check("non-array diagnostics", ok_codes(_sch([], diagnostics="nope")),
          (False, ["bad-diagnostics"]))

    # --- schema block shape ---
    check("missing schema block", ok_codes({"ranges": []}),
          (False, ["missing-schema"]))
    check("non-object schema block", ok_codes({"schema": [], "ranges": []}),
          (False, ["missing-schema"]))
    # Right name but a non-integer version is rejected; bool is not an int here.
    for label, ver in (("string", "1"), ("float", 1.0), ("bool", True),
                       ("missing", None)):
        check(f"non-integer schema.version: {label}",
              ok_codes(_sch([], schema={"name": NAME, "version": ver})),
              (False, ["missing-schema-version"]))

    # --- top-level field types ---
    check("ranges not an array",
          ok_codes({"schema": {"name": NAME, "version": 1}, "ranges": "nope"}),
          (False, ["bad-ranges"]))
    check("name wrong type", ok_codes(_sch([], name=123)), (False, ["bad-field"]))
    check("source_file wrong type", ok_codes(_sch([], source_file=[])),
          (False, ["bad-field"]))
    check("source_size negative", ok_codes(_sch([], source_size=-1)),
          (False, ["bad-field"]))
    check("source_size bool rejected", ok_codes(_sch([], source_size=True)),
          (False, ["bad-field"]))
    check("source_sha256 not 64 hex", ok_codes(_sch([], source_sha256="zz")),
          (False, ["bad-field"]))
    check("source_sha256 uppercase rejected",
          ok_codes(_sch([], source_sha256="A" * 64)), (False, ["bad-field"]))

    # --- per-range shape ---
    check("range not an object", ok_codes(_sch([5])), (False, ["bad-range"]))
    check("type not a string",
          ok_codes(_sch([{"offset": 0, "length": 1, "type": 123}])),
          (False, ["bad-type"]))
    check("decoded wrong type",
          ok_codes(_sch([{"offset": 0, "length": 4, "decoded": [1, 2]}])),
          (False, ["bad-decoded"]))

    # --- offset/length boundary behaviour (file-aware) ---
    # A range ending exactly at EOF is in bounds; one byte past is not.
    check("range ends exactly at EOF",
          ok_codes(_sch([{"offset": 0, "length": 4}]), b"\x00\x00\x00\x00"),
          (True, []))
    check("range one past EOF",
          ok_codes(_sch([{"offset": 0, "length": 5}]), b"\x00\x00\x00\x00"),
          (True, ["range-out-of-bounds"]))
    check("range-out-of-bounds is a warning",
          severities(_sch([{"offset": 0, "length": 5}]),
                     b"\x00\x00\x00\x00").get("range-out-of-bounds"),
          "warning")
    # File-aware checks must not crash on documents the structural layer already
    # rejected: non-list ranges, non-dict entries, and invalid offsets are all
    # skipped rather than indexed into the binary.
    check("file-aware tolerates non-list ranges",
          ok_codes({"schema": {"name": NAME, "version": 1}, "ranges": "x"},
                   b"\x00\x00"),
          (False, ["bad-ranges"]))
    check("file-aware skips non-dict range",
          ok_codes(_sch([5]), b"\x00\x00"), (False, ["bad-range"]))
    check("file-aware skips invalid offset",
          ok_codes(_sch([{"offset": -1, "length": 1}]), b"\x00\x00"),
          (False, ["bad-offset"]))

    # A correct source_sha256 produces no mismatch (the matching branch).
    check("matching source_sha256 is clean",
          ok_codes(_sch([], source_sha256=hashlib.sha256(b"\x00\x00")
                         .hexdigest()), b"\x00\x00"),
          (True, []))
    # A zero-length range with a non-scalar type and no bytes is fine: the
    # zero-length-scalar rule must not fire for `bytes`.
    check("zero-length non-scalar range is clean",
          ok_codes(_sch([{"offset": 4, "length": 0, "type": "bytes"}])),
          (True, []))
    # The `warnings` accessor mirrors the warning-severity diagnostics.
    check("warnings accessor lists only warnings",
          [d.code for d in
           validate(_sch([{"offset": 0, "length": 4, "type": "f32le"}])).warnings],
          ["unknown-type"])

    # --- diagnostic serialization (the CLI/JSON output shape) ---
    check("to_dict drops absent optional fields",
          Diagnostic("info", "c", "m").to_dict(),
          {"severity": "info", "code": "c", "message": "m"})
    check("to_dict keeps present optional fields",
          Diagnostic("error", "c", "m", path="p", offset=1, length=2).to_dict(),
          {"severity": "error", "code": "c", "message": "m",
           "path": "p", "offset": 1, "length": 2})

    print()
    print("ALL PASS" if _fails == 0 else f"{_fails} FAILED")
    return 1 if _fails else 0


# pytest entry points (one assert per case when collected by pytest)
def test_contract():
    assert run() == 0


if __name__ == "__main__":
    sys.exit(run())
