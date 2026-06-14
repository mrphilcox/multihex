# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this project is

`multihex` is a Python tool for side-by-side fixed-offset hex comparison of multiple binary files. It has two frontends sharing one core:

- `multihex_core.py` — stdlib-only shared logic: file loading, `HexModel`/`Row` dataclasses, `Marker` enum, cell formatting
- `multihex.py` — batch CLI frontend (text/JSON output, ANSI color)
- `multihex-tui.py` — interactive Textual TUI frontend

## Commands

```bash
# Run the batch CLI
python3 multihex.py FILE1 FILE2 FILE3
python3 multihex.py --offset 0x40 --length 0x80 FILE1 FILE2
python3 multihex.py --json FILE1 FILE2

# Search (exact byte/text match; reports observed matches only)
python3 multihex.py --search-text RIFF FILE1 FILE2
python3 multihex.py --search-hex "52 49 46 46" FILE1 FILE2
python3 multihex.py --search-text content-type --search-ignore-case FILE1
python3 multihex.py --search-text RIFF --search-context 2 FILE1

# Run the TUI (requires textual + rich)
python3 multihex-tui.py FILE1 FILE2
# TUI search keys:  /  text search   x  hex search   n  next   N/p  previous

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

**Search** is exact (no inference, no alignment, no wildcards) and lives entirely in the core: `parse_hex_pattern()`, `make_text_query()`/`make_hex_query()` → `SearchQuery`, `search_files()` → ordered `SearchMatch` list, plus index-based navigation helpers (`first_match_index`, `next_match_index`, `prev_match_index`, `match_index_after`/`before`). Results are ordered by `(file_index, offset)`; matches are non-overlapping unless `overlap=True`. Case-insensitive text search folds ASCII letters only. Frontends add UI glue only: the CLI prints `file=… offset=… match=… ascii=…` lines (with optional `--search-context` rows), the TUI tracks search state and highlights matches (current match strongest). TUI render priority: missing > current match > other matches > diff marker.

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

When updating `tests/goldens/*.out`, review the diff carefully and note the reason in the commit.

## Key constraints for new code

- Keep all comparison **and search** semantics in `multihex_core.py`; frontends render and navigate only.
- `multihex_core.py` must remain stdlib-only (no third-party imports).
- Search is exact: report observed byte matches only. Never add wildcards, alignment, or inference to it.
- The batch CLI and TUI color differently by design: CLI colors individual cells that differ from the reference; TUI colors whole columns by marker state. Do not unify them.
