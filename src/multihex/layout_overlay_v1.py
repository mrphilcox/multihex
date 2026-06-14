#!/usr/bin/env python3
# Copyright (c) 2026 Philip Cox
# SPDX-License-Identifier: Apache-2.0

"""Validator for the bintools.layout-overlay v1 schema.

Stdlib only. Two layers of checking:

  structural  - JSON shape, required fields, vocabularies, bounds, hex,
                path uniqueness, zero-length rules. Needs only the overlay.
  file-aware  - out-of-bounds ranges, source_size / source_sha256 /
                raw_hex_preview mismatches. Runs only when a binary is given.

Both layers emit diagnostics in the schema's own diagnostic shape
(severity / message / code / path / offset / length), so the validator's
output is itself a layout-overlay diagnostics array.

Severity policy
---------------
A structural problem that makes a range or the document unusable is an
`error`. Advisory or file-relative mismatches (source_size, source_sha256,
raw_hex_preview, out-of-bounds) are `warning` by default, matching the spec's
"diagnostic, not a hard load failure" stance. The deliberately-deferred
questions (raw-preview-mismatch and out-of-bounds severity) are isolated to
the SEVERITY table below so they are one edit away from changing.

`Result.ok` means *loadable/usable* (no error-severity diagnostics), NOT
*perfectly clean*. A document with only warnings (unknown-type, unsafe-integer,
malformed-hex, range-out-of-bounds, source-* mismatches) is `ok`. unsafe-integer
is a SHOULD in the spec, so it is a warning and never flips `ok`. duplicate-path
is an `error` because the validator acts as a producer-side gate, even though a
consumer may choose to load past it.

Exit codes (CLI): 0 = clean, 1 = warnings only, 2 = errors present,
3 = the validator itself could not run (bad args / unreadable file).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from dataclasses import dataclass, field
from typing import Any, Optional

SCHEMA_NAME = "bintools.layout-overlay"
SCHEMA_VERSION = 1

# Closed vocabularies.
KNOWN_TYPES = frozenset(
    {"u8", "u16le", "u16be", "u32le", "u32be", "u64le", "u64be",
     "bytes", "ascii", "utf8"}
)
SCALAR_TYPES = frozenset(
    {"u8", "u16le", "u16be", "u32le", "u32be", "u64le", "u64be"}
)
STATUS_VALUES = frozenset({"ok", "warning", "error", "unchecked"})
SEVERITY_VALUES = frozenset({"info", "warning", "error"})

# Single place to tune the two deferred-severity decisions.
SEVERITY = {
    "range-out-of-bounds": "warning",
    "raw-preview-mismatch": "warning",
    "source-size-mismatch": "warning",
    "source-sha256-mismatch": "warning",
}

_HEX_RE = re.compile(r"\A(?:[0-9a-f]{2})*\Z")
# path: dot-separated segments, each an identifier with an optional [n] index.
_PATH_SEG = r"[A-Za-z_][A-Za-z0-9_]*(?:\[\d+\])?"
_PATH_RE = re.compile(rf"\A{_PATH_SEG}(?:\.{_PATH_SEG})*\Z")

JSON_INT_SAFE_MAX = (1 << 53) - 1


@dataclass
class Diagnostic:
    severity: str
    code: str
    message: str
    path: Optional[str] = None
    offset: Optional[int] = None
    length: Optional[int] = None

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "severity": self.severity,
            "code": self.code,
            "message": self.message,
        }
        if self.path is not None:
            d["path"] = self.path
        if self.offset is not None:
            d["offset"] = self.offset
        if self.length is not None:
            d["length"] = self.length
        return d


@dataclass
class Result:
    diagnostics: list[Diagnostic] = field(default_factory=list)

    def add(self, *a: Any, **k: Any) -> None:
        self.diagnostics.append(Diagnostic(*a, **k))

    @property
    def errors(self) -> list[Diagnostic]:
        return [d for d in self.diagnostics if d.severity == "error"]

    @property
    def warnings(self) -> list[Diagnostic]:
        return [d for d in self.diagnostics if d.severity == "warning"]

    @property
    def ok(self) -> bool:
        return not self.errors


def _is_int(v: Any) -> bool:
    # bool is a subclass of int in Python; reject it explicitly.
    return isinstance(v, int) and not isinstance(v, bool)


def _bad_hex(s: Any) -> bool:
    return not isinstance(s, str) or _HEX_RE.match(s) is None


def validate_structural(doc: Any) -> Result:
    """Check everything that needs only the overlay document."""
    r = Result()

    if not isinstance(doc, dict):
        r.add("error", "not-an-object", "Top-level value must be a JSON object.")
        return r

    _check_schema_block(doc, r)
    # If the schema block is wrong we have already said so; keep going so the
    # author sees structural problems too, but a wrong name/version is fatal
    # for actually trusting the rest.

    _check_top_level(doc, r)

    ranges = doc.get("ranges")
    if isinstance(ranges, list):
        _check_ranges(ranges, r)

    diags = doc.get("diagnostics")
    if diags is not None and not isinstance(diags, list):
        r.add("error", "bad-diagnostics",
              "`diagnostics` must be an array when present.")

    return r


def _check_schema_block(doc: dict, r: Result) -> None:
    schema = doc.get("schema")
    if not isinstance(schema, dict):
        r.add("error", "missing-schema",
              "Missing or non-object required field `schema`.")
        return
    name = schema.get("name")
    if name != SCHEMA_NAME:
        # Wrong name => not our file. Check this before version.
        r.add("error", "wrong-schema-name",
              f"schema.name must be {SCHEMA_NAME!r}; got {name!r}.")
        return
    version = schema.get("version")
    if not _is_int(version):
        r.add("error", "missing-schema-version",
              "schema.version must be an integer.")
    elif version != SCHEMA_VERSION:
        r.add("error", "unsupported-version",
              f"Unsupported schema.version {version}; this validator "
              f"handles version {SCHEMA_VERSION}.")


def _check_top_level(doc: dict, r: Result) -> None:
    if "ranges" not in doc:
        r.add("error", "missing-ranges", "Missing required field `ranges`.")
    elif not isinstance(doc["ranges"], list):
        r.add("error", "bad-ranges", "`ranges` must be an array.")

    for key, typ, label in (
        ("name", str, "string"),
        ("source_file", str, "string"),
        ("source_size", int, "integer"),
        ("source_sha256", str, "string"),
    ):
        if key in doc:
            val = doc[key]
            if typ is int:
                if not _is_int(val) or val < 0:
                    r.add("error", "bad-field",
                          f"`{key}` must be a non-negative integer.")
            elif not isinstance(val, typ):
                r.add("error", "bad-field", f"`{key}` must be a {label}.")
    if "source_sha256" in doc and isinstance(doc["source_sha256"], str):
        h = doc["source_sha256"]
        if _HEX_RE.match(h) is None or len(h) != 64:
            r.add("error", "bad-field",
                  "`source_sha256` must be 64 lowercase hex digits.")


def _check_ranges(ranges: list, r: Result) -> None:
    seen_paths: dict[str, int] = {}
    for i, rng in enumerate(ranges):
        where = f"ranges[{i}]"
        if not isinstance(rng, dict):
            r.add("error", "bad-range", f"{where} must be an object.")
            continue
        _check_range(rng, where, r, seen_paths)


def _check_range(rng: dict, where: str, r: Result,
                 seen_paths: dict[str, int]) -> None:
    path = rng.get("path") if isinstance(rng.get("path"), str) else None

    # Required: offset, length.
    offset = rng.get("offset")
    length = rng.get("length")
    off_ok = _is_int(offset) and offset >= 0
    len_ok = _is_int(length) and length >= 0
    if "offset" not in rng or not off_ok:
        r.add("error", "bad-offset",
              f"{where}: `offset` must be a non-negative integer.", path=path)
    if "length" not in rng or not len_ok:
        r.add("error", "bad-length",
              f"{where}: `length` must be a non-negative integer.", path=path)

    # path: format + uniqueness.
    if "path" in rng:
        if not isinstance(rng["path"], str) or _PATH_RE.match(rng["path"]) is None:
            r.add("error", "bad-path",
                  f"{where}: `path` must match the path grammar "
                  f"(dotted segments, optional [n]).", path=path)
        else:
            if rng["path"] in seen_paths:
                r.add("error", "duplicate-path",
                      f"{where}: duplicate path {rng['path']!r} "
                      f"(first seen at ranges[{seen_paths[rng['path']]}]).",
                      path=rng["path"])
            else:
                # index recorded against numeric position parsed from `where`
                seen_paths[rng["path"]] = int(where[len("ranges["):-1])

    for key, allowed in (("status", STATUS_VALUES),):
        if key in rng and rng[key] not in allowed:
            r.add("error", "bad-status",
                  f"{where}: `status` {rng[key]!r} not in "
                  f"{sorted(allowed)}.", path=path)

    # type: recognized vs unknown (unknown is non-fatal).
    typ = rng.get("type")
    if typ is not None:
        if not isinstance(typ, str):
            r.add("error", "bad-type",
                  f"{where}: `type` must be a string.", path=path)
            typ = None
        elif typ not in KNOWN_TYPES:
            r.add("warning", "unknown-type",
                  f"{where}: unrecognized type {typ!r}; treated as opaque "
                  f"bytes.", path=path)

    # Hex fields.
    for key in ("raw_hex_preview", "expected_hex"):
        if key in rng and _bad_hex(rng[key]):
            r.add("warning", "malformed-hex",
                  f"{where}: `{key}` must be lowercase hex with an even "
                  f"number of digits.", path=path)

    # decoded type.
    if "decoded" in rng:
        dv = rng["decoded"]
        if not (isinstance(dv, (str, bool)) or _is_int(dv)
                or isinstance(dv, float)):
            r.add("error", "bad-decoded",
                  f"{where}: `decoded` must be a string, number, or bool.",
                  path=path)
        elif _is_int(dv) and dv > JSON_INT_SAFE_MAX:
            r.add("warning", "unsafe-integer",
                  f"{where}: `decoded` integer exceeds 2^53-1; encode large "
                  f"integers as strings to avoid precision loss.", path=path)

    # Zero-length rules.
    if len_ok and length == 0:
        for key in ("raw_hex_preview", "expected_hex"):
            if rng.get(key):  # present and non-empty
                r.add("error", "zero-length-bytes",
                      f"{where}: zero-length range must not carry a non-empty "
                      f"`{key}`.", path=path)
        if isinstance(typ, str) and typ in SCALAR_TYPES:
            r.add("warning", "zero-length-scalar",
                  f"{where}: scalar `type` {typ!r} on a zero-length range "
                  f"cannot be decoded.", path=path)

    # raw_hex_preview length should match range length when both known.
    # Skip zero-length ranges: the zero-length rules above already handle them.
    rhp = rng.get("raw_hex_preview")
    if len_ok and length > 0 and isinstance(rhp, str) and _HEX_RE.match(rhp) \
            and len(rhp) // 2 != length:
        r.add("warning", "preview-length-mismatch",
              f"{where}: raw_hex_preview is {len(rhp)//2} bytes but range "
              f"length is {length}.", path=path)


def validate_file_aware(doc: dict, data: bytes) -> Result:
    """Checks that need the actual binary. Assumes doc already parsed."""
    r = Result()
    size = len(data)

    declared = doc.get("source_size")
    if _is_int(declared) and declared != size:
        r.add(SEVERITY["source-size-mismatch"], "source-size-mismatch",
              f"source_size {declared} != actual file size {size}.")

    declared_hash = doc.get("source_sha256")
    if isinstance(declared_hash, str) and len(declared_hash) == 64:
        actual = hashlib.sha256(data).hexdigest()
        if actual != declared_hash:
            r.add(SEVERITY["source-sha256-mismatch"], "source-sha256-mismatch",
                  "source_sha256 does not match the file's SHA-256.")

    ranges = doc.get("ranges")
    if not isinstance(ranges, list):
        return r
    for i, rng in enumerate(ranges):
        if not isinstance(rng, dict):
            continue
        where = f"ranges[{i}]"
        path = rng.get("path") if isinstance(rng.get("path"), str) else None
        offset, length = rng.get("offset"), rng.get("length")
        if not (_is_int(offset) and _is_int(length)
                and offset >= 0 and length >= 0):
            continue
        end = offset + length
        if end > size:
            r.add(SEVERITY["range-out-of-bounds"], "range-out-of-bounds",
                  f"{where}: range [{offset}, {end}) extends beyond file "
                  f"size {size}.", path=path, offset=offset, length=length)
            continue  # cannot compare bytes for an out-of-bounds range
        rhp = rng.get("raw_hex_preview")
        if isinstance(rhp, str) and _HEX_RE.match(rhp) and len(rhp) // 2 == length:
            actual_hex = data[offset:end].hex()
            if actual_hex != rhp:
                r.add(SEVERITY["raw-preview-mismatch"], "raw-preview-mismatch",
                      f"{where}: raw_hex_preview disagrees with file bytes.",
                      path=path, offset=offset, length=length)
    return r


def validate(doc: Any, data: Optional[bytes] = None) -> Result:
    r = validate_structural(doc)
    # Only attempt file-aware checks if the document is a dict and the schema
    # name is right; otherwise the structural errors already explain things.
    if data is not None and isinstance(doc, dict) \
            and isinstance(doc.get("schema"), dict) \
            and doc["schema"].get("name") == SCHEMA_NAME:
        r.diagnostics.extend(validate_file_aware(doc, data).diagnostics)
    return r


def _main(argv: Optional[list[str]] = None) -> int:
    p = argparse.ArgumentParser(
        description="Validate a bintools.layout-overlay v1 JSON file.")
    p.add_argument("overlay", help="Path to the overlay JSON file.")
    p.add_argument("-b", "--binary",
                   help="Optional binary file for file-aware checks.")
    p.add_argument("--json", action="store_true",
                   help="Emit diagnostics as a JSON array.")
    args = p.parse_args(argv)

    try:
        with open(args.overlay, "r", encoding="utf-8") as f:
            doc = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        print(f"error: cannot read overlay: {e}", file=sys.stderr)
        return 3

    data: Optional[bytes] = None
    if args.binary:
        try:
            with open(args.binary, "rb") as f:
                data = f.read()
        except OSError as e:
            print(f"error: cannot read binary: {e}", file=sys.stderr)
            return 3

    result = validate(doc, data)

    if args.json:
        print(json.dumps([d.to_dict() for d in result.diagnostics], indent=2))
    else:
        for d in result.diagnostics:
            loc = f" [{d.path}]" if d.path else ""
            print(f"{d.severity}: {d.code}{loc}: {d.message}")
        if not result.diagnostics:
            print("ok: no diagnostics")

    if result.errors:
        return 2
    if result.warnings:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(_main())
