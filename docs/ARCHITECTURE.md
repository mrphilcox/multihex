# Architecture

This document describes how `multihex` is put together for people who want to
work on it. For the public, embeddable API see [`API.md`](API.md); for the
contributor workflow see [`../CONTRIBUTING.md`](../CONTRIBUTING.md).

## One core, two frontends

```
            ┌────────────────────────┐
            │   multihex.core        │   all the *meaning*:
            │   (stdlib only)        │   file loading, the offset
            │                        │   grid, markers, search
            └───────────┬────────────┘
                        │
          ┌─────────────┴──────────────┐
          ▼                            ▼
┌───────────────────┐        ┌───────────────────────┐
│  multihex.cli     │        │  multihex.tui         │
│  batch frontend   │        │  interactive frontend │
│  text/JSON/color  │        │  Textual viewer       │
└───────────────────┘        └───────────────────────┘
```

| Module                  | Responsibility                                                        |
| ----------------------- | -------------------------------------------------------------------- |
| `src/multihex/core.py`  | The *meaning* of a comparison: loading, the row model, marker computation, cell formatting, and exact search. **Stdlib-only.** |
| `src/multihex/cli.py`   | Batch rendering: text layout with ANSI color, JSON shaping, search output, argument parsing. |
| `src/multihex/tui.py`   | Interactive rendering: a Textual app with scrolling, paging, jump, live ref switching, and search highlight state. Requires `textual` + `rich`. |

The guiding rule: **comparison and search semantics live in the core; frontends
render and navigate only.** This is what keeps the batch CLI and the TUI in
lockstep — they cannot disagree about what "different" means because neither one
decides it.

## The data model

### `HexFile`

A single file exposed as random-access bytes.

- `data` is either an `mmap.mmap` (lazy, demand-paged — produced by
  `load_files()`) or a plain `bytes`/`bytearray` (for tests and in-memory use).
  `byte_at()` and `size` behave identically for both backings, so nothing
  downstream cares which one it is.
- `byte_at(offset)` returns the byte value or `None` if the offset is past the
  file's end.
