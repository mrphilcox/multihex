# Repository Guidelines

## Project Structure & Module Organization

This repository contains a small Python hex comparison tool laid out as a `src/`
package (`src/multihex/`). `src/multihex/core.py` holds the shared comparison
model, byte formatting, file loading, and exact search logic. `src/multihex/cli.py`
is the batch CLI frontend (console script `multihex`), and `src/multihex/tui.py`
is the interactive Textual frontend (console script `multihex-tui`). Tests live
under `tests/`; generated binary fixtures are built from `tests/fixtures.py`,
named cases are in `tests/golden_cases.py`, and expected CLI output is stored in
`tests/goldens/*.out`. Human-facing docs live in `README.md`, `docs/`, and
`CONTRIBUTING.md`. `TODO.md` tracks repo-wide tasks and follow-ups — consult it
for outstanding work and keep it updated as items are completed or discovered.

## Build, Test, and Development Commands

- `pip install -e '.[dev]'`: install both console scripts plus test/lint deps.
- `multihex FILE1 FILE2 --json`: run the batch CLI locally.
- `multihex --offset 0x40 --length 0x80 FILE1 FILE2`: inspect a fixed byte range.
- `multihex --search-text RIFF FILE1 FILE2`: exact text search;
  `--search-hex "52 49 46 46"` for bytes, `--search-ignore-case` (ASCII) and
  `--search-context N` are also available.
- `multihex-tui FILE1 FILE2`: run the TUI; requires `textual` and `rich`
  (the `[tui]` or `[dev]` extra). Search keys: `/` text, `x` hex, `n` next,
  `N`/`p` previous.
- `python3 -m pytest`: run all tests.
- `python3 tests/capture_goldens.py`: regenerate golden output files after an
  intentional CLI rendering change.

## Coding Style & Naming Conventions

Use Python 3 with standard-library dependencies in core and batch code unless a
frontend already requires otherwise. Follow the existing style: four-space
indentation, descriptive snake_case functions, PascalCase dataclasses/classes,
and concise docstrings for public helpers or non-obvious behavior. Keep
comparison semantics in `src/multihex/core.py`; frontends should render and navigate,
not reimplement marker rules. The core (`src/multihex/core.py`) and batch CLI
must stay stdlib-only; only the TUI may depend on `textual`/`rich`.

## Testing Guidelines

Tests use pytest. Add characterization or golden coverage for user-visible CLI
output, and parity tests when core behavior must match frontend JSON output.
Name test files `test_*.py` and test functions `test_*`. When updating
`tests/goldens/*.out`, review the diff carefully and include the reason in the
change description.

## Commit & Pull Request Guidelines

The current history uses short imperative summaries, for example `add tests` and
`Refactor code to share backend`. Keep commits focused and describe the user-
visible or structural change. Pull requests should include a concise summary,
the commands run, and notes about any regenerated golden files. Link related
issues when available, and include screenshots or terminal captures for TUI
changes that affect display behavior.

## Agent-Specific Instructions

Preserve fixed-offset comparison semantics: no byte alignment, resync, or
inference. Missing bytes render as `--`, and marker behavior should remain
centralized in `HexModel`. Search is exact too — it reports observed byte
matches only, with no wildcards or inference — and its semantics
(`parse_hex_pattern`, `search_files`, navigation helpers) stay in the core.
