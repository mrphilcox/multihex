# multihex Reference Manual

Reference for `multihex` version 0.1.0. This document is organized for lookup,
not for reading start to finish. For a guided introduction see `README.md`; for
internals see `docs/ARCHITECTURE.md` and `docs/API.md`.

Every statement here is derived from the source in `src/multihex/`. Where the
source and the prose documentation disagree, this manual follows the source.
Discrepancies found during the source survey are listed in
[Appendix E](#appendix-e-doccode-discrepancies-found).

## Table of contents

1. [Scope and conventions](#1-scope-and-conventions)
2. [Overview and frontend model](#2-overview-and-frontend-model)
3. [Installation and invocation](#3-installation-and-invocation)
4. [Common concepts](#4-common-concepts)
5. [multihex (batch CLI) reference](#5-multihex-batch-cli-reference)
6. [Search reference](#6-search-reference)
7. [multihex-tui reference](#7-multihex-tui-reference)
8. [multihex-gui reference](#8-multihex-gui-reference)
9. [Comparison and markers reference](#9-comparison-and-markers-reference)
10. [Layout overlay reference](#10-layout-overlay-reference)
11. [Exit codes and diagnostics](#11-exit-codes-and-diagnostics)
12. [File handling](#12-file-handling)
13. [Appendix A: flag index](#appendix-a-flag-index)
14. [Appendix B: key and menu index](#appendix-b-key-and-menu-index)
15. [Appendix C: glossary](#appendix-c-glossary)
16. [Appendix D: overlay diagnostic codes](#appendix-d-overlay-diagnostic-codes)
17. [Appendix E: doc/code discrepancies found](#appendix-e-doccode-discrepancies-found)

---

## 1. Scope and conventions

`multihex` compares the byte values that live at identical offsets across two or
more binary files. It is a viewer and comparator. It performs no alignment,
resynchronization, or format inference: offset `N` in one file is only ever
compared to offset `N` in the others.

This manual covers four invokable surfaces:

- `multihex` (batch CLI)
- `multihex-tui` (interactive terminal viewer)
- `multihex-gui` (read-only desktop viewer)
- `python3 -m multihex.layout_overlay_v1` (the vendored overlay validator)

Notation in this manual:

- `INDEX` is a 0-based file index.
- `N` is an integer accepted in any base understood by Python's `int(x, 0)`:
  decimal, `0x` hex, `0o` octal, `0b` binary, with an optional sign. Each option
  table states whether negative values are accepted.
- "Visual-only" / "display-only" means the option changes rendering only and
  never affects offsets, byte values, comparison markers, `--ref`, `--only-diff`,
  search results, or `--json` output.

### Relationship to bintools

`multihex` consumes `bintools.layout-overlay` v1 files. The sibling `bintools`
project produces them. The schema and validator
(`src/multihex/layout_overlay_v1.py`, `docs/layout-overlay-v1.md`) are a vendored
copy shared with bintools. `multihex` only loads, validates, displays, and
highlights overlays. It never authors, infers, or edits them.

---

## 2. Overview and frontend model

All three frontends share one engine, `multihex.core`, which is stdlib-only.
The core owns: file loading, the offset grid (`HexModel` / `Row`), three-state
column markers, cell formatting, byte classification, and exact search. The
frontends add only presentation and navigation glue. A given window therefore
produces semantically identical comparisons in every frontend.

Supporting modules: `overlay.py` (overlay load/query seam), `layout_overlay_v1.py`
(overlay validator), `tui_config.py` (TUI-only persisted preferences), and
`shortcuts.py` (the shared keyboard registry that is the single source of truth
for the TUI and GUI keymaps and help text).

### The fixed-offset invariant

`HexModel` compares fixed offsets. There is no byte alignment, resync, or
inference. A byte that is past a file's end is "missing" and renders as `--`.
This invariant is guaranteed not to change.

### Markers and the pivot

Every comparison column carries one three-state marker:

| Token | Marker | Meaning |
|-------|--------|---------|
| `==`  | SAME    | every file's byte at this offset equals the pivot |
| `!=`  | DIFF    | all bytes present, but at least one differs from the pivot |
| `--`  | MISSING | at least one file has no byte at this offset |

`MISSING` wins outright: if any byte in a column is missing, the column is `--`
regardless of the others. Otherwise the column is `==` when every byte equals the
pivot, else `!=`.

The pivot is:

- the first file's byte (`column[0]`) when no `--ref` is given, so `==` means
  "all files agree";
- the `--ref INDEX` file's byte when `--ref` is given, so `==` means "matches the
  reference".

Marker computation lives only in `HexModel._markers()` and is identical across
frontends.

---

## 3. Installation and invocation

Requires Python >= 3.9. The core and batch CLI have no third-party dependencies.

| Install command | Provides |
|-----------------|----------|
| `pip install .` | core + `multihex` |
| `pip install '.[tui]'` | adds `textual` + `rich` (and `tomli` on 3.9/3.10) for `multihex-tui` |
| `pip install '.[gui]'` | adds `PySide6` for `multihex-gui` |
| `pip install -e '.[dev]'` | tests, linter, and the TUI |
| `pip install -e '.[dev,gui]'` | the above plus the GUI |

Console scripts installed: `multihex` (`multihex.cli:main`), `multihex-tui`
(`multihex.tui:main`), `multihex-gui` (`multihex.gui:main`).

Without installing, from a checkout with `src/` on `PYTHONPATH`:

```bash
PYTHONPATH=src python3 -m multihex.cli FILE1 FILE2
PYTHONPATH=src python3 -m multihex.tui FILE1 FILE2
PYTHONPATH=src python3 -m multihex.gui FILE1 FILE2
```

Synopses:

```
multihex     [OPTIONS] FILE [FILE ...]
multihex-tui [OPTIONS] FILE [FILE ...]
multihex-gui [OPTIONS] [FILE ...]
```

`multihex` and `multihex-tui` require at least one file. `multihex-gui` accepts
zero files and opens an empty window (load files from the File menu).

### Standard input

Only the batch CLI reads stdin. A lone `-` positional reads raw bytes from
`sys.stdin.buffer`, at most once. It is treated as an ordinary input: it can be
compared against files and participates in markers, `--ref`, search, and overlay.
A stdin input is always labelled `<stdin>` regardless of `--names`, and its
`--json` `paths` entry is `null`. stdin is read fully into memory (it is not
seekable). `multihex-tui` and `multihex-gui` do not read stdin.

```bash
cat firmware.bin | multihex -
multihex - other.bin
```

---

## 4. Common concepts

### Offset grid and windowing

Row `i` starts at `start_offset + i * width`. The batch CLI always bounds the
window with a `length` (the `--length` value, or the shortest remaining length
common to all files). The TUI and GUI derive the range from the largest file
(unbounded length), so every row is full width. The final row of a bounded window
may be narrower than `width`. Rows past every file's end are all-missing.

### Byte classes

`core.classify_byte()` maps a byte (or a missing byte) to one of five classes.
This drives optional byte-class highlighting and is display-only.

| Class | Bytes |
|-------|-------|
| MISSING | past a file's end (renders as `--`) |
| ZERO | `0x00` |
| WHITESPACE | `0x09` tab, `0x0a` LF, `0x0b` VT, `0x0c` FF, `0x0d` CR, `0x20` space |
| PRINTABLE_ASCII | `0x21`-`0x7e` (note: `0x20` space is WHITESPACE, not printable) |
| OTHER | everything else (`0x7f`, `0x80`-`0xff`, and `0x01`-`0x08`, `0x0e`-`0x1f`) |

Highlighting tints only ZERO, WHITESPACE, and PRINTABLE_ASCII cells. OTHER and
MISSING are never byte-class colored. Byte classes never affect comparison.

### The ASCII gutter

The gutter renders one character per byte: bytes `0x20`-`0x7e` print as
themselves, missing bytes print as a space, and all other bytes print as `.`.
Note the gutter's printable range (`0x20`-`0x7e`) intentionally differs from the
byte-class printable range (`0x21`-`0x7e`).

### Color resolution

`--color` accepts `auto` (default), `always`, `never`.

- `auto`: color on when stdout is a TTY and the `NO_COLOR` environment variable
  is unset.
- `always`: color on. This mode does NOT consult `NO_COLOR`.
- `never`: color off.
- `--json` forces color off regardless of `--color`.

The TUI resolves the same way from its startup `--color` / config `color`
setting, except there is no TTY test (the TUI always runs on a terminal): `auto`
is on unless `NO_COLOR` is set. The GUI has no `--color` flag; color starts on
and is toggled from the View menu or the `c` key.

### File-name display

`--names basename` (default) labels each file by its basename; `--names path`
uses the path as given. A stdin input always shows as `<stdin>`. The label width
is padded to the widest label so columns align.

---

## 5. multihex (batch CLI) reference

```
multihex [OPTIONS] FILE [FILE ...]
```

Default behavior: show the largest range common to all files starting at offset
0, 16 bytes per row, stacked layout, ASCII gutter on, single marker strip, color
when stdout is a TTY.

### 5.1 Windowing options

| Option | Value | Default | Semantics |
|--------|-------|---------|-----------|
| `--offset N` | integer >= 0 | `0` | First offset displayed. Negative is an error. |
| `--length N` | integer >= 0 | shortest remaining length common to all files | Number of bytes in the window: `[offset, offset+length)`. Negative is an error. Does not consider file size, so a large value renders many all-missing rows past EOF. |
| `--width N` | integer >= 1 | `16` | Bytes per row. `< 1` is an error. |
| `--around OFF:N` | `OFF:N` | unset | Show `N` bytes centered on `OFF`: sets `offset = max(0, OFF - N/2)` and `length = N`. Overrides `--offset` and `--length`. The argument must contain a colon; both parts accept any `int(x, 0)` base. |

### 5.2 Comparison options

| Option | Value | Default | Semantics |
|--------|-------|---------|-----------|
| `--ref INDEX` | 0-based index | unset (all-agree) | Use this file as the pivot. `==` means "matches the reference". Also reddens, in color, each cell that differs from the reference. Out of range is a hard error (exit 1). |
| `--only-diff` | flag | off | Print only rows that contain at least one `!=` or `--` column. |
| `--limit-rows N` | integer >= 1 | unset | Stop after `N` printed rows (applied after `--only-diff` filtering). `< 1` is an error. |

### 5.3 Display options

| Option | Value | Default | Semantics |
|--------|-------|---------|-----------|
| `--ascii` / `--no-ascii` | flag | on | Show or hide the ASCII gutter. |
| `--names basename\|path` | choice | `basename` | Label files by basename or by path-as-given. |
| `--color auto\|always\|never` | choice | `auto` | See [color resolution](#color-resolution). |
| `--byte-classes` | flag | off | Tint hex cells by byte class. Visual-only; needs color on; no effect on `--json`. |
| `--layout stacked\|side-by-side` | choice | `stacked` | `stacked` puts one file per line; `side-by-side` lays files horizontally. Visual-only; side-by-side rows may exceed terminal width (wrapping is left to the terminal or pager). |
| `--markers single\|repeat\|none` | choice | `single` | Marker-strip display, separate from `--layout`. See below. Display-only. |
| `--overlay PATH` | path | unset | Load and highlight a layout overlay. Visual-only; needs color on; no effect on `--json` (when `--json` is set the overlay is not even loaded or reported). See [section 10](#10-layout-overlay-reference). |
| `--json` | flag | off | Emit one JSON object instead of text. Implies color off. |

Marker display (`--markers`):

- `single` (default): one marker strip per block. In `side-by-side` it is drawn
  as its own left prefix column, not attached to the first file.
- `repeat`: in `side-by-side`, repeat the strip under each file segment. In
  `stacked` it is identical to `single`.
- `none`: hide the marker strip text entirely.

`--markers` changes only the marker text rendering. Marker computation,
`--only-diff` filtering, diff and missing highlighting, search, and the JSON
`markers` array are all unaffected.

### 5.4 Text output

A block is one row of the offset grid. The offset rides the first content line as
a left gutter (`0x` plus at least 8 hex digits, so 10 characters wide); the
block's remaining lines are indented under it. The gutter widens automatically
when the largest offset on screen needs 9+ hex digits (offsets at or above
`0x100000000`), keeping a single consistent width for the whole dump. Stacked
layout, no color:

```
0x00000000  a.bin  52 49 46 46 00 01 02 03 4d 41 47 49 43 de ad be  |RIFF....MAGIC...|
            b.bin  52 49 46 46 00 01 02 03 6d 61 67 69 63 de ad 00  |RIFF....magic...|
                   == == == == == == == == != != != != != == == !=
```

### 5.5 Color scheme (batch CLI)

The batch CLI colors individual cells. With color on:

- Each present cell that differs from the pivot's byte in that column is red.
- Missing cells (`--`) are dim.
- Non-diff cells inside an applicable overlay range get a blue background.
- Otherwise, when `--byte-classes` is on, non-diff cells get a byte-class
  foreground (ZERO dim, WHITESPACE cyan, PRINTABLE_ASCII green).
- Marker tokens are colored: `==` green, `!=` red, `--` dim.

Cell priority, highest first: missing > diff > overlay > byte class. The ASCII
gutter is never colored in the batch CLI.

This per-cell scheme is intentionally different from the TUI/GUI whole-column
scheme; the two are not unified by design.

### 5.6 JSON output

`--json` emits a single object. It is the stable, scriptable surface and is
unaffected by `--layout`, `--markers`, `--byte-classes`, `--color`, or
`--overlay`.

```bash
multihex --length 8 a.bin b.bin --json
```

```json
{
  "offset": 0,
  "length": 8,
  "width": 16,
  "ref": null,
  "files": ["a.bin", "b.bin"],
  "paths": ["a.bin", "b.bin"],
  "rows": [
    {
      "offset": 0,
      "markers": ["==", "==", "==", "==", "==", "==", "==", "=="],
      "files": [
        {"name": "a.bin", "bytes": [82, 73, 70, 70, 0, 1, 2, 3], "ascii": "RIFF...."},
        {"name": "b.bin", "bytes": [82, 73, 70, 70, 0, 1, 2, 3], "ascii": "RIFF...."}
      ]
    }
  ]
}
```

Top-level fields:

| Field | Type | Meaning |
|-------|------|---------|
| `offset` | integer | The window start (the `--offset` value, or as set by `--around`). |
| `length` | integer | The effective window length. |
| `width` | integer | Bytes per row. |
| `ref` | integer or null | The `--ref` index, or null. |
| `files` | array of string | Display names (honors `--names`; `<stdin>` for stdin). |
| `paths` | array of string or null | Each entry exactly as given on the command line; `null` for a stdin (`-`) input. |
| `rows` | array | One entry per printed row. |

Each row:

| Field | Type | Meaning |
|-------|------|---------|
| `offset` | integer | Absolute offset of the row's first column. |
| `markers` | array of string | One of `==` / `!=` / `--` per column. Always present. |
| `files` | array | Per-file objects: `name` (string), `bytes` (array of integer 0-255 or `null` for missing), `ascii` (string). |

JSON is emitted as one complete object, so bound large machine-readable dumps
with `--offset` / `--length` / `--limit-rows`. Plain text streams rows as they
are rendered.

### 5.7 Empty output

When `--only-diff` removes every row (or the window contains nothing to display),
the text path prints `multihex: nothing to display for this range` to stderr and
exits 0. The JSON path emits an object with an empty `rows` array.

---

## 6. Search reference

Search is exact: it reports observed byte matches only. There are no wildcards,
no alignment, and no inference. In the batch CLI a `--search-*` flag
short-circuits the normal dump and prints match lines instead. The TUI and GUI
expose search interactively. All three reuse the same core engine.

Batch search is its own output mode, not JSON or a filtered dump. When
`--search-text` or `--search-hex` is present:

- `--json` is ignored; output is match lines, not a JSON object.
- `--offset`, `--length`, and `--around` are validated but do not restrict search
  or context rows; search uses a full-file model starting at offset 0.
- `--ref` is not validated and has no effect in search mode.
- `--only-diff`, `--limit-rows`, `--color`, `--byte-classes`, and `--overlay` do
  not affect search output. A non-positive `--limit-rows` is still rejected before
  search runs.
- `--width` controls context-row width. `--names`, `--ascii`, `--layout`, and
  `--markers` affect context rows and match-line names.
- `--search-context` is validated only when a search mode is active.

### 6.1 Query model

Two modes that never overlap:

- Text search matches the literal UTF-8 bytes of the string.
- Hex search matches the byte values of the hex pattern.

So `--search-hex D9` looks for the single byte `0xd9`, not ASCII `"D9"` (bytes
`44 39`). To find ASCII `"D9"`, use `--search-text D9`.

Hex pattern parsing (`parse_hex_pattern`): tokens may be separated by whitespace,
`:`, `-`, or `,`, and each token may carry an optional `0x` prefix. All of these
are equal: `"DE AD BE EF"`, `"deadbeef"`, `"0xDE 0xAD 0xBE 0xEF"`,
`"DE:AD:BE:EF"`, `"de-ad-be-ef"`, `"DE,AD,BE,EF"`. Hex is case-insensitive.
Errors (each reported clearly, never silently retried as text): empty input, an
odd number of hex digits, a non-hex character, or a bare `0x` token.

Case-insensitive text search (`--search-ignore-case`, or the TUI/GUI checkbox)
folds ASCII letters only (`A-Z` to `a-z`); other bytes match verbatim. Hex search
has no case toggle (it is always exact byte matching).

### 6.2 Ordering, overlap, and limits

Matches are ordered deterministically by `(file_index, offset)`. By default
matches are non-overlapping (each scan resumes past the previous match);
`--search-overlap` reports overlapping occurrences as well (for example `AA AA`
at offsets 0 and 1 in `AA AA AA`). `--search-max-results N` caps the total
returned, keeping the deterministic prefix.

### 6.3 Batch CLI search options

| Option | Value | Semantics |
|--------|-------|-----------|
| `--search-text TEXT` | string | Literal UTF-8 text. Mutually exclusive with `--search-hex`. |
| `--search-hex HEX` | hex pattern | Hex byte pattern. Mutually exclusive with `--search-text`. |
| `--search-ignore-case` | flag | Case-insensitive text search (ASCII letters). Applies to text mode only. |
| `--search-file INDEX_OR_NAME` | index or name | Restrict to one file. Resolves a 0-based index, then a display name, path, or basename. No match is an error (exit 1). |
| `--search-context N` | integer >= 0 | Print `N` full-file comparison rows above and below each match. `0` prints match lines only (same as omitting). Negative is an error when search mode is active. |
| `--search-max-results N` | integer >= 1 | Stop after `N` matches. `< 1` is an error. |
| `--search-overlap` | flag | Also report overlapping matches. |

### 6.4 Batch CLI search output

One line per match:

```
file=0 path=a.bin offset=0x0000000d len=4 match=de ad be ef ascii="...."
```

Fields: `file` (0-based index), `path` (display name, honoring `--names`),
`offset` (8-hex), `len` (byte length), `match` (matched bytes as spaced hex),
`ascii` (the matched bytes through the gutter rules). With `--search-context N`,
each match is followed by `N` rows of context on each side, rendered as plain
comparison rows from the full-file grid (honoring `--names`, `--ascii`,
`--layout`, `--markers`, and `--width`); the context rows are not colored and do
not highlight the match. A blank line
separates context blocks.

```bash
multihex --search-hex deadbeef --search-context 1 a.bin
```

```
file=0 path=a.bin offset=0x0000000d len=4 match=de ad be ef ascii="...."
0x00000000  a.bin  52 49 46 46 00 01 02 03 4d 41 47 49 43 de ad be  |RIFF....MAGIC...|
                   == == == == == == == == == == == == == == == ==
0x00000010  a.bin  ef -- -- -- -- -- -- -- -- -- -- -- -- -- -- --  |.               |
                   == -- -- -- -- -- -- -- -- -- -- -- -- -- -- --
```

When there are no matches, `multihex: no matches for '<pattern>'` is written to
stderr and the command exits 0.

### 6.5 Interactive search (TUI and GUI)

The TUI and GUI build the same queries and highlight matches in place. The
current match is highlighted most strongly. TUI search styling is current match >
other match > non-SAME marker (including missing columns) > overlay > byte class;
GUI styling is missing byte > current match > other match > diff > overlay > byte
class. See [section 7](#7-multihex-tui-reference) and
[section 8](#8-multihex-gui-reference) for keys and dialogs. Interactive search
always scans full files (independent of any display window), so a match anywhere
gets a row to navigate to.

---

## 7. multihex-tui reference

```
multihex-tui [OPTIONS] FILE [FILE ...]
```

Interactive Textual viewer. Requires the `[tui]` extra. If `textual` is not
installed, it prints an install hint and exits 2.

### 7.1 Startup flags

| Option | Value | Default source | Notes |
|--------|-------|----------------|-------|
| `--offset N` | integer | `0` | Start offset. |
| `--width N` | integer | config or `16` | Bytes per row. |
| `--ref INDEX` | index | unset | Pivot file. Out of range is a hard error (exit 2). |
| `--names basename\|path` | choice | config or `basename` | File-name mode. |
| `--only-diff` | flag | config or off | Start with only differing rows. |
| `--no-ascii` | flag | config or on | Start with the gutter hidden. |
| `--color auto\|always\|never` | choice | config or `auto` | Initial highlighting. |
| `--byte-classes` | flag | config or off | Start with byte-class highlighting on. |
| `--layout stacked\|side-by-side` | choice | config or `stacked` | Initial layout. |
| `--markers single\|repeat\|none` | choice | config or `single` | Initial marker display. |
| `--overlay PATH` | path | unset | Load an overlay at startup. Never persisted. |
| `--config PATH` | path | default path | Load settings from `PATH` and make it the save target. |
| `--no-config` | flag | off | Ignore any config file; start from built-in defaults plus CLI args. |

`--config` and `--no-config` are mutually exclusive. A value flag that is not
passed defers to the config file, then to the built-in default (see
[7.5](#75-configuration)). The TUI has no `--length`, `--limit-rows`, `--around`,
`--json`, or batch search flags.

### 7.2 Keybindings

The keymap comes from `shortcuts.py` and is enforced against the live bindings by
`tests/test_shortcuts.py`.

| Key | Action |
|-----|--------|
| `q` | quit |
| `j` / `Down` | next row |
| `k` / `Up` | previous row |
| `PageDown` | next page |
| `PageUp` | previous page |
| `Home` | jump to the start of the range (honors `--offset`) |
| `End` | jump to the last page (bottom-anchored) |
| `g` | jump to an offset (prompt) |
| `r` | choose the reference file (index, or `a`/`all` for all-agree) |
| `a` | toggle the ASCII gutter |
| `d` | toggle only-diff rows |
| `c` | toggle color / highlighting |
| `t` | toggle byte-class highlighting |
| `v` | cycle layout (stacked / side-by-side) |
| `m` | cycle markers (single / repeat / none) |
| `l` | load or change the layout overlay (blank path clears) |
| `L` | view the current overlay (then `c` clears, any other key closes) |
| `Left` / `Right` | scroll horizontally (when a row exceeds the viewport) |
| `o` | open the settings / options pane |
| `/` | text search (panel has a case-insensitive ASCII checkbox) |
| `x` | hex search (matches byte values, not ASCII text) |
| `n` | next match |
| `N` / `p` | previous match |
| `h` / `?` | help |

Horizontal scroll (`Left`/`Right`) moves 8 characters per press and engages
whenever a row is wider than the viewport (a wide `--width` in stacked, or a
side-by-side row); it is a clamped no-op when the row already fits. The `c` toggle
flips the render color state independently of the
persisted `color` mode; turning color off also hides byte-class and overlay
highlighting.

### 7.3 Status lines

The bottom status line shows: the visible offset range and row position
(`row M/total`), the active reference (`all-agree` or a file name), the toggle
states (`ascii diff color classes layout markers`), an `overlay:on`/`overlay:err`
indicator when an overlay is loaded, and per-file sizes.

A second search line appears only while a search is active. It shows the mode and
pattern (text searches append `(ci)` when case-insensitive), and either
`no matches` or `match M/total | file F | offset 0xNNNNNNNN`. A query error shows
`Search error: <message>`.

### 7.4 Search behavior

`/` opens a text-search panel with an input and a "Case-insensitive (ASCII)"
checkbox; submit dismisses with the text and the checkbox state. Tab moves to the
checkbox, Space toggles it, Escape cancels. The checkbox state is remembered for
the session (it re-seeds the panel) but is not persisted to config. `x` opens a
hex prompt with no case control. Running a search jumps to the first match;
`n` / `N` / `p` step matches and re-center. If only-diff is on and a match's row
is not a differing row, navigation snaps to the nearest visible row while the
search line still reports the exact match offset.

### 7.5 Configuration

The TUI loads persistent display preferences from a TOML file. The batch CLI
never reads it.

Path discovery: `$XDG_CONFIG_HOME/multihex/tui.toml` when `XDG_CONFIG_HOME` is set
and non-empty, otherwise `~/.config/multihex/tui.toml`. `--config PATH` overrides
both and becomes the save target.

Precedence, lowest to highest: built-in defaults, config file, command-line
options, interactive changes. CLI flags always win over the file; interactive
changes affect only the running session unless saved.

The settings pane (`o`) shows the effective settings and the active config path.
`Up`/`Down` (or `k`/`j`) select a row, `Left`/`Right` change a value (applied
immediately to the live view), `s` saves to the active path, `S` saves to a
prompted path, `Esc` closes. Closing alone never writes. Saving writes a complete
document (every setting, even defaults), so preferences survive future default
changes.

Persisted document shape (`config_version` is the schema version, currently 1,
independent of the application version):

```toml
config_version = 1
multihex_version = "0.1.0"

[display]
layout = "stacked"        # stacked | side-by-side
ascii = true
byte_classes = false
color = "auto"            # auto | always | never
names = "basename"        # basename | path
markers = "single"        # single | repeat | none

[view]
width = 16
only_diff = false
```

Load validation and warnings (warnings are never fatal, are printed to stderr
before launch and shown as in-app toasts):

| Condition | Behavior |
|-----------|----------|
| File absent | Normal; use defaults silently. |
| Unreadable / unparseable | Ignore the whole file; warn. |
| Missing `config_version` | Ignore the whole file; warn. |
| `config_version` not an integer, or greater than 1 | Ignore the whole file; warn. |
| Unknown top-level key, or unknown key in `[display]`/`[view]` | Ignore that key; warn. |
| `[display]` or `[view]` not a table | Ignore that table; warn. |
| Invalid value for a known key | Drop it (keep the lower-precedence value); warn. |

Never persisted (this is preferences, not session restore): the reference file,
current offset, scroll position, search string, current match, the text-search
case-insensitive preference, the overlay path, and the file list.

---

## 8. multihex-gui reference

```
multihex-gui [OPTIONS] [FILE ...]
```

Read-only PySide6/Qt desktop viewer. Requires the `[gui]` extra. If `PySide6` is
not installed, it prints an install hint and exits 2. The view scrolls vertically
and horizontally; wide rows get a horizontal scrollbar instead of clipping.

On Linux/X11 the Qt `xcb` plugin may need `libxcb-cursor.so.0`. When a preflight
check detects it is missing, the GUI prints an install hint (for example
`sudo apt install libxcb-cursor0`) and exits 2.

### 8.1 Startup flags

| Option | Value | Default | Notes |
|--------|-------|---------|-------|
| `--offset N` | integer | `0` | Start offset. Negative exits 2. |
| `--width N` | integer | `16` | Bytes per row. `< 1` exits 2. Changeable at runtime via View > Options. |
| `--ref INDEX` | index | unset | Pivot file. Out of range is NOT fatal: it is coerced to "no reference" and a warning is printed to stderr. |
| `--names basename\|path` | choice | `basename` | File-name mode. |
| `--only-diff` | flag | off | Start with only differing rows. |
| `--no-ascii` | flag | on | Start with the gutter hidden. |
| `--markers single\|repeat\|none` | choice | `single` | Initial marker text: `single`, `repeat` (repeat the strip under each segment in side-by-side; same as `single` when stacked), or `none`. Cycle at runtime with `m`. |
| `--layout stacked\|side-by-side` | choice | `stacked` | Initial layout. `side-by-side` lays the files out horizontally; cycle at runtime with `v`. |
| `--overlay PATH` | path | unset | Load an overlay at startup; needs files on the command line too, otherwise a stderr note is printed and the overlay is skipped. Never persisted. |

The GUI has no `--color` or `--byte-classes` flags; those are runtime-only (View
menu / keys). Color starts on.

### 8.2 Menus

| Menu | Items |
|------|-------|
| File | Open (`Ctrl+O`), Quit (`Ctrl+Q`) |
| View | ASCII gutter, Only differing rows, Side-by-side layout, Markers (Single / Repeat / None), Color highlighting, Byte-class highlighting, Options, File names (Basename / Full path) |
| Navigate | Jump to offset (`Ctrl+G`), Go to start (`Ctrl+Home`), Go to end (`Ctrl+End`) |
| Search | Find text (`Ctrl+F`), Find hex, Next match, Previous match |
| Compare | Choose reference (dialog), All agree (no reference), then one radio item per file |
| Overlay | Load/change overlay, Clear overlay, View current overlay |
| Help | Keyboard shortcuts |

Menu items also display their single-key shortcuts (`a`, `d`, `v`, `m`, `c`, `t`,
`o`, `x`, `n`, `N`, `r`, `l`, `L`, `h`) as hint text; the keys themselves are
dispatched by the shared registry, not by Qt shortcuts.

### 8.3 Single-key shortcuts

The GUI shares the full TUI keymap through `shortcuts.py` (no frontend-exclusive
entries remain). The shared keys behave as in [7.2](#72-keybindings) with these GUI
specifics:

- `v` cycles the layout (stacked / side-by-side); `m` cycles the marker mode
  (single / repeat / none); `Left` / `Right` scroll a wide row horizontally by 8
  columns (a no-op when the row fits).
- `l` / `L` manage the overlay via dialogs; `o` opens an apply-immediately options
  dialog (display toggles, layout, markers, file-name mode, and bytes-per-row) with
  no persistence (the GUI has no config file).
- `h` / `?` shows the keyboard-shortcut dialog (a scrollable text report).

Named keys (Down, PageUp, Home, End) are dispatched by key code; printable keys by
character. While a modal dialog (search, jump, reference) holds focus, single-key
shortcuts do not fire.

### 8.4 Mouse and scrolling

Vertical scrollbar, plus the mouse wheel (about three rows per notch; trackpad
pixel deltas always move at least one row). The horizontal scrollbar appears as
needed: a row wider than the viewport (a large `--width`, or a `side-by-side` row)
scrolls instead of clipping, and `Left` / `Right` move it 8 columns per press.

### 8.5 Rendering and status bar

The view paints only the visible blocks (it never renders the whole range into a
buffer), so it stays light on large files. Block layout mirrors the CLI/TUI: in
`stacked`, the offset gutter on the first file line, one `name  hex  |ascii|` line
per file, then the optional marker strip; in `side-by-side`, all files joined
horizontally across one row (the painter's columns match `core.render_row_text`).

Color scheme (whole-column, like the TUI): the offset gutter is blue; a column
whose marker is not SAME is red; missing cells and the `==`/`--` markers are dim
(so the red `!=` stands out); the reference file's name is emphasized. Search
matches fill a background (current match stronger) with dark glyphs. Overlay
ranges fill a distinct background on covered SAME cells, and byte classes are the
lowest tier. Cell priority: missing > current match > other match > diff >
overlay > byte class > normal. Accents come in light and dark sets, chosen from
the widget palette, so the view follows the system theme. The hex view uses the
platform's fixed-pitch font; UI chrome stays in the proportional system font.

The status bar is segmented: visible offset range and row position, reference
mode, the `ascii diff markers color classes layout` toggles, overlay state (name,
range count, warning/error tint — persistent while an overlay is loaded), and
per-file sizes. An active search keeps its own persistent segment (query, match
position,
file and offset of the current match, or `no matches` / the error); transient
notices (overlay summary toasts) appear briefly in the message area. The window
title shows the loaded file names.

### 8.6 File reload behavior

Opening new files rebuilds the model and the Compare menu, drops any loaded
overlay (it was validated against the previous files), and clears any search
results. Note: File > Open re-applies the startup `--ref`, not the last
Compare-menu choice.

---

## 9. Comparison and markers reference

- Any number of files >= 1. With one file every column is `==` (it equals
  itself), so the tool still renders bytes and the gutter.
- Markers are computed per column by `HexModel._markers()`; see
  [section 2](#markers-and-the-pivot).
- `--ref INDEX` sets the pivot to file `INDEX`. In the batch CLI it also enables
  per-cell red highlighting of bytes that differ from the reference. In the TUI
  and GUI it is selectable at runtime (`r`, or the Compare menu) and `all-agree`
  restores the no-reference pivot.
- `--only-diff` keeps only rows with at least one non-SAME column. In the TUI and
  GUI this is a runtime toggle; switching the reference rebuilds the filtered set.
- `--limit-rows N` (batch CLI only) caps printed rows after filtering.
- Missing bytes render `--` in hex and a space in the gutter, and force the
  column marker to `--`.
- The batch CLI colors individual differing cells; the TUI and GUI color whole
  columns by marker state. This difference is intentional and is not unified.

---

## 10. Layout overlay reference

A layout overlay is a `bintools.layout-overlay` v1 JSON file: a resolved list of
byte ranges for one binary. It is a read-only annotation layer, not a format
grammar. `multihex` loads it, validates it, reports diagnostics, and highlights
the covered byte ranges.

### 10.1 Load and apply contract

`OverlayState.load(path, files)` reads the JSON and runs the validator:
`validate_structural` once, plus `validate_file_aware` per loaded file (only when
the document already identifies itself as this schema). The validator is the
single source of truth for severities.

- An overlay is "applicable" only when it loaded and has no error-severity
  diagnostic anywhere (structural or per-file). Highlighting happens only when
  applicable.
- An overlay with any error-severity diagnostic is reported but not applied; the
  comparison still renders.
- An overlay with only warnings is applied; warnings are summarized, with full
  detail in "view current overlay".

Highlighting sits below missing/diff and search styling, needs color on, and has
no effect on `--json` (in `--json` mode the batch CLI does not load the overlay at
all). Overlay paths are never persisted to config.

What `multihex` highlights and what it ignores:

- It highlights every byte covered by any range of an applicable overlay, using
  one uniform highlight. It does NOT vary the highlight by `status`, `kind`, or
  `type`. A range whose `status` field is `"error"` (a validation status, not a
  diagnostic) still highlights.
- A zero-length range covers no byte and never highlights.
- Out-of-bounds and overlapping ranges never crash range lookup.
- The overlay file's own `diagnostics` array (producer-emitted) is validated only
  for being an array; its contents are not read or displayed. Only the validator's
  own diagnostics are surfaced.
- Unknown top-level and range fields are ignored. They do not produce diagnostics
  and do not affect rendering.

### 10.2 Top-level fields

| Field | Required | Type | Notes |
|-------|----------|------|-------|
| `schema` | yes | object | Identity block; see below. |
| `ranges` | yes | array | The byte ranges; may be empty. |
| `name` | no | string | Human label for the overlay. |
| `source_file` | no | string | Advisory file name. Type-checked only; not compared to anything by the validator. |
| `source_size` | no | integer >= 0 | If present and it disagrees with the loaded file size, warning `source-size-mismatch`. |
| `source_sha256` | no | string | Must be 64 lowercase hex digits (else error `bad-field`). If present and it disagrees with the file hash, warning `source-sha256-mismatch`. |
| `diagnostics` | no | array | Must be an array if present (else error `bad-diagnostics`). Contents are otherwise ignored by the validator and by multihex viewers. |

`schema` block:

| Field | Required | Type | Notes |
|-------|----------|------|-------|
| `name` | yes | string | Must equal `"bintools.layout-overlay"`. A wrong or missing schema object is error `missing-schema`; a wrong name is error `wrong-schema-name`. File-aware checks are skipped unless this name matches. Structural checks may still continue so authors see additional shape errors. |
| `version` | yes | integer | Must equal `1`. Non-integer or bool is error `missing-schema-version`; any other integer is error `unsupported-version`. |

### 10.3 Range fields

| Field | Required | Type | Allowed / notes |
|-------|----------|------|-----------------|
| `offset` | yes | integer >= 0 | Else error `bad-offset`. JSON bools are rejected. |
| `length` | yes | integer >= 0 | `0` permitted (zero-width marker). Else error `bad-length`. JSON bools are rejected. |
| `label` | no | string | Human name. Not type-checked by the validator; viewers use it only when it is a string. Viewer display falls back to `path`, then a generic label. |
| `path` | no | string | Dotted segments, each `ident` with optional `[n]`, for example `header.records[0].id`. Must match the grammar (else error `bad-path`) and be unique within `ranges` (else error `duplicate-path`). |
| `kind` | no | string | Open vocabulary. Not type-checked by the validator; viewers copy it only when it is a string. Advisory only. |
| `type` | no | string | Recognized set below; an unrecognized string is warning `unknown-type` (treated as opaque bytes); a non-string is error `bad-type`. |
| `decoded` | no | string / number / bool | Else error `bad-decoded`. An integer above 2^53 - 1 is warning `unsafe-integer`. |
| `raw_hex_preview` | no | string | Lowercase, even number of hex digits, else warning `malformed-hex`. Compared to file bytes when in bounds and lengths match. |
| `expected_hex` | no | string | Same hex-form check as above. NOT compared to file bytes. |
| `status` | no | string | One of `ok`, `warning`, `error`, `unchecked` (default `unchecked`). Other values are error `bad-status`. |
| `diagnostics` | no | any | Range-level producer diagnostics are not validated or surfaced by multihex. |

Recognized `type` values: `u8`, `u16le`, `u16be`, `u32le`, `u32be`, `u64le`,
`u64be`, `bytes`, `ascii`, `utf8`. The scalar subset (used by the zero-length
scalar check) is the seven `uN` widths.

Zero-length rules: for `length: 0`, a non-empty `raw_hex_preview` or
`expected_hex` is error `zero-length-bytes`, and a scalar `type` is warning
`zero-length-scalar`.

`raw_hex_preview` whose decoded byte length does not match `length` (for non-zero
length) is warning `preview-length-mismatch`.

Viewer range parsing keeps only ranges with valid non-negative integer `offset`
and `length`. A malformed overlay with structural errors can therefore still show
well-formed ranges in "view current overlay", but it is not applicable and does
not highlight until all error-severity diagnostics are gone.

### 10.4 File-aware checks

These run only when a binary is loaded and `schema.name` matches:

| Check | Diagnostic | Severity |
|-------|------------|----------|
| `source_size` not equal to actual file size | `source-size-mismatch` | warning |
| `source_sha256` not equal to the file's SHA-256 | `source-sha256-mismatch` | warning |
| `offset + length` exceeds file size | `range-out-of-bounds` | warning |
| `raw_hex_preview` disagrees with actual bytes (when in bounds, valid hex, matching length) | `raw-preview-mismatch` | warning |

An out-of-bounds range's bytes are not compared (the byte check is skipped).

### 10.5 Per-frontend overlay UX

- Batch CLI: `--overlay PATH`. The summary and any diagnostic lines print to
  stderr (`multihex: <summary>` then `multihex:   <diagnostic>`); covered bytes
  get a blue background in the hex view. No effect under `--json`.
- TUI: `--overlay PATH` at startup, `l` to load or change (blank clears), `L` to
  view current overlay (then `c` clears). Covered bytes use `on blue`. The status
  line shows `overlay:on` or `overlay:err`.
- GUI: `--overlay PATH` (with files), or the Overlay menu (load/change, clear,
  view). Diagnostics surface as a status-bar summary plus a dialog for warnings or
  errors. Covered bytes use a teal cell color. Opening new files drops the overlay.

### 10.6 Complete annotated example

The following commands create a 33-byte fictional QPX telemetry frame and a
matching overlay. The layout deliberately uses unaligned offsets, mixed
endianness, varied field widths, and a zero-length marker. The overlay validates
cleanly both structurally and file-aware against the generated binary.

```bash
python3 - <<'PY'
from pathlib import Path

Path("qpx-frame.bin").write_bytes(bytes.fromhex(
    "a57e"                  # sync preamble
    "04"                    # version
    "0003"                  # record_count, u16be
    "a0"                    # flags
    "78563412"              # packet_id, u32le
    "fa00"                  # temperature_tenths_c, u16le
    "0000018f2bc3abcd"      # sequence, u64be
    "09"                    # payload length
    "dead0020417f805510"    # payload
    "010203"                # check bytes
))
PY

cat > qpx-frame.overlay.json <<'JSON'
{
  "schema": { "name": "bintools.layout-overlay", "version": 1 },
  "name": "qpx telemetry frame example",
  "source_file": "qpx-frame.bin",
  "source_size": 33,
  "source_sha256": "dc3bdef95c724adf922d25edc5344bd1b0e8fc517017b9722411f309aed54cce",
  "ranges": [
    {
      "path": "sync.preamble",
      "offset": 0,
      "length": 2,
      "kind": "identifier",
      "label": "sync preamble",
      "type": "bytes",
      "raw_hex_preview": "a57e",
      "expected_hex": "a57e",
      "status": "ok"
    },
    {
      "path": "header.version",
      "offset": 2,
      "length": 1,
      "kind": "integer",
      "label": "format version",
      "type": "u8",
      "raw_hex_preview": "04",
      "decoded": 4,
      "status": "ok"
    },
    {
      "path": "header.record_count",
      "offset": 3,
      "length": 2,
      "kind": "count",
      "label": "record count",
      "type": "u16be",
      "raw_hex_preview": "0003",
      "decoded": 3,
      "status": "ok"
    },
    {
      "path": "header.flags",
      "offset": 5,
      "length": 1,
      "kind": "flags",
      "label": "capture flags",
      "type": "u8",
      "raw_hex_preview": "a0",
      "decoded": 160,
      "status": "warning"
    },
    {
      "path": "header.packet_id",
      "offset": 6,
      "length": 4,
      "kind": "integer",
      "label": "packet id",
      "type": "u32le",
      "raw_hex_preview": "78563412",
      "decoded": 305419896,
      "status": "ok"
    },
    {
      "path": "header.temperature_tenths_c",
      "offset": 10,
      "length": 2,
      "kind": "integer",
      "label": "temperature tenths C",
      "type": "u16le",
      "raw_hex_preview": "fa00",
      "decoded": 250,
      "status": "ok"
    },
    {
      "path": "header.sequence",
      "offset": 12,
      "length": 8,
      "kind": "timestamp",
      "label": "monotonic sequence",
      "type": "u64be",
      "raw_hex_preview": "0000018f2bc3abcd",
      "decoded": "1714426194893",
      "status": "ok"
    },
    {
      "path": "payload.length",
      "offset": 20,
      "length": 1,
      "kind": "length",
      "label": "payload length",
      "type": "u8",
      "raw_hex_preview": "09",
      "decoded": 9,
      "status": "ok"
    },
    {
      "path": "payload.bytes",
      "offset": 21,
      "length": 9,
      "kind": "payload",
      "label": "payload bytes",
      "type": "bytes",
      "status": "unchecked"
    },
    {
      "path": "trailer.check_bytes",
      "offset": 30,
      "length": 3,
      "kind": "checksum",
      "label": "check bytes",
      "type": "bytes",
      "raw_hex_preview": "010203",
      "expected_hex": "010203",
      "status": "ok"
    },
    {
      "path": "eof.marker",
      "offset": 33,
      "length": 0,
      "kind": "reserved",
      "label": "end marker",
      "status": "unchecked"
    }
  ],
  "diagnostics": []
}
JSON

python3 -m multihex.layout_overlay_v1 qpx-frame.overlay.json
python3 -m multihex.layout_overlay_v1 qpx-frame.overlay.json -b qpx-frame.bin
multihex --overlay qpx-frame.overlay.json --color always --length 33 qpx-frame.bin
```

Notes on the example:

| Path | Offset/length | Purpose |
|------|---------------|---------|
| `sync.preamble` | `0+2` | Byte identifier, checked by `raw_hex_preview` and `expected_hex`. |
| `header.record_count` | `3+2` | Big-endian scalar at an unaligned offset. |
| `header.packet_id` | `6+4` | Little-endian scalar. |
| `header.sequence` | `12+8` | Big-endian 64-bit scalar with `decoded` stored as a string. |
| `header.flags` | `5+1` | `status: "warning"` is a range status, not a validator warning; it still validates and renders with the same overlay color. |
| `payload.bytes` | `21+9` | No `raw_hex_preview`; the file remains authoritative. |
| `eof.marker` | `33+0` | Loaded and listed, covers no bytes, highlights nothing. |

### 10.7 The overlay validator CLI

`src/multihex/layout_overlay_v1.py` is runnable as a module:

```
python3 -m multihex.layout_overlay_v1 OVERLAY [-b BINARY] [--json]
```

| Option | Meaning |
|--------|---------|
| `OVERLAY` | Path to the overlay JSON (required). |
| `-b`, `--binary BINARY` | Optional binary for file-aware checks. |
| `--json` | Emit the diagnostics as a JSON array. |

Exit codes: `0` clean, `1` warnings only, `2` errors present or argparse usage
error, `3` the validator could not read or parse the overlay or binary. Without
`--json` it prints one `severity: code [path]: message` line per diagnostic, or
`ok: no diagnostics`.

---

## 11. Exit codes and diagnostics

### 11.1 Batch CLI (`multihex`)

| Code | Trigger |
|------|---------|
| `0` | Normal completion. Also: no search matches, "nothing to display", and a broken downstream pipe. |
| `1` | Runtime error reported as `multihex: <message>` on stderr: `--width < 1`, `--limit-rows < 1`, `--search-max-results < 1`, `--offset < 0`, `--length < 0`, `--search-context < 0`, `--ref` out of range, a malformed `--around`, an unreadable input file, `-` given more than once, an invalid search query, or `--search-file` matching no file. |
| `2` | argparse usage error (unknown flag, bad choice, missing positional, mutually-exclusive conflict). |

In batch search mode, invalid `--ref` is ignored because the search path returns
before reference validation. Invalid `--search-context` is only checked when a
search mode is active. Invalid `--width`, `--limit-rows`, `--search-max-results`,
`--offset`, `--length`, `--around`, inputs, and search queries are still errors.

### 11.2 multihex-tui

| Code | Trigger |
|------|---------|
| `0` | Normal exit. |
| `2` | `textual` not installed; an input file is unreadable; invalid model arguments (bad `--width`, negative `--offset`, out-of-range `--ref`); or an argparse usage error. |

Config-load problems are warnings, not failures: they print to stderr and appear
as in-app toasts, and the TUI still launches.

### 11.3 multihex-gui

| Code | Trigger |
|------|---------|
| `0` | Normal exit (Qt event loop returned 0). |
| `2` | `PySide6` not installed; `--width < 1`; `--offset < 0`; the `libxcb-cursor` preflight failed; or an argparse usage error. |
| other | Whatever `QApplication.exec()` returns. |

An out-of-range `--ref` is not fatal in the GUI: it is coerced to "no reference"
and a warning is printed to stderr. An unreadable file at startup prints to stderr
and shows a warning dialog but does not exit.

### 11.4 Overlay validator CLI

`0` clean, `1` warnings only, `2` validator errors or argparse usage errors, `3`
unreadable/unparseable overlay or unreadable binary. See
[10.7](#107-the-overlay-validator-cli).

---

## 12. File handling

- Real files are opened read-only and memory-mapped (`mmap`, `ACCESS_READ`), so a
  small window over a large file touches only the pages it reads. The mapping
  stays valid after the file descriptor is closed.
- Empty files cannot be memory-mapped and fall back to an empty buffer; they
  contribute only missing bytes (`--`).
- stdin (`-`, batch CLI only) is read fully into memory and labelled `<stdin>`.
- All frontends are read-only; `multihex` never modifies inputs.
- The byte grid never moves: a missing byte always renders `--` (hex) or a space
  (gutter). There is no alignment or resync.
- Plain text output streams row by row. JSON is one complete object. Bound large
  JSON or text dumps with `--offset` / `--length` / `--limit-rows`.
- TUI and GUI only-diff mode build a visible-row index by checking every row in
  the current model. This is correct but O(row count) when toggled or when the
  reference changes.

Known limitations (tracked in `TODO.md`):

- Case-insensitive text search copies the whole file once (an mmap cannot be
  case-folded in place). This is a documented cost.
- `--length` is independent of file size, and there is no upper bound on `--width`
  or `--length`; very large values cost time and memory proportional to the value.
  `--limit-rows` mitigates `--length` for the text path.
- A file truncated beneath a live read mapping can raise SIGBUS on access (an
  inherent `mmap` hazard).
- A FIFO or other non-regular input with no writer can block indefinitely on open.
- An all-matching search (for example searching `00` in an all-zero file)
  materializes every match; cap it with `--search-max-results`.
- A full-file absent-pattern search can fault every searched page into memory.
- The batch CLI handles broken downstream pipes cleanly, but other stdout/stderr
  write failures (for example `/dev/full`) are tracked as a known robustness gap.

---

## Appendix A: flag index

`C` = batch CLI, `T` = TUI, `G` = GUI. A blank cell means the flag is absent in
that frontend.

| Flag | C | T | G | Default | Notes |
|------|---|---|---|---------|-------|
| `--offset N` | yes | yes | yes | `0` | start offset |
| `--length N` | yes | | | min common | window length (CLI only) |
| `--width N` | yes | yes | yes | `16` | bytes per row |
| `--around OFF:N` | yes | | | | center a window (CLI only) |
| `--ref INDEX` | yes | yes | yes | unset | pivot; out-of-range fatal in C/T, non-fatal in G |
| `--only-diff` | yes | yes | yes | off | differing rows only |
| `--limit-rows N` | yes | | | unset | cap printed rows (CLI only) |
| `--ascii` / `--no-ascii` | yes | `--no-ascii` | `--no-ascii` | on | ASCII gutter |
| `--names basename\|path` | yes | yes | yes | `basename` | file-name mode |
| `--color auto\|always\|never` | yes | yes | | `auto` | color (GUI is runtime-only) |
| `--byte-classes` | yes | yes | | off | byte-class tint (GUI runtime-only) |
| `--layout stacked\|side-by-side` | yes | yes | yes | `stacked` | layout (cycle with `v`) |
| `--markers ...` | `single\|repeat\|none` | `single\|repeat\|none` | `single\|repeat\|none` | `single` | marker display |
| `--overlay PATH` | yes | yes | yes | unset | layout overlay |
| `--json` | yes | | | off | JSON output (CLI only) |
| `--search-text TEXT` | yes | | | | batch search (interactive in T/G) |
| `--search-hex HEX` | yes | | | | batch search (interactive in T/G) |
| `--search-ignore-case` | yes | | | off | text search, ASCII fold |
| `--search-file IDX_OR_NAME` | yes | | | | restrict search to one file |
| `--search-context N` | yes | | | | context rows around matches |
| `--search-max-results N` | yes | | | | cap matches |
| `--search-overlap` | yes | | | off | report overlapping matches |
| `--config PATH` | | yes | | default path | TUI config (TUI only) |
| `--no-config` | | yes | | off | ignore TUI config (TUI only) |

---

## Appendix B: key and menu index

### TUI keys

See [7.2](#72-keybindings). Summary: `q` quit; `j`/`k`/`Up`/`Down` rows;
`PageUp`/`PageDown` pages; `Home`/`End`; `g` goto; `r` ref; `a` ascii; `d`
only-diff; `c` color; `t` byte-classes; `v` layout; `m` markers; `l`/`L` overlay;
`Left`/`Right` horizontal scroll; `o` settings; `/` text search; `x` hex search;
`n` next; `N`/`p` previous; `h`/`?` help.

### GUI keys

Same as the TUI minus `v` and `Left`/`Right`. Plus menu accelerators: `Ctrl+O`
open, `Ctrl+Q` quit, `Ctrl+G` jump, `Ctrl+Home`/`Ctrl+End` start/end, `Ctrl+F`
find text. See [section 8](#8-multihex-gui-reference).

---

## Appendix C: glossary

| Term | Definition |
|------|------------|
| Block | One offset row of the grid: the offset gutter, one line per file, and the optional marker strip. |
| Column | One byte position within a row, compared across all files. |
| Marker | The three-state per-column result `==` / `!=` / `--`. |
| Pivot | The byte every column is compared against (`column[0]`, or the `--ref` file's byte). |
| Missing byte | An offset past a file's end; renders `--` (hex) or a space (gutter) and forces a `--` column. |
| Window | The displayed offset range `[offset, offset + length)`. |
| Overlay | A `bintools.layout-overlay` v1 annotation layer of byte ranges for one file. |
| Applicable overlay | A loaded overlay with no error-severity diagnostic; only these highlight. |
| Byte class | A coarse value class (ZERO / WHITESPACE / PRINTABLE_ASCII / OTHER / MISSING) used for optional highlighting. |

---

## Appendix D: overlay diagnostic codes

Severities are fixed by the validator. An `error` makes the overlay non-applicable
(loaded but not highlighted); a `warning` does not.

| Code | Severity | Trigger |
|------|----------|---------|
| `not-an-object` | error | Top-level value is not a JSON object. |
| `missing-schema` | error | `schema` missing or not an object. |
| `wrong-schema-name` | error | `schema.name` is not `"bintools.layout-overlay"`. |
| `missing-schema-version` | error | `schema.version` is not an integer. |
| `unsupported-version` | error | `schema.version` is an integer other than 1. |
| `missing-ranges` | error | Top-level `ranges` absent. |
| `bad-ranges` | error | `ranges` is not an array. |
| `bad-range` | error | A `ranges` entry is not an object. |
| `bad-offset` | error | `offset` missing or not a non-negative integer. |
| `bad-length` | error | `length` missing or not a non-negative integer. |
| `bad-path` | error | `path` does not match the path grammar. |
| `duplicate-path` | error | `path` repeats within `ranges`. |
| `bad-status` | error | `status` not in the closed vocabulary. |
| `bad-type` | error | `type` present but not a string. |
| `bad-decoded` | error | `decoded` not a string, number, or bool. |
| `bad-field` | error | A top-level `name`/`source_file`/`source_size`/`source_sha256` has the wrong type, `source_size` is negative or bool, or `source_sha256` is not 64 lowercase hex digits. |
| `bad-diagnostics` | error | Top-level `diagnostics` present but not an array. |
| `zero-length-bytes` | error | A zero-length range carries a non-empty `raw_hex_preview` or `expected_hex`. |
| `unknown-type` | warning | `type` is a string outside the recognized set. |
| `malformed-hex` | warning | `raw_hex_preview` or `expected_hex` is not lowercase even-digit hex. |
| `unsafe-integer` | warning | `decoded` integer exceeds 2^53 - 1. |
| `zero-length-scalar` | warning | A scalar `type` on a zero-length range. |
| `preview-length-mismatch` | warning | `raw_hex_preview` byte length does not match `length`. |
| `range-out-of-bounds` | warning | `offset + length` exceeds the file size (file-aware). |
| `source-size-mismatch` | warning | `source_size` disagrees with the file size (file-aware). |
| `source-sha256-mismatch` | warning | `source_sha256` disagrees with the file hash (file-aware). |
| `raw-preview-mismatch` | warning | `raw_hex_preview` disagrees with file bytes (file-aware). |

---

## Appendix E: doc/code discrepancies found

The source survey found these discrepancies in existing prose or docstrings. This
manual documents the source behavior above; these items are listed for follow-up
in the older documents.

| Claim location | Source behavior |
|----------------|-----------------|
| `docs/layout-overlay-v1.md` says `source_file` mismatch can produce a diagnostic. | `validate_file_aware()` never compares `source_file`; it is type-checked only. |
| `docs/layout-overlay-v1.md` describes producer diagnostics as structured objects. | The validator only checks top-level `diagnostics` is an array; it does not validate diagnostic entries and does not check range-level `diagnostics`. |
| `docs/layout-overlay-v1.md` says wrong/missing `schema.name` means "do not parse" ranges. | The structural validator continues after schema errors to report additional shape diagnostics; file-aware checks are skipped and the overlay is not applicable. |
| Overlay prose lists `label` and `kind` as string fields. | The validator does not diagnose non-string `label`/`kind`; viewers use them only when they are strings. |
| Validator docstring/manual text described bad validator arguments as exit `3`. | `argparse` usage errors exit `2`; exit `3` is used for unreadable/unparseable overlay or unreadable binary. |
| README/architecture prose summarizes TUI/GUI search styling as `missing > current match > other match > diff`. | GUI follows that ordering. TUI applies search first, then non-SAME marker styling; missing columns are styled as non-SAME marker columns rather than a separate missing tier. |
| Existing docs did not spell out batch search mode ordering. | Search mode ignores `--ref` validation and normal dump/window/filter/JSON/overlay output, while still validating several startup flags before dispatch. |
