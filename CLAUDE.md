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

# Marker text display (display-only; separate from --layout; no effect on --json)
multihex --markers none FILE1 FILE2                      # hide the marker strip
multihex --layout side-by-side --markers repeat FILE1 FILE2

# Run the TUI (requires textual + rich)
multihex-tui FILE1 FILE2
multihex-tui --byte-classes FILE1 FILE2   # start with byte-class highlighting on
multihex-tui --markers repeat FILE1 FILE2 # start with the chosen marker display
# TUI search keys:  /  text search (panel has ASCII case-insensitive checkbox)
#                   x  hex search (byte values, not ASCII)   n  next   N/p  previous
# TUI toggles:  c  color   t  byte-class highlighting   v  layout   m  markers
# TUI overlay:  l  load/change layout overlay (blank clears)   L  view current overlay

# Layout overlay (read-only annotation layer; validated; needs color on; no --json effect)
multihex --overlay path/to/file.overlay.json --color always FILE1 FILE2

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

**Search** is exact (no inference, no alignment, no wildcards) and lives entirely in the core: `parse_hex_pattern()`, `make_text_query()`/`make_hex_query()` → `SearchQuery`, `search_files()` → ordered `SearchMatch` list, plus index-based navigation helpers (`first_match_index`, `next_match_index`, `prev_match_index`, `match_index_after`/`before`). Results are ordered by `(file_index, offset)`; matches are non-overlapping unless `overlap=True`. Case-insensitive text search folds ASCII letters only (`--search-ignore-case`; the TUI text-search panel has a session-only "Case-insensitive (ASCII)" checkbox). Hex search is always exact byte matching — it has no case toggle, parses upper/lowercase hex digits via `parse_hex_pattern()`, and never falls back to a text search of the raw input. Frontends add UI glue only: the CLI prints `file=… offset=… match=… ascii=…` lines (with optional `--search-context` rows), the TUI tracks search state and highlights matches (current match strongest). TUI render priority: missing > current match > other matches > diff marker > byte class.

**Byte classes** (`--byte-classes`; TUI `t`): display-only highlighting. `core.classify_byte()` maps a byte (or `None`) to a `ByteClass` (`ZERO`/`WHITESPACE`/`PRINTABLE_ASCII`/`OTHER`/`MISSING`) — data only, no ANSI/Rich. Frontends color hex cells by class as the **lowest-priority** tier (missing/diff/search styling always wins), only when color is enabled; off by default. It never affects offsets, markers, `--only-diff`, `--ref`, search, or `--json`.

**Marker display** (`--markers single|repeat|none`; TUI `m`): display-only, and a **separate concern from `--layout`** — a plain string each frontend renderer branches on (also a `markers` keyword on `core.render_row_text()`, so CLI search-context rows honor it). `single` (default) draws one strip per block — in side-by-side as its own left prefix column, not attached to the first file; `repeat` repeats the strip under each segment in side-by-side (identical to `single` when stacked); `none` hides the strip text. Stacked `single`/`repeat` output is byte-identical to the pre-feature rendering. Marker **computation** stays in `HexModel._markers()` and is untouched, so this never affects `--only-diff`, diff/missing highlighting, search, or `--json` (the `markers` array is always present). TUI persists it as `[display] markers` (config schema still v1; missing key defaults to `single`).

**Layout overlays** (`--overlay PATH`; TUI `l`/`L`; GUI Overlay menu): display-only consumption of `bintools.layout-overlay` v1 files — a read-only annotation layer, never authored or inferred here. The seam is `src/multihex/overlay.py` (`OverlayState`/`OverlayRange`), separate from `core.py` so the comparison core stays focused. `OverlayState.load(path, files)` reads the JSON and calls `layout_overlay_v1.validate_structural` once plus `validate_file_aware` per loaded file (diagnostics labelled by file). The **validator is the single source of truth** for severities and the `ok`-means-loadable contract — multihex never re-derives them: `OverlayState.applicable` is `True` only when no `error`-severity diagnostic exists anywhere, and frontends highlight only when applicable (errored overlays are reported but not applied; warnings are summarized with detail in "view current overlay"). Frontends never touch raw JSON — they ask the state object: `covers(offset)`, `ranges_at(offset)` (deterministic order; zero-length match nothing, out-of-bounds/overlapping never crash), `all_diagnostics()`, `summary()`, `details_text()`. Highlight priority sits **below missing/diff** and search (CLI blue background, TUI `on blue`, GUI a distinct cell color), needs color on, and has no effect on `--json`. Overlay paths are **never persisted** to config (overlays are file/session-specific).

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
- `tests/test_cli_markers.py` — CLI `--markers` parsing, both layouts, JSON/only-diff/search invariants
- `tests/test_tui_markers.py` — headless TUI marker-mode state, `m` cycle, status/help, redraw
- `tests/test_overlay.py` — core `OverlayState`/`OverlayRange`: load, per-file validation, range lookup, overlap/zero-length/out-of-bounds robustness
- `tests/test_cli_overlay.py` — CLI `--overlay` highlight ANSI, diagnostics on stderr, JSON safety, no-op path
- `tests/test_tui_overlay.py` — headless TUI overlay load/clear/view state, status, cell-style priority
- `tests/test_gui_overlay.py` — headless GUI overlay menu glue, diagnostics surfaced, cell-color tier, stale-overlay drop on reload

When updating `tests/goldens/*.out`, review the diff carefully and note the reason in the commit.

## Key constraints for new code

- Keep all comparison **and search** semantics in `src/multihex/core.py`; frontends render and navigate only.
- `src/multihex/core.py` must remain stdlib-only (no third-party imports).
- Search is exact: report observed byte matches only. Never add wildcards, alignment, or inference to it.
- The batch CLI and TUI color differently by design: CLI colors individual cells that differ from the reference; TUI colors whole columns by marker state. Do not unify them.
- Layout overlays are **consumer-only**: load, validate, display, highlight. Never author, infer, or edit overlays, and never re-derive the validator's severities/`ok` contract — call `multihex.layout_overlay_v1` and render its diagnostics. Keep `core.py` free of overlay logic; it lives in `src/multihex/overlay.py`. Don't persist overlay paths in config.
