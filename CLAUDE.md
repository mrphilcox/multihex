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

# Run the TUI (requires textual + rich)
python3 multihex-tui.py FILE1 FILE2

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

## Tests

- `tests/fixtures.py` — builds deterministic binary test fixtures
- `tests/golden_cases.py` — named test case definitions
- `tests/goldens/` — expected stdout snapshots for characterization tests
- `tests/test_multihex_characterization.py` — verifies CLI output matches goldens byte-for-byte
- `tests/test_core_parity.py` — verifies core model output matches CLI JSON output
- `tests/test_tui_smoke.py` — smoke tests for TUI

When updating `tests/goldens/*.out`, review the diff carefully and note the reason in the commit.

## Key constraints for new code

- Keep all comparison semantics in `multihex_core.py`; frontends render and navigate only.
- `multihex_core.py` must remain stdlib-only (no third-party imports).
- The batch CLI and TUI color differently by design: CLI colors individual cells that differ from the reference; TUI colors whole columns by marker state. Do not unify them.
