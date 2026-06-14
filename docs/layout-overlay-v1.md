# bintools.layout-overlay v1

A versioned, human-readable JSON format describing a concrete list of byte
ranges within **one specific binary file**. It is the shared contract between
bintools (producer) and multihex (consumer), and is equally usable as a
hand-authored file.

An overlay does **not** describe how its ranges were derived. It is resolved
evidence about a single file, not a reusable layout grammar. (Reusable
validation grammars are the separate `layout-spec` concept and are out of scope
here.)

## Design invariants

These hold for every version of this schema and must never be weakened by a
future field:

1. **Sizes, offsets, endianness, alignment, and field presence are
   format-specific.** Nothing is assumed. There is no default scalar width, no
   default endianness, no default header size, no assumed magic field, no
   assumed payload offset.
2. **When scalar decoding is requested, width and endianness are explicit in
   `type`.** They are never inferred from context. (Byte/string types and
   minimal overlays carry no endianness, and that is fine.)
3. **The binary file is authoritative for byte content**, not the overlay. Any
   byte data carried in the overlay is advisory/verification only.
4. **Unknown optional fields are ignored** (per object level). Missing required
   fields are an error. An unknown `schema.version` is an error.

## Top-level structure

```json
{
  "schema": { "name": "bintools.layout-overlay", "version": 1 },
  "name": "example_layout",
  "source_file": "sample.bin",
  "source_size": 20,
  "source_sha256": "…",
  "ranges": [ … ],
  "diagnostics": []
}
```

### Top-level fields

| Field           | Req? | Type    | Meaning |
|-----------------|------|---------|---------|
| `schema`        | yes  | object  | Schema identity block (see below). |
| `ranges`        | yes  | array   | The byte ranges. May be empty. |
| `name`          | no   | string  | Human label for this overlay. |
| `source_file`   | no   | string  | **Advisory** name/path of the file this overlay describes. Documentation and an optional sanity check only. A mismatch with the file multihex was given is a diagnostic, never a load failure. |
| `source_size`   | no   | integer | Expected file size in bytes. If present and it disagrees with the actual file, emit a diagnostic. Stronger than `source_file` because it checks content compatibility rather than just a name, but it is still not a hard load failure. Intended mainly for generated traces; optional for hand-authored overlays. |
| `source_sha256` | no   | string  | Expected file hash, lowercase hex. Same semantics as `source_size`: mismatch → diagnostic, not a load failure. |
| `diagnostics`   | no   | array   | Overlay-level diagnostics (see Diagnostics). |

### `schema` block

| Field     | Req? | Type    | Meaning |
|-----------|------|---------|---------|
| `name`    | yes  | string  | Must be `"bintools.layout-overlay"`. |
| `version` | yes  | integer | Currently `1`. |

**Validation order:** check `name` first. A wrong or missing `name` means *this
is not our file* — fail with a clear error and do not attempt to parse
`ranges`. Only once `name` matches, check `version`: an unknown version with the
correct name means *too new / unsupported* — fail clearly rather than guessing.

## The range object

A range is one highlightable region of the file.

| Field          | Req? | Type                  | Meaning |
|----------------|------|-----------------------|---------|
| `offset`       | yes  | integer ≥ 0           | Byte offset from start of file. |
| `length`       | yes  | integer ≥ 0           | Length in bytes. `length: 0` is permitted (zero-width marker). |
| `label`        | no   | string                | Human-facing name. If absent, the viewer falls back to `path`, then to the offset. |
| `path`         | no   | string                | Dotted/indexed path; source of truth for grouping. MUST be unique within `ranges` when present (see Paths and grouping). |
| `kind`         | no   | string (open vocab)   | Semantic role; drives display/color/filter (see Vocabularies). |
| `type`         | no   | string (recognized, extensible) | Decode hint; how to interpret the bytes (see Vocabularies). |
| `decoded`      | no   | string \| number \| bool | Display value the producer computed. Shown verbatim. Generated producers SHOULD encode integers larger than 2^53 − 1 as strings to avoid precision loss in JSON consumers (relevant for `u64`, offsets, sizes, timestamps, bitmasks, hashes). |
| `raw_hex_preview` | no | string               | **Advisory** preview of the bytes, lowercase hex. The file is authoritative; if this disagrees with the file, emit a diagnostic. Should be omitted or capped for large ranges. |
| `expected_hex` | no   | string                | Expected bytes, lowercase hex, for validation display. |
| `status`       | no   | string (closed vocab) | Validation result (see Vocabularies). Defaults to `unchecked`. |
| `diagnostics`  | no   | array                 | Range-level diagnostics (see Diagnostics). |

