# `multihex.core` API reference

`multihex.core` is the stdlib-only engine behind both frontends. You can import it
directly to load files, build the fixed-offset comparison grid, and run exact
searches in your own programs. Everything below is importable from
`multihex.core`.

```python
from multihex.core import (
    HexModel, HexFile, Row, Marker, load_files,
    make_text_query, make_hex_query, search_files,
)
```

See [`ARCHITECTURE.md`](ARCHITECTURE.md) for how these pieces fit together.

## Loading files

### `load_files(paths) -> list[HexFile]`
Open every path for lazy, memory-mapped random access. Raises `OSError` on
failure. Use this for real files.

### `class HexFile`
A single file as random-access bytes.

```python
HexFile(path: str, data: mmap.mmap | bytes | bytearray)
```

- `size -> int` — length in bytes.
- `byte_at(offset) -> int | None` — the byte value, or `None` past the end.
- `display_name(mode="basename") -> str` — `"basename"` or `"path"`.

For tests or in-memory data you can construct one directly from `bytes`:

```python
f = HexFile(path="synthetic", data=b"\x00\x01\x02\x03")
```

## The comparison model

### `class HexModel`
Builds rows and computes markers over a **fixed** offset grid (row `i` starts at
`start_offset + i * width`).

```python
HexModel(
    files: list[HexFile],
    *,
    start_offset: int = 0,
    width: int = 16,
    ref: int | None = None,      # 0-based pivot file, or None for "all agree"
    length: int | None = None,   # bound the window, or derive from largest file
)
```

- `row_count -> int`
- `row_offset(index) -> int`
- `index_for_offset(offset) -> int` — visible row index containing `offset` (clamped).
- `locate(offset) -> tuple[int, int] | None` — `(row_index, column)` on the grid.
- `build_row(index) -> Row` — the row's cells and markers.

### `class Row`
`offset`, `cells` (one `list[int | None]` per file), `markers` (one per column),
and the convenience property `has_diff`.

### `enum Marker`
`SAME` (`"=="`), `DIFF` (`"!="`), `MISSING` (`"--"`). `format_marker(marker)`
returns the two-char token.

```python
model = HexModel([HexFile("a", b"ABC"), HexFile("b", b"ABX")])
row = model.build_row(0)
[m.value for m in row.markers[:3]]   # ['==', '==', '!=']
```

### `enum ByteClass` / `classify_byte(value) -> ByteClass`
Display-only classification of a single byte value (or `None` for missing) into
a coarse class, used by both frontends to drive optional byte-class
highlighting. This is **data only** — the core never emits ANSI or Rich/Textual
styles; frontends map a `ByteClass` to their own colors.

- `MISSING` — `value is None` (a byte past a file's end).
- `ZERO` — `0x00`.
- `WHITESPACE` — `0x09`, `0x0a`, `0x0b`, `0x0c`, `0x0d`, `0x20` (space included).
- `PRINTABLE_ASCII` — `0x21`–`0x7e` (space is `WHITESPACE`, not printable).
- `OTHER` — everything else (e.g. `0x7f`, `0x80`, `0xff`).

```python
classify_byte(0x00)   # ByteClass.ZERO
classify_byte(0x20)   # ByteClass.WHITESPACE
classify_byte(0x41)   # ByteClass.PRINTABLE_ASCII
classify_byte(None)   # ByteClass.MISSING
```

## Formatting helpers

- `format_byte(byte) -> str` — two-char hex, or `--` for `None`.
- `format_ascii_char(byte) -> str` / `format_ascii(row_bytes) -> str` — printable
  char, `.`, or space (for missing).
- `render_row_text(row, files, *, name_mode="basename", ascii_on=True,
  show_markers=True, name_width=None) -> list[str]` — the shared, un-styled
  multi-line layout for one row.
- `name_column_width(files, mode="basename") -> int`,
  `marker_prefix_width(name_width) -> int` — alignment helpers.
- `parse_int(text) -> int` — parse like the CLI does (`int(x, 0)`: decimal, `0x`,
  `0o`, `0b`).

## Exact search

Search is exact — observed byte matches only, no wildcards or inference.

### Building a query
- `make_text_query(pattern, *, case_sensitive=True, file_index=None) -> SearchQuery`
  — UTF-8 text. Empty pattern raises `SearchError`.
- `make_hex_query(pattern, *, file_index=None) -> SearchQuery` — a hex pattern,
  always case-sensitive.
- `parse_hex_pattern(text) -> bytes` — parse a flexible hex string (whitespace /
  `:` / `-` / `,` separators, optional `0x`). Raises `SearchError` on empty input,
  an odd digit count, or non-hex characters.

### `class SearchQuery`
Frozen dataclass: `mode` (`"text"`/`"hex"`), `pattern`, `needle` (bytes),
`case_sensitive`, `file_index`.

### `search_files(files, query, *, max_results=None, overlap=False, model=None) -> list[SearchMatch]`
Search and return matches ordered by `(file_index, offset)`. Non-overlapping by
default; `overlap=True` includes overlapping hits; `max_results` caps the count;
pass a `model` to fill each match's `row_index`/`column`. Raises `SearchError` if
`query.file_index` is out of range.

### `class SearchMatch`
Frozen dataclass: `file_index`, `path`, `offset`, `length`, `matched` (bytes), and
optional `row_index` / `column` (set when a `model` was provided).

### `exception SearchError(ValueError)`
Raised by the query builders with a human-readable message suitable for showing
directly to a user.

### Navigation helpers
All operate on an ordered result list and return an index (or `None`):

- `first_match_index(matches)`
- `next_match_index(matches, current, *, wrap=True)`
- `prev_match_index(matches, current, *, wrap=True)`
- `match_index_after(matches, file_index, offset, *, inclusive=True, wrap=True)`
- `match_index_before(matches, file_index, offset, *, inclusive=True, wrap=True)`

## Worked example

```python
from multihex.core import HexFile, HexModel, make_hex_query, search_files

# In-memory files (no disk needed):
files = [
    HexFile("a", b"RIFF\x00\x01\xde\xad\xbe\xef"),
    HexFile("b", b"RIFF\x00\x01\xde\xad\x00\x00"),
]

# Compare at fixed offsets:
model = HexModel(files, width=16)
row = model.build_row(0)
print(" ".join(m.value for m in row.markers[:10]))
# => == == == == == == == == != !=

# Exact search, with grid coordinates filled in:
matches = search_files(files, make_hex_query("de ad"), model=model)
for m in matches:
    print(m.file_index, hex(m.offset), m.matched, m.row_index, m.column)
# => 0 0x6 b'\xde\xad' 0 6
# => 1 0x6 b'\xde\xad' 0 6
```
