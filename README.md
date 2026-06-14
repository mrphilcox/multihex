# multihex

> Side-by-side **fixed-offset** hex comparison of multiple binary files.

![Python](https://img.shields.io/badge/python-%E2%89%A53.9-blue)
![License](https://img.shields.io/badge/license-Apache--2.0-green)

`multihex` lines up several binary files at the **same byte offsets** and shows
you, byte for byte, where they agree and where they differ. It comes with three
frontends that share one comparison engine:

- **`multihex`** — a batch CLI for text, colorized, or JSON output (great for
  scripting and diffs in CI).
- **`multihex-tui`** — an interactive terminal viewer for scrolling, jumping, and
  searching through large files.
- **`multihex-gui`** — a read-only PySide6/Qt desktop viewer (first-pass MVP).

It is a **viewer and comparator, not an inference tool.** It shows what bytes are
present at each offset — it never tries to align, resynchronize, or guess the
structure of a file.

---

## Table of contents

- [What it is (and is not)](#what-it-is-and-is-not)
- [Install](#install)
- [Quickstart](#quickstart)
- [Core concept: fixed offsets and markers](#core-concept-fixed-offsets-and-markers)
- [The batch CLI (`multihex`)](#the-batch-cli-multihex)
  - [Options reference](#options-reference)
  - [JSON output](#json-output)
- [Searching](#searching)
- [The interactive TUI (`multihex-tui`)](#the-interactive-tui-multihex-tui)
- [The desktop GUI (`multihex-gui`)](#the-desktop-gui-multihex-gui)
- [Recipes](#recipes)
- [Semantics and limitations](#semantics-and-limitations)
- [Developer documentation](#developer-documentation)
- [License](#license)

---

## What it is (and is not)

**It is:** a tool to compare the byte values that live at *identical offsets*
across two or more files. Offset `0x40` in file A is only ever compared to offset
`0x40` in file B. This makes it ideal for comparing firmware images, file-format
variants, struct dumps, memory snapshots, and "almost identical" binaries.

**It is not:** a structural diff. There is no byte alignment, no resync after an
inserted byte, and no format inference. If you insert one byte near the start of a
file, every subsequent offset will read as different — which is exactly the truth
about the bytes, and exactly what `multihex` reports.

## Install

`multihex` requires **Python ≥ 3.9**. The core and batch CLI are **stdlib-only**.

```bash
# Core + batch CLI only (no third-party dependencies):
pip install .

# With the interactive TUI (adds textual + rich):
pip install '.[tui]'

# With the desktop GUI (adds PySide6):
pip install '.[gui]'

# For development (tests, linter, and the TUI):
pip install -e '.[dev]'

# For development with the desktop GUI launcher:
pip install -e '.[dev,gui]'
```

Installing provides three console scripts:

| Command        | Module             | Purpose                          |
| -------------- | ------------------ | -------------------------------- |
| `multihex`     | `multihex.cli`     | Batch / scriptable comparison    |
| `multihex-tui` | `multihex.tui`     | Interactive terminal viewer      |
| `multihex-gui` | `multihex.gui`     | Read-only desktop (Qt) viewer    |

From a checkout, you can also run them without installing by putting `src/` on
`PYTHONPATH`:

```bash
PYTHONPATH=src python3 -m multihex.cli FILE1 FILE2
PYTHONPATH=src python3 -m multihex.tui FILE1 FILE2
PYTHONPATH=src python3 -m multihex.gui FILE1 FILE2
```

## Quickstart

```bash
multihex a.bin b.bin
```

```text
0x00000000  a.bin  52 49 46 46 00 01 02 03 4d 41 47 49 43 de ad be  |RIFF....MAGIC...|
            b.bin  52 49 46 46 00 01 02 03 6d 61 67 69 63 de ad 00  |RIFF....magic...|
                   == == == == == == == == != != != != != == == !=
0x00000010  a.bin  ef  |.|
            b.bin  00  |.|
                   !=
```

Each block is one row of the offset grid:

- the **offset** (`0x00000000`) is a left gutter that rides the first file line;
  the block's remaining lines are indented under it so the offset and its bytes
  share a row,
- one **file line** per input: name, the hex bytes at that offset, and an ASCII
  gutter (`|...|`, non-printable bytes shown as `.`),
- a **marker line** aligned under the hex columns showing how the column compares.

## Core concept: fixed offsets and markers

Every column carries a three-state marker:

| Marker | Meaning                                                             |
| ------ | ------------------------------------------------------------------- |
| `==`   | every file has the same byte at this offset (matches the pivot)     |
| `!=`   | all bytes are present, but at least one differs from the pivot      |
| `--`   | at least one file has no byte here (the offset is past its end)     |

`--` always wins: if any file is missing a byte in a column, the column is `--`
regardless of the others. A missing byte also renders as `--` in the hex columns
and as a space in the ASCII gutter.

The **pivot** is what every byte is compared against:

- **No `--ref`** (default): the pivot is the *first* file's byte, so `==` means
  "all files agree."
- **`--ref INDEX`**: the pivot is the byte from file `INDEX` (0-based), so `==`
  means "matches the reference."

## The batch CLI (`multihex`)

```bash
multihex [OPTIONS] FILE1 [FILE2 ...]
```

By default it shows the largest range common to all files starting at offset 0,
16 bytes per row, with the ASCII gutter on and color when writing to a terminal.

Use `-` as an input file to read bytes from stdin (at most once). It is just
another input among possibly many, so it can be compared against files:

```bash
cat /path/to/binary.data | multihex -
cat /path/to/binary.data | multihex --byte-classes -
cat /path/to/binary.data | multihex --overlay /path/to/layout.json -
multihex - other.bin            # compare stdin against a file
```

A stdin input is labelled `<stdin>` regardless of `--names`, and its
`--json` `paths` entry is `null` (it has no filesystem path).

### Options reference

**Windowing**

| Option            | Description                                                                   |
| ----------------- | ----------------------------------------------------------------------------- |
| `--offset N`      | Start offset (default `0`). Accepts `0x40`, `64`, `0o100`, `0b1000000`.        |
| `--length N`      | Bytes to display (default: shortest remaining length common to all files).    |
| `--width N`       | Bytes per row (default `16`).                                                 |
| `--around OFF:N`  | Show `N` bytes centered on `OFF` (overrides `--offset`/`--length`).           |

**Comparison**

| Option          | Description                                                                |
| --------------- | ------------------------------------------------------------------------- |
| `--ref INDEX`   | Use this 0-based file as the comparison reference (see [markers](#core-concept-fixed-offsets-and-markers)). Also highlights cells that differ from the reference. |
| `--only-diff`   | Show only rows containing at least one differing or missing byte.         |
| `--limit-rows N`| Stop after `N` printed rows.                                              |

**Display**

| Option                        | Description                                                       |
| ----------------------------- | ---------------------------------------------------------------- |
| `--layout stacked` \| `side-by-side` | Human-readable layout (default `stacked`). `side-by-side` lays the files out horizontally (visual-only; no effect on `--json`). |
| `--markers single` \| `repeat` \| `none` | Marker-text display (default `single`). Separate from `--layout`; visual-only (no effect on `--json`). |
| `--ascii` / `--no-ascii`      | Show / hide the ASCII gutter (default on).                       |
| `--names basename` \| `path`  | Label files by basename (default) or full path.                  |
| `--color auto` \| `always` \| `never` | Colorize output. `auto` = on when stdout is a TTY. Honors `NO_COLOR`. |
| `--byte-classes`              | Highlight byte classes in the hex cells (visual-only; needs color on). |
| `--overlay PATH`              | Load a [layout-overlay-v1](docs/layout-overlay-v1.md) JSON annotation layer and highlight its byte ranges (visual-only; needs color on; no effect on `--json`). |
| `--json`                      | Emit machine-readable JSON instead of text (implies no color).   |

**Layout (`--layout`).** `stacked` (the default) keeps the familiar one-file-per-line
block. `side-by-side` instead places each file's hex (and ASCII gutter, if shown)
horizontally across the row, which makes it easy to compare the same offset across
files left-to-right. Layout is **visual-only**: it never affects offsets, bytes,
comparison markers, `--ref`, `--only-diff`, search, or `--json`. Side-by-side rows
are deliberately allowed to be wider than the terminal — let your terminal, pager,
or pipe handle wrapping. (The TUI adds horizontal scrolling instead; see below.)

**Marker display (`--markers`).** Controls how the column-marker strip (`==` / `!=`
/ `--`) is drawn — a concern kept **separate from `--layout`**:

- `single` (default) shows one marker strip per row/block. In `side-by-side` the
  strip is its own left prefix column (not attached to the first file, which would
  misleadingly imply the markers were that file's results).
- `repeat` repeats the strip under each file segment in `side-by-side` layout. In
  `stacked` layout it is identical to `single` (one strip already applies to all
  files, so repeating it would just add noise).
- `none` hides the marker text entirely.

`--markers` is **display-only**: it hides/positions text only and never changes
marker computation, `--only-diff` filtering, diff/missing highlighting, search, or
`--json` output (the JSON `markers` array is always present and unchanged).

### Large files

For large binaries, start with a bounded window rather than dumping the whole
common range:

```bash
multihex --offset 0x4000 --length 0x200 --limit-rows 32 a.bin b.bin
```

`--offset` chooses where inspection starts, `--length` caps the byte span, and
`--limit-rows` caps displayed rows after filtering. Plain text rows are streamed
as they are rendered; JSON is emitted as one complete object, so bounded windows
are especially important for machine-readable output.

In the batch CLI, color **reddens each individual cell that differs** from the
reference file's byte in that column, dims missing cells, and colors the marker
tokens (`==` green, `!=` red, `--` dim). *(Frontend color schemes differ by
design.)*

**Byte classes (`--byte-classes`).** A purely visual aid for spotting structure
while reverse engineering: when color is enabled it tints the hex byte cells by
value class — zero bytes (`0x00`) dim, ASCII whitespace (tab/LF/VT/FF/CR/space)
cyan, and printable ASCII (`0x21`–`0x7e`) green; all other bytes stay normal.
It is **disabled by default** and does not affect offsets, comparison markers,
`--only-diff`, `--ref`, search, or `--json` output. Existing missing/diff
styling always takes priority, so differences never become harder to see. With
`--color never` (or `--json`) it emits no color.

**Layout overlays (`--overlay PATH`).** A layout overlay is a
[`bintools.layout-overlay` v1](docs/layout-overlay-v1.md) JSON file: a resolved
list of byte ranges for one binary — a **read-only annotation layer**, not a
file-format grammar. multihex is a consumer: it loads the file, validates it,
prints a one-line summary plus any diagnostics to stderr, and highlights the
overlay's ranges in the hex view. The overlay's own validator is the source of
truth for what counts as an error vs a warning:

- An overlay with any **error**-severity diagnostic is reported but **not
  applied** (the comparison still renders).
- An overlay with only **warnings** is applied; the warnings are summarized
  (full detail is available via "view current overlay" in the TUI/GUI).

Highlighting is **visual-only** (needs color on, no effect on `--json`) and slots
in below missing/diff styling, so differences stay obvious. Overlay paths are
**not saved in config** in v1 — an overlay is specific to one file/session.

```bash
multihex --overlay header.overlay.json --color always firmware-a.bin firmware-b.bin
```

### JSON output

`--json` emits a single object describing the window and every row. This is the
stable, scriptable surface:

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

- Top level: `offset`, `length`, `width`, `ref`, `files` (display names),
  `paths` (as given on the command line), and `rows`.
- Each row: `offset`, a `markers` array (one token per column), and `files`, each
  with `name`, `bytes` (integers, or `null` for a missing byte), and `ascii`.

JSON is emitted as one complete object for compatibility. For very large files,
bound machine-readable dumps with `--offset`, `--length`, and/or `--limit-rows`;
plain text output streams rows as they are rendered.

## Searching

`multihex` can search the loaded files for an **exact** byte sequence and report
where it occurs. Search is exact by design: it reports *observed byte matches
only* — no wildcards, no alignment, no inference. A `--search-*` flag short-circuits
the normal comparison dump and prints match lines instead.

```bash
# Literal UTF-8 text:
multihex --search-text RIFF a.bin b.bin

# Hex pattern (spaces, ':', '-', ',' and optional 0x are all accepted):
multihex --search-hex "de ad be ef" a.bin
multihex --search-hex deadbeef a.bin
multihex --search-hex "DE:AD:BE:EF" a.bin
```

```text
file=0 path=a.bin offset=0x00000000 len=4 match=52 49 46 46 ascii="RIFF"
file=1 path=b.bin offset=0x00000000 len=4 match=52 49 46 46 ascii="RIFF"
```

Each match prints its file index, path, offset, byte length, the matched bytes,
and their ASCII rendering. Results are ordered by `(file, offset)`. When there are
no matches, a `multihex: no matches for '...'` note is written to **stderr**.

**Text vs. hex search.** The two modes never overlap: text search matches the
literal UTF-8 bytes of your string, while hex search matches the byte *values* of
your hex pattern. So `--search-hex D9` looks for the single byte `0xd9` — not the
ASCII text `"D9"` (which is bytes `44 39`). To find ASCII `"D9"`, use
`--search-text D9`; to find bytes `44 39`, use `--search-hex "44 39"`. Hex input
is case-insensitive (`D9`, `d9`, `0xD9` are equivalent); `--search-ignore-case`
applies to **text** search only (ASCII letters).

**Search options**

| Option                   | Description                                                            |
| ------------------------ | --------------------------------------------------------------------- |
| `--search-text TEXT`     | Search for literal UTF-8 text. Mutually exclusive with `--search-hex`. |
| `--search-hex HEX`       | Search for a hex byte pattern.                                        |
| `--search-ignore-case`   | Case-insensitive text search (ASCII letters only).                   |
| `--search-file IDX_OR_NAME` | Restrict the search to one file (0-based index, basename, or path). |
| `--search-context N`     | Print `N` comparison rows of context above and below each match.     |
| `--search-max-results N` | Stop after `N` matches.                                              |
| `--search-overlap`       | Also report overlapping matches (e.g. `AA AA` at offsets 0 and 1 in `AA AA AA`). Default is non-overlapping. |

With `--search-context`, each match is followed by the surrounding comparison
rows so you can see it in place:

```bash
multihex --search-hex deadbeef --search-context 1 a.bin
```

```text
file=0 path=a.bin offset=0x0000000d len=4 match=de ad be ef ascii="...."
0x00000000  a.bin  52 49 46 46 00 01 02 03 4d 41 47 49 43 de ad be  |RIFF....MAGIC...|
                   == == == == == == == == == == == == == == == ==
0x00000010  a.bin  ef -- -- -- -- -- -- -- -- -- -- -- -- -- -- --  |.               |
                   == -- -- -- -- -- -- -- -- -- -- -- -- -- -- --
```

## The interactive TUI (`multihex-tui`)

For exploring large files, the TUI gives you scrolling, paging, jump-to-offset,
live reference switching, and interactive search. It requires the `[tui]` extra
(`textual` + `rich`); if those aren't installed it prints a clear message and
exits.

```bash
multihex-tui a.bin b.bin
multihex-tui --offset 0x400 --width 16 *.bin
multihex-tui --ref 0 file*.bin
```

**Startup flags:** `--offset N`, `--width N`, `--ref INDEX`,
`--names basename|path`, `--only-diff`, `--no-ascii`, `--color auto|always|never`,
`--byte-classes` (start with byte-class highlighting on; toggle with `t`),
`--layout stacked|side-by-side` (start in the chosen layout; cycle with `v`),
`--markers single|repeat|none` (start with the chosen marker display; cycle with `m`),
`--overlay PATH` (load a [layout overlay](docs/layout-overlay-v1.md); manage with `l`/`L`),
`--config PATH` / `--no-config` (see [TUI configuration](#tui-configuration)).

**Keys**

| Key            | Action                                |
| -------------- | ------------------------------------- |
| `q`            | quit                                  |
| `j` / `↓`      | next row                              |
| `k` / `↑`      | previous row                          |
| `PageDown`     | next page                             |
| `PageUp`       | previous page                         |
| `Home`         | jump to the start of the range        |
| `End`          | jump to the final page (bottom-anchored) |
| `←` / `→`      | scroll horizontally (side-by-side)    |
| `g`            | jump to an offset                     |
| `r`            | choose the reference file             |
| `a`            | toggle the ASCII gutter               |
| `d`            | toggle only-diff rows                 |
| `c`            | toggle color / highlighting           |
| `t`            | toggle byte-class highlighting        |
| `v`            | cycle layout (stacked / side-by-side) |
| `m`            | cycle markers (single / repeat / none)|
| `l`            | load/change layout overlay (blank path clears) |
| `L`            | view current layout overlay (`c` clears)       |
| `o`            | open the settings / options pane      |
| `/`            | text search (panel has a case-insensitive toggle) |
| `x`            | hex search (matches byte values, not ASCII text)  |
| `n`            | next match                            |
| `N` / `p`      | previous match                        |
| `h` / `?`      | help                                  |

Layout works the same as in the batch CLI (`stacked` is the default; `side-by-side`
lays files out horizontally), and `v` cycles between them live. Because a
side-by-side row is usually wider than the viewport, the TUI scrolls horizontally
with `←` / `→`; vertical scrolling, paging, jump, reference switching, search, and
the ASCII/only-diff/color/byte-class toggles all keep working in both layouts.
Layout is visual-only and never changes comparison or search results.

A status line shows the current offset range, row position, active reference,
toggle states, and file sizes; a second line appears during a search with the
match count and current match location (text searches show `(ci)` when
case-insensitive).

Search works exactly like the batch CLI. The text-search panel (`/`) has a
**Case-insensitive (ASCII)** checkbox (Tab to it, Space toggles) so you can fold
ASCII letter case; the choice is remembered for the session. Hex search (`x`)
matches byte *values* and accepts upper- or lowercase hex digits, so `x` then
`D9` finds the byte `0xd9` rather than the ASCII text `"D9"`. To search for ASCII
text use text search; to search for raw bytes use hex search. Invalid hex shows a
clear error and never silently falls back to a text search.

The TUI colors **whole columns** by their marker state and highlights search
matches, with this priority: missing byte > current match > other match > diff
marker. The current match is highlighted more strongly than the rest. When
byte-class highlighting is on (`--byte-classes`, or the `t` toggle) it slots in
as the lowest tier — `… > diff marker > byte class` — so it never hides marker
or search highlighting. Pressing `c` (color off) hides byte-class colors too;
the on/off state is remembered independently.

### TUI configuration

The TUI can load persistent display preferences from
`~/.config/multihex/tui.toml`, or `$XDG_CONFIG_HOME/multihex/tui.toml` when
`XDG_CONFIG_HOME` is set. **These settings apply only to `multihex-tui`. The
batch CLI does not read the TUI config file, so scripted output stays explicit
and repeatable.**

Precedence is: **built-in defaults → config file → command-line options →
interactive changes**. Command-line flags always win over the config file, and
interactive changes affect only the running session unless you save them.

| Flag | Effect |
| ---- | ------ |
| `--config PATH`  | Load settings from `PATH` and make it the save target. |
| `--no-config`    | Ignore any config file; start from built-in defaults plus CLI args. Saving still works (it uses the default path). |

`--config` and `--no-config` are mutually exclusive.

Press `o` inside the TUI to open the **settings pane**. It shows the current
effective settings and the active config path; `↑`/`↓` move between rows,
`←`/`→` change a value (changes apply to the running view immediately), `s` saves
to the active path, `S` saves to a prompted path, and `Esc` closes. Saving
writes a **complete** file (every setting, even those at their defaults) so your
preferences survive even if defaults change in a future release.

**Persisted settings** (preferences / startup defaults only):

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

`config_version` is the config **schema** version (currently `1`), independent of
the application version. A config with a missing or newer `config_version`, or
with invalid values, is reported with a warning and falls back to the
lower-precedence value rather than failing; a missing config file is normal and
silent.

**Not persisted** — this is preferences, not session restore. The reference file
(`--ref`), current offset, scroll position, search string, current match, and the
file list are all per-session and are never written to the config.

## The desktop GUI (`multihex-gui`)

A read-only **PySide6/Qt** desktop viewer that reuses the same comparison engine as
the CLI and TUI (identical fixed-offset semantics and markers; no editing or
selection). It now mirrors the TUI's keyboard workflow — including search — and
requires the `[gui]` extra (`PySide6`); if it isn't installed the command prints a
clear message and exits.

On Linux/X11, Qt's `xcb` platform plugin may also require native system libraries.
If startup reports a missing `xcb` platform dependency such as `libxcb-cursor.so.0`,
install the OS package, for example on Debian/Ubuntu:

```bash
sudo apt install libxcb-cursor0
```

```bash
multihex-gui a.bin b.bin c.bin
multihex-gui --offset 0x10 --width 16 a.bin b.bin
multihex-gui --only-diff --ref 0 fw_v1.bin fw_v2.bin
multihex-gui                       # empty window; open files from the File menu
```

**Startup flags:** `--offset N`, `--width N`, `--ref INDEX`,
`--names basename|path`, `--only-diff`, `--no-ascii`, `--markers single|none`,
`--overlay PATH` (load a [layout overlay](docs/layout-overlay-v1.md); manage from
the **Overlay** menu).

The window has a menu bar (**File** ▸ Open/Quit, **View** ▸ ASCII gutter /
only-diff / markers / colour / byte-classes / file-name mode / options, **Navigate**
▸ jump-to-offset and start/end, **Compare** ▸ reference file incl. *all-agree*,
**Overlay** ▸ load/change, clear, and view current layout overlay, **Search** ▸
find text/hex and next/previous, **Help** ▸ keyboard shortcuts), a custom comparison
view that paints only the visible rows (so it stays light on large files), and a
status bar showing the visible offset range, row position, reference mode, toggle
states, and file sizes. The block layout mirrors the CLI/TUI: an offset line, one
`name  hex  |ascii|` line per file, then the marker strip; columns that differ (or
are missing) are highlighted, and missing bytes render as `--`.

The GUI currently has vertical scrolling only. Very wide rows can be clipped on
the right; use a smaller `--width`, or use the CLI/TUI when you need horizontal
inspection of wide rows.

**Keyboard shortcuts mirror the TUI** (the keymap and on-screen help for the TUI
and GUI come from one shared registry, `src/multihex/shortcuts.py`, so they cannot
drift). Press `h` or `?` for the in-app list. Navigate with `j`/`k` or `↑`/`↓`,
`PageUp`/`PageDown`, `Home`/`End`, the scrollbar, or the mouse wheel; `g` jumps to an
offset and `r` picks the reference file. Toggle the display with `a` (ASCII gutter),
`d` (only-diff), `m` (marker strip), `c` (colour), and `t` (byte classes); `o` opens
an options dialog; `l`/`L` manage the overlay. Search with `/` (text, with a
case-insensitive ASCII option) and `x` (hex, matching byte values), then step matches
with `n` and `N`/`p` — the current match is highlighted most strongly, with the same
priority as the TUI (missing > current match > other match > diff). Search reuses the
core engine; the GUI only renders and navigates. The two TUI-only shortcuts are `v`
(layout cycle) and `←`/`→` (horizontal scroll), which pair with the side-by-side
layout the GUI does not yet implement.

**Layout overlays** work as in the CLI/TUI: the **Overlay** menu loads/changes,
clears, and views a [layout-overlay-v1](docs/layout-overlay-v1.md) annotation
layer. Diagnostics surface in the status bar (summary) and a dialog (full detail);
an overlay with errors is reported but not applied, and overlay paths are not saved
in config. Loading new files drops a previously loaded overlay (its validation was
file-specific).

Selection/copy, editing, persistent settings, a side-by-side layout, and a
search results-summary panel are tracked as later phases in `TODO.md`.

## Recipes

```bash
# Compare two firmware images and show only the rows that differ,
# measuring everything against the first image:
multihex --only-diff --ref 0 fw_v1.bin fw_v2.bin

# Inspect a 128-byte window around a header field:
multihex --around 0x40:0x80 *.bin

# Find a magic number across a directory of files:
multihex --search-hex "89 50 4e 47" *.bin

# Locate a header string and see it in context:
multihex --search-text "Content-Type" --search-ignore-case --search-context 2 dump.bin

# Diff two files programmatically (exit/inspect with jq):
multihex --json a.bin b.bin | jq '.rows[] | select(.markers | index("!="))'
```

## Semantics and limitations

- **Fixed offsets only.** No alignment, resync, or inference — by design and
  guaranteed not to change.
- **Exact search only.** No wildcards. Case-insensitive text search folds ASCII
  letters only (`A–Z` ↔ `a–z`); other bytes are matched verbatim.
- **Case-insensitive search cost.** Because memory-mapped files cannot be
  case-folded in place, `--search-ignore-case` copies the whole file once. This is
  a known, documented trade-off.
- **Read-only.** `multihex` never modifies your files; all three frontends are viewers.
- **Empty files** are handled (they simply contribute missing bytes / `--`).

## Developer documentation

If you want to work on or build against `multihex`:

- [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) — how the core and frontends fit
  together, and the invariants that must hold.
- [`docs/API.md`](docs/API.md) — the public `multihex.core` API for embedding the
  comparison/search engine in your own code.
- [`docs/TESTING.md`](docs/TESTING.md) — test layers, the full-suite runner, and
  the performance opt-in policy.
- [`CONTRIBUTING.md`](CONTRIBUTING.md) — dev setup, tests, linting, golden files,
  and how to extend the tool.
- [`CHANGELOG.md`](CHANGELOG.md) — notable changes.

## License

Licensed under the [Apache License 2.0](LICENSE).