### Offset / length bounds

`offset` and `length` are non-negative JSON integers. If `offset + length`
exceeds the actual file size, this is a **load-time diagnostic, not a hard
fail**: the viewer should still render the in-bounds portion so a partially
wrong overlay is still useful.

`length: 0` is permitted as a zero-width marker (insertion point, EOF marker,
parse cursor, "expected field missing here"). For a zero-length range,
`raw_hex_preview` and `expected_hex` must be absent or the empty string, and
consumers must not attempt scalar decoding regardless of `type`.

### Hex strings

`raw_hex_preview` and `expected_hex` are lowercase hexadecimal with an even
number of digits (whole bytes). Malformed hex strings should produce a
diagnostic.

## Vocabularies

### `type` — recognized, extensible

A decode hint for how to interpret the bytes. The viewer may use this to compute
`decoded` when the producer did not supply one; it has no other effect. When
scalar decoding is requested, width and endianness are explicit here.

Consumers must recognize the v1 types below:

```
u8
u16le  u16be
u32le  u32be
u64le  u64be
bytes
ascii
utf8
```

Unknown `type` values are **not fatal**: they are treated as opaque `bytes` and
should produce a diagnostic. This lets future producers emit types like `i32le`,
`f32le`, `uuid`, or `unix_time_u32le` without forcing a schema bump, while older
consumers still load the overlay and tell the user the decode hint was not
understood. Absent `type` means opaque bytes with no decode attempted (no
diagnostic).

### `kind` — open

Semantic role, advisory display metadata only. Drives grouping, coloring, and
filtering. Common values:

```
identifier  integer  count  length  offset  timestamp
payload  padding  reserved  checksum  flags
```

Because `kind` is open, an **unknown value is harmless** — the viewer falls back
to a neutral default. New formats with unanticipated roles never require a
schema bump.

`kind` and `type` are **independent axes.** A `timestamp` kind may be `u32le`,
`u64be`, or `bytes`; a `length` kind is probably an integer type but the schema
does not enforce the pairing. Keeping them orthogonal keeps both lists short.

### `status` — closed

```
ok         validated, matches expectation
warning    suspicious but not fatal
error      validation failed for this range; the overlay may still be loadable
unchecked  no validation performed (default when absent)
```

A hand-authored overlay with no expected values renders everything
`unchecked`, **not** green. Green (`ok`) means something was actually checked.
A range `status` of `error` is a *validation* failure, distinct from a
structural/schema parse error (which is a hard load failure).

## Paths and grouping

`path` is the single source of truth for hierarchy. The range list stays
**flat** — easy to author, stream, and diff by path — and the viewer derives a
tree from the paths.

Grammar (minimal):

- Dot-separated segments: `header.record_count`
- Optional `[n]` index suffix on a segment for repeats: `records[0].payload`

`header.record_count` implies a `header` group; `records[0]` and `records[1]`
imply a `records` group with indexed children. Parent groups are **derived, not
listed** — a group is not itself a range.

### Path policy

Generated overlays SHOULD provide a stable, unique `path` for every range.
Hand-authored overlays MAY omit `path`. When `path` is absent, consumers should
synthesize an internal identity from `offset`, `length`, and `label` — but a
synthesized identity is not stable enough for field-aware diffing. Future tools
such as `layoutxdiff` should rely on `path`, not on labels or offsets.

When present, `path` MUST match the grammar above (dot-separated segments, each
an identifier with an optional `[n]` index). A `path` that violates the grammar
is a structural error and should produce a `bad-path` diagnostic.

When present, `path` MUST be unique within `ranges`. Alternative interpretations
of the same bytes are expressed through overlapping ranges with distinct paths,
not duplicate paths. Duplicate paths are a structural overlay error: producers
must not emit them, but consumers may report a `duplicate-path` diagnostic and
continue loading for interactive viewing.

