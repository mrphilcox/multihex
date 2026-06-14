# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this project is

`multihex` is a Python tool for side-by-side fixed-offset hex comparison of multiple binary files. It is a `src/`-layout package (`src/multihex/`) with two console-script frontends sharing one core:

- `src/multihex/core.py` — stdlib-only shared logic: file loading, `HexModel`/`Row` dataclasses, `Marker` enum, cell formatting, exact search, and `classify_byte()`/`ByteClass` (display-only byte classification)
- `src/multihex/cli.py` — batch CLI frontend (text/JSON output, ANSI color); console script `multihex`
- `src/multihex/tui.py` — interactive Textual TUI frontend; console script `multihex-tui`

Install with `pip install -e '.[dev]'` to get both scripts plus the test/lint deps. The commands below use the installed scripts; `python3 -m multihex.cli` / `python3 -m multihex.tui` work too.

Human-facing docs: `README.md` (users), `docs/ARCHITECTURE.md` and `docs/API.md` (developers), `CONTRIBUTING.md` (workflow). Keep them in sync with behavior changes.

`TODO.md` tracks repo-wide tasks and follow-ups. Check it for outstanding work, and when you finish a tracked item move it to the Done section (or add new follow-ups you discover).

## Commands

```bash
# Run the batch CLI
multihex FILE1 FILE2 FILE3
multihex --offset 0x40 --length 0x80 FILE1 FILE2
multihex --json FILE1 FILE2

# Search (exact byte/text match; reports observed matches only)
multihex --search-text RIFF FILE1 FILE2
multihex --search-hex "52 49 46 46" FILE1 FILE2
multihex --search-text content-type --search-ignore-case FILE1
multihex --search-text RIFF --search-context 2 FILE1

# Byte-class highlighting (display-only; needs color on; off by default)
multihex --byte-classes --color always FILE1 FILE2

# Run the TUI (requires textual + rich)
multihex-tui FILE1 FILE2
multihex-tui --byte-classes FILE1 FILE2   # start with byte-class highlighting on
# TUI search keys:  /  text search   x  hex search   n  next   N/p  previous
# TUI toggles:  c  color   t  byte-class highlighting

# Run all tests
python3 -m pytest

# Run a single test file
python3 -m pytest tests/test_core_parity.py

# Run a single test by name
python3 -m pytest tests/test_multihex_characterization.py::test_stdout_matches_golden[basic]

# Lint
ruff check .

# Regenerate golden output files after an intentional CLI rendering change
python3 tests/capture_goldens.py
```

## Architecture

**Core invariant**: `HexModel` compares fixed offsets — no byte alignment, resync, or inference. Missing bytes (past a file's end) render as `--`. This must never change.

**`HexModel`** owns the offset grid and marker computation. Frontends call `model.build_row(i)` and render what they get. `HexModel` takes an optional `length` to bound the window; TUI passes `None` (derives from largest file), batch CLI always passes a length.

**Marker logic** (`Marker.SAME/DIFF/MISSING`) is centralized in `HexModel._markers()`. `MISSING` wins if any byte in a column is `None`; otherwise compares against a pivot (the `--ref` file's byte, or `column[0]` when no `--ref`).

**`HexFile.data`** is either `mmap.mmap` (lazy, for real files) or `bytes`/`bytearray` (for tests). `byte_at()` and `size` work identically for both.

**Search** is exact (no inference, no alignment, no wildcards) and lives entirely in the core: `parse_hex_pattern()`, `make_text_query()`/`make_hex_query()` → `SearchQuery`, `search_files()` → ordered `SearchMatch` list, plus index-based navigation helpers (`first_match_index`, `next_match_index`, `prev_match_index`, `match_index_after`/`before`). Results are ordered by `(file_index, offset)`; matches are non-overlapping unless `overlap=True`. Case-insensitive text search folds ASCII letters only. Frontends add UI glue only: the CLI prints `file=… offset=… match=… ascii=…` lines (with optional `--search-context` rows), the TUI tracks search state and highlights matches (current match strongest). TUI render priority: missing > current match > other matches > diff marker > byte class.

**Byte classes** (`--byte-classes`; TUI `t`): display-only highlighting. `core.classify_byte()` maps a byte (or `None`) to a `ByteClass` (`ZERO`/`WHITESPACE`/`PRINTABLE_ASCII`/`OTHER`/`MISSING`) — data only, no ANSI/Rich. Frontends color hex cells by class as the **lowest-priority** tier (missing/diff/search styling always wins), only when color is enabled; off by default. It never affects offsets, markers, `--only-diff`, `--ref`, search, or `--json`.

## Tests

- `tests/fixtures.py` — builds deterministic binary test fixtures
- `tests/golden_cases.py` — named test case definitions
- `tests/goldens/` — expected stdout snapshots for characterization tests
- `tests/test_multihex_characterization.py` — verifies CLI output matches goldens byte-for-byte
- `tests/test_core_parity.py` — verifies core model output matches CLI JSON output
- `tests/test_tui_smoke.py` — smoke tests for TUI
- `tests/test_search.py` — core search: hex parser, text/hex/multi-file/overlap, navigation
- `tests/test_cli_search.py` — CLI `--search-*` output and clean error handling
- `tests/test_tui_search.py` — headless TUI search state, navigation, and status line
- `tests/test_byte_class.py` — core `classify_byte()` over boundary values
- `tests/test_cli_byte_classes.py` — CLI `--byte-classes` ANSI styling, color gating, JSON safety
- `tests/test_tui_byte_classes.py` — headless TUI byte-class state, toggle, status/help, priority

When updating `tests/goldens/*.out`, review the diff carefully and note the reason in the commit.

## Key constraints for new code

- Keep all comparison **and search** semantics in `src/multihex/core.py`; frontends render and navigate only.
- `src/multihex/core.py` must remain stdlib-only (no third-party imports).
- Search is exact: report observed byte matches only. Never add wildcards, alignment, or inference to it.
- The batch CLI and TUI color differently by design: CLI colors individual cells that differ from the reference; TUI colors whole columns by marker state. Do not unify them.
