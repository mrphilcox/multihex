# `multihex.core` API reference

`multihex.core` is the stdlib-only engine behind the CLI, TUI, and GUI. You can
import it directly to load files, build the fixed-offset comparison grid, and run
exact searches in your own programs. Everything below is importable from
`multihex.core`.

```python
from multihex.core import (
    HexModel, HexFile, Row, Marker, load_files, hexfile_from_bytes,
    make_text_query, make_hex_query, search_files,
)
```

See [`ARCHITECTURE.md`](ARCHITECTURE.md) for how these pieces fit together.

## Loading files

### `load_files(paths) -> list[HexFile]`
Open every path for lazy, memory-mapped random access. Raises `OSError` on
failure. Use this for real files.

### `hexfile_from_bytes(data, *, name) -> HexFile`
Build a `HexFile` from in-memory bytes with no filesystem path. `name` is the
display label every frontend shows regardless of its basename/path mode (the CLI
uses this for stdin, with `name="<stdin>"`). The bytes are stored as a plain
`bytes` buffer, so `byte_at`/`size` behave exactly like an mmap-backed file.

### `class HexFile`
A single file as random-access bytes.

```python
HexFile(path: str, data: mmap.mmap | bytes | bytearray, name: str | None = None)
```

- `size -> int` — length in bytes.
- `byte_at(offset) -> int | None` — the byte value, or `None` past the end.
- `display_name(mode="basename") -> str` — `"basename"` or `"path"`. When `name`
  is set it is returned verbatim, ignoring `mode` (used for path-less inputs).

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
a coarse class, used by the frontends to drive optional byte-class highlighting.
This is **data only** — the core never emits ANSI, Qt, or Rich/Textual styles;
frontends map a `ByteClass` to their own colors.

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
  markers="single", name_width=None, layout="stacked", gutter_width=None)
  -> list[str]` — the shared, un-styled layout for one row. The offset rides the
  first returned line as a left gutter and the row's remaining lines are indented
  by that gutter width, so the offset shares a line with its bytes (no standalone
  offset line). `gutter_width` sets that width (default `OFFSET_LABEL_WIDTH`, the
  8-digit minimum); pass `offset_gutter_width(model.max_offset)` to size it for
  large offsets.
  `layout` is display-only: `"stacked"` prints one file per line; `"side-by-side"`
  joins the per-file segments horizontally on a single line. `markers` is
  display-only too and controls the marker text only: `"single"` (default) one
  strip per block (a left prefix column in side-by-side), `"repeat"` repeats it
  under each segment in side-by-side (same as `"single"` when stacked), `"none"`
  hides it.
- `offset_label(offset, digits=8) -> str` — the offset gutter label
  (`0x` + `digits` zero-padded hex; default 8). `offset_hex_digits(max_offset)`
  returns the digit count needed for offsets up to `max_offset` (never below 8),
  and `offset_gutter_width(max_offset)` the matching label width.
  `OFFSET_LABEL_WIDTH` is the 8-digit minimum. `HexModel.max_offset` gives the
  largest row offset a model renders, so a frontend sizes its gutter once.
- `name_column_width(files, mode="basename") -> int`,
  `marker_prefix_width(name_width) -> int` — alignment helpers (measured within
  the block body, i.e. after the offset gutter).
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
`query.file_index` is out of range. The cap is global across all searched files,
and counts matches after `overlap` filtering. With `max_results=None` this
collects every match, so peak memory is unbounded for a needle that occurs very
often (e.g. a one-byte pattern over a large file) - prefer `search_files_bounded`
in frontends.

### `search_files_bounded(files, query, *, max_results=DEFAULT_SEARCH_MAX_RESULTS, overlap=False, model=None) -> SearchResults`
Memory-bounded wrapper over `search_files`. Applies a global default cap
(`DEFAULT_SEARCH_MAX_RESULTS`, currently 10000) unless the caller overrides it,
and reports whether more matches existed past the cap. It probes for one match
beyond the cap to detect truncation, then trims back, so peak memory stays
bounded to `max_results + 1` matches. Pass `max_results=None` for an unbounded
search (the documented escape hatch; memory is then unbounded). This is the call
all three frontends use.

### `class SearchResults`
Frozen dataclass returned by `search_files_bounded`: `matches`
(`list[SearchMatch]`, ordered like `search_files`), `truncated` (True when the
search stopped at the cap with more matches remaining), and `limit` (the cap
applied, or `None` when unbounded).

### `DEFAULT_SEARCH_MAX_RESULTS`
Module constant: the project-wide default match ceiling (10000) used by
`search_files_bounded` when no explicit limit is given.

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
