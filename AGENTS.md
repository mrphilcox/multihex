# Repository Guidelines

## Project Structure & Module Organization

This repository contains a small Python hex comparison tool. `multihex_core.py`
holds the shared comparison model, byte formatting, and file loading logic.
`multihex.py` is the batch CLI frontend, and `multihex-tui.py` is the interactive
Textual frontend. Tests live under `tests/`; generated binary fixtures are built
from `tests/fixtures.py`, named cases are in `tests/golden_cases.py`, and
expected CLI output is stored in `tests/goldens/*.out`.

## Build, Test, and Development Commands

- `python3 multihex.py FILE1 FILE2 --json`: run the batch CLI locally.
- `python3 multihex.py --offset 0x40 --length 0x80 FILE1 FILE2`: inspect a
  fixed byte range.
- `python3 multihex.py --search-text RIFF FILE1 FILE2`: exact text search;
  `--search-hex "52 49 46 46"` for bytes, `--search-ignore-case` (ASCII) and
  `--search-context N` are also available.
- `python3 multihex-tui.py FILE1 FILE2`: run the TUI; requires `textual` and
  `rich` to be installed in the active environment. Search keys: `/` text,
  `x` hex, `n` next, `N`/`p` previous.
- `python3 -m pytest`: run all tests.
- `python3 tests/capture_goldens.py`: regenerate golden output files after an
  intentional CLI rendering change.

## Coding Style & Naming Conventions

Use Python 3 with standard-library dependencies in core and batch code unless a
frontend already requires otherwise. Follow the existing style: four-space
indentation, descriptive snake_case functions, PascalCase dataclasses/classes,
and concise docstrings for public helpers or non-obvious behavior. Keep
comparison semantics in `multihex_core.py`; frontends should render and navigate,
not reimplement marker rules.

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
