# multihex

> Side-by-side **fixed-offset** hex comparison of multiple binary files.

![Python](https://img.shields.io/badge/python-%E2%89%A53.9-blue)
![License](https://img.shields.io/badge/license-Apache--2.0-green)

`multihex` lines up several binary files at the **same byte offsets** and shows
you, byte for byte, where they agree and where they differ. It comes in two
flavors that share one comparison engine:

- **`multihex`** — a batch CLI for text, colorized, or JSON output (great for
  scripting and diffs in CI).
- **`multihex-tui`** — an interactive terminal viewer for scrolling, jumping, and
  searching through large files.

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

# For development (tests, linter, and the TUI):
pip install -e '.[dev]'
```

Installing provides two console scripts:

| Command        | Module             | Purpose                          |
| -------------- | ------------------ | -------------------------------- |
| `multihex`     | `multihex.cli`     | Batch / scriptable comparison    |
| `multihex-tui` | `multihex.tui`     | Interactive terminal viewer      |

You can also run them without installing:

```bash
python3 -m multihex.cli FILE1 FILE2
python3 -m multihex.tui FILE1 FILE2
```

## Quickstart

```bash
multihex a.bin b.bin
```

```text
0x00000000
  a.bin  52 49 46 46 00 01 02 03 4d 41 47 49 43 de ad be  |RIFF....MAGIC...|
  b.bin  52 49 46 46 00 01 02 03 6d 61 67 69 63 de ad 00  |RIFF....magic...|
         == == == == == == == == != != != != != == == !=
0x00000010
  a.bin  ef  |.|
  b.bin  00  |.|
         !=
```

Each block is one row of the offset grid:

- the **offset line** (`0x00000000`),
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
| `--ascii` / `--no-ascii`      | Show / hide the ASCII gutter (default on).                       |
| `--names basename` \| `path`  | Label files by basename (default) or full path.                  |
| `--color auto` \| `always` \| `never` | Colorize output. `auto` = on when stdout is a TTY. Honors `NO_COLOR`. |
| `--json`                      | Emit machine-readable JSON instead of text (implies no color).   |

In the batch CLI, color **reddens each individual cell that differs** from the
reference file's byte in that column, dims missing cells, and colors the marker
tokens (`==` green, `!=` red, `--` dim). *(The TUI colors whole columns instead —
the two schemes differ by design.)*

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
0x00000000
  a.bin  52 49 46 46 00 01 02 03 4d 41 47 49 43 de ad be  |RIFF....MAGIC...|
         == == == == == == == == == == == == == == == ==
0x00000010
  a.bin  ef -- -- -- -- -- -- -- -- -- -- -- -- -- -- --  |.               |
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
`--names basename|path`, `--only-diff`, `--no-ascii`, `--color auto|always|never`.

**Keys**

| Key            | Action                                |
| -------------- | ------------------------------------- |
| `q`            | quit                                  |
| `j` / `↓`      | next row                              |
| `k` / `↑`      | previous row                          |
| `PageDown`     | next page                             |
| `PageUp`       | previous page                         |
| `g`            | jump to an offset                     |
| `r`            | choose the reference file             |
| `a`            | toggle the ASCII gutter               |
| `d`            | toggle only-diff rows                 |
| `c`            | toggle color / highlighting           |
| `/`            | text search                           |
| `x`            | hex search                            |
| `n`            | next match                            |
| `N` / `p`      | previous match                        |
| `h` / `?`      | help                                  |

A status line shows the current offset range, row position, active reference,
toggle states, and file sizes; a second line appears during a search with the
match count and current match location.

The TUI colors **whole columns** by their marker state and highlights search
matches, with this priority: missing byte > current match > other match > diff
marker. The current match is highlighted more strongly than the rest.

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
- **Read-only.** `multihex` never modifies your files; both frontends are viewers.
- **Empty files** are handled (they simply contribute missing bytes / `--`).

## Developer documentation

If you want to work on or build against `multihex`:

- [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) — how the core and the two
  frontends fit together, and the invariants that must hold.
- [`docs/API.md`](docs/API.md) — the public `multihex.core` API for embedding the
  comparison/search engine in your own code.
- [`CONTRIBUTING.md`](CONTRIBUTING.md) — dev setup, tests, linting, golden files,
  and how to extend the tool.
- [`CHANGELOG.md`](CHANGELOG.md) — notable changes.

## License

Licensed under the [Apache License 2.0](LICENSE).