## Overlapping ranges

Overlap is permitted. Because groups are derived from paths rather than listed
as ranges, the common "field is also part of a header span" case does not
produce overlap. Explicit overlapping ranges are reserved for genuine
**alternative interpretations** of the same bytes. The viewer should render
overlaps as stacked/layered, **not** error.

## Diagnostics

Diagnostics appear at top level (about the overlay/file as a whole) and/or on
individual ranges. Each diagnostic:

| Field      | Req? | Type   | Meaning |
|------------|------|--------|---------|
| `severity` | yes  | string | `info` \| `warning` \| `error`. |
| `message`  | yes  | string | Human-readable description. |
| `code`     | no   | string | Stable machine-readable identifier, e.g. `range-out-of-bounds`, `unknown-type`, `source-size-mismatch`, `duplicate-path`, `bad-path`, `raw-preview-mismatch`, `malformed-hex`. Lets tests assert on a code rather than exact prose. |
| `path`     | no   | string | Range path this refers to, when applicable. |
| `offset`   | no   | integer | Byte offset this refers to, when it does not map cleanly to a named range. |
| `length`   | no   | integer | Byte length associated with the diagnostic, when applicable. |

Example:

```json
{
  "severity": "warning",
  "code": "range-out-of-bounds",
  "message": "Range extends beyond end of file",
  "path": "payload",
  "offset": 128,
  "length": 64
}
```

Diagnostics are produced both by producers (e.g. layoutcheck recording a failed
constraint) and by the consumer at load time (size mismatch, out-of-bounds
range, unknown `type`, `raw_hex_preview` disagreeing with the file).

## Compatibility rules

```
correct schema.name, version 1   → current schema, parse normally
wrong/missing schema.name         → not our file; fail clearly, do not parse
correct name, unknown version     → too new; fail clearly
unknown optional fields           → ignore (checked per object level)
missing required fields           → fail
```

Additive, optional fields (e.g. future `display_hints`, `confidence`) may be
introduced within version 1 because unknown-field tolerance is required. A
change that removes or repurposes a required field, or alters the meaning of an
existing field, requires a version bump.

## Example

A 20-byte file: a 3-byte ASCII identifier, a 2-byte big-endian record count, two
bytes of padding, then a 13-byte payload. No fixed identifier width is assumed;
the identifier happens to be 3 bytes here.

```json
{
  "schema": { "name": "bintools.layout-overlay", "version": 1 },
  "name": "example_layout",
  "source_file": "sample.bin",
  "source_size": 20,
  "ranges": [
    {
      "path": "header.identifier",
      "offset": 0,
      "length": 3,
      "kind": "identifier",
      "label": "format identifier",
      "type": "ascii",
      "raw_hex_preview": "464d54",
      "decoded": "FMT",
      "expected_hex": "464d54",
      "status": "ok"
    },
    {
      "path": "header.record_count",
      "offset": 3,
      "length": 2,
      "kind": "count",
      "label": "record count",
      "type": "u16be",
      "raw_hex_preview": "0002",
      "decoded": 2,
      "status": "ok"
    },
    {
      "path": "header.padding",
      "offset": 5,
      "length": 2,
      "kind": "padding",
      "label": "alignment padding",
      "type": "bytes",
      "raw_hex_preview": "0000",
      "status": "unchecked"
    },
    {
      "path": "payload",
      "offset": 7,
      "length": 13,
      "kind": "payload",
      "label": "payload bytes",
      "type": "bytes",
      "status": "unchecked"
    }
  ],
  "diagnostics": []
}
```

The payload range carries no `raw_hex_preview` — it is large-ish and the file is
authoritative anyway. The padding and payload are `unchecked` because nothing
validated them; only the identifier and count were checked against expectations.

## Minimal hand-authored example

The smallest useful overlay: just boxes with labels.

```json
{
  "schema": { "name": "bintools.layout-overlay", "version": 1 },
  "ranges": [
    { "offset": 0, "length": 4, "label": "file marker" },
    { "offset": 4, "length": 4, "label": "version", "type": "u32le" },
    { "offset": 8, "length": 56, "label": "page header", "kind": "reserved" }
  ]
}
```

Everything else is optional. This is the authoring experience the schema is
designed to protect.