- `_open_buffer()` uses `mmap` so a small window over a huge file never reads the
  whole file. Empty files (which cannot be mmap'd) fall back to empty `bytes`. On
  POSIX the mapping outlives the file descriptor, so no handle is retained.

### `Row`

One block of the display: `cells` is one list per file (each of length `ncols`,
entries are a byte `0..255` or `None`), plus one `Marker` per column. `has_diff`
is true if any column is not `SAME`.

### `HexModel`

Owns the **fixed offset grid** and computes markers. Row `i` always starts at
`start_offset + i * width`. There is no alignment or inference anywhere in here —
that is the central invariant.

Key behaviors:

- **Bounded vs derived window.** With `length` given, the window is
  `[start_offset, start_offset + length)`: `row_count` is derived from `length`,
  the final row may be narrower than `width`, and rows past every file's end are
  all-missing. With `length=None` (the TUI), the range is derived from the largest
  file and every row is full width.
- **Coordinate helpers:** `row_offset(i)`, `row_count`, `index_for_offset(offset)`
  (clamped to visible rows), and `locate(offset)` → `(row_index, column)` on the
  same fixed grid (used to place search matches).
- Construction validates its inputs (`width > 0`, non-negative `start_offset` /
  `length`, in-range `ref`).

## Marker computation

`HexModel._markers()` is the **single source of truth** for column state, shared
by both frontends. For each column:

1. If **any** byte is `None`, the column is `MISSING` (`--`). Missing wins
   outright.
2. Otherwise pick the **pivot**: `column[ref]` when `--ref` is set, else
   `column[0]`.
3. If every byte equals the pivot, the column is `SAME` (`==`); otherwise `DIFF`
   (`!=`).

Because this lives in one place, "what differs" is identical in text, JSON, and
the TUI.

## Cell formatting

The core also owns rendering primitives so the frontends stay consistent:
`format_byte()` (two-char hex or `--`), `format_ascii_char()` /
`format_ascii()` (printable char, `.`, or space for missing),
`format_marker()`, and `render_row_text()` — the shared un-styled layout used
directly by the batch CLI and as the geometry reference for the TUI's styled
rendering. `name_column_width()` and `marker_prefix_width()` keep the marker row
aligned under the hex columns.

The core also owns **byte classification** for the optional `--byte-classes`
highlighting: `classify_byte(value) -> ByteClass` maps a byte (or `None`) to a
coarse class (`ZERO` / `WHITESPACE` / `PRINTABLE_ASCII` / `OTHER` / `MISSING`).
This is **data only** — like the rest of the core it emits no ANSI and no
Rich/Textual styles. Each frontend maps a `ByteClass` to its own colors as the
lowest-priority styling tier, so it never overrides missing/diff/search
highlighting and is purely visual (no effect on markers, filtering, search, or
JSON).

## The search subsystem

Search is **exact**: it reports observed byte matches only, with no wildcards,
alignment, or inference. It lives entirely in the core; frontends add UI glue.

- **Queries.** `SearchQuery` is a frozen, frontend-independent request (`mode`,
  original `pattern`, exact `needle` bytes, `case_sensitive`, optional
  `file_index`). Build one with `make_text_query()` (UTF-8) or `make_hex_query()`
  (via `parse_hex_pattern()`). `parse_hex_pattern()` accepts whitespace, `:`, `-`,
  `,` separators and optional `0x` prefixes, and raises `SearchError` with a
  user-facing message on bad input.
- **Matching.** `search_files()` returns `SearchMatch` objects ordered
  deterministically by `(file_index, offset)`. Matches are non-overlapping by
  default (`overlap=True` to include overlaps); `max_results` caps the count; an
  optional `model` fills each match's `row_index`/`column` via `HexModel.locate()`.
  `_find_in_file()` searches the backing buffer directly (no copy) for
  case-sensitive and hex queries; case-insensitive text folds a full `bytes` copy
  of the file via an ASCII-only translation table (the documented cost).
- **Navigation.** Index-based helpers operate on an already-ordered result list
  and return an index (or `None`), which is exactly what a frontend tracking a
  "current match" needs: `first_match_index()`, `next_match_index()`,
  `prev_match_index()` (both wrap by default), and `match_index_after()` /
  `match_index_before()` for seeking from an arbitrary `(file, offset)`.

## The frontend boundary

Frontends are allowed to **render, navigate, and filter** — nothing more.

- **`cli.py`** turns core `Row`s into colored text or JSON. Its color scheme
  reddens *individual cells that differ from the reference*, dims missing cells,
  and colors marker tokens. `--only-diff` and `--limit-rows` are presentation
  filters applied over `model.build_row(i)`. Search short-circuits the normal dump
  (`run_search`) so existing output and its goldens are untouched when no
  `--search-*` flag is present.
- **`tui.py`** is a Textual `App` with a `HexView` widget. It owns navigation
  state (top row, page size, only-diff visible set, toggles) and search highlight
  state, but every byte and marker still comes from the core model. Its color
  scheme highlights **whole columns** by marker, plus search matches with the
  priority: missing > current match > other match > diff. With `--byte-classes`
  (or the `t` toggle) byte-class foreground color is appended as the lowest tier
  (`… > diff > byte class`); the `c` color toggle hides it along with everything
  else, and its on/off state is independent.

The two color schemes **differ on purpose** — do not unify them. The CLI is for
spotting exact differing bytes in a scrollback or a pipe; the TUI is for scanning
column stability at a glance.

## Invariants (do not break these)

1. **Fixed-offset comparison only.** No byte alignment, resync, or inference.
   Missing bytes render as `--`. Marker logic stays centralized in
   `HexModel._markers()`.
2. **Exact search only.** Report observed byte matches; never add wildcards,
   alignment, or inference. Search semantics stay in the core.
3. **The core stays stdlib-only.** No third-party imports in `core.py`. The TUI
   may depend on `textual`/`rich`; the core and batch CLI may not.
