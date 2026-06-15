# Repository Guidelines

## Project Structure & Module Organization

This repository contains a Python hex **comparison and visualization** tool laid
out as a `src/` package (`src/multihex/`). `src/multihex/core.py` holds the shared
comparison model, byte formatting, file loading, and exact search logic — and is
**stdlib-only**. There are three frontends sharing that core:

- `src/multihex/cli.py` — batch CLI frontend (console script `multihex`)
- `src/multihex/tui.py` — interactive Textual frontend (console script `multihex-tui`; needs `textual`/`rich`)
- `src/multihex/gui.py` — read-only PySide6/Qt desktop frontend (console script `multihex-gui`; the `[gui]` extra)

Supporting modules: `src/multihex/overlay.py` (overlay load/query seam),
`src/multihex/layout_overlay_v1.py` (overlay schema validator), and
`src/multihex/tui_config.py` (TUI-only persisted preferences). Tests live under
`tests/` (unit + headless TUI/GUI); generated binary fixtures are built from
`tests/fixtures.py`, named cases are in `tests/golden_cases.py`, and expected CLI
output is stored in `tests/goldens/*.out`. Heavier opt-in UI visual-regression
tests live in `tests_ui/`; end-to-end shell checks live in `scripts/integration/`.
Human-facing docs live in `README.md`, `docs/`, and `CONTRIBUTING.md`. `TODO.md`
tracks repo-wide tasks and follow-ups — consult it for outstanding work and keep
it updated as items are completed or discovered.

## Relationship to bintools, boundaries, and non-goals

`multihex` is the **visualization layer**: it shows bytes, diffs, and read-only
layout overlays across multiple files at fixed offsets. The sibling `bintools`
project is the **evidence producer** (byte stability maps, field/payload scans,
and `layoutcheck`, which emits `bintools.layout-overlay` v1 JSON via
`--overlay-out`). multihex *consumes* those overlays; it never authors, infers,
or edits them.

Non-goals (keep these out of multihex — they belong in `bintools`/`layoutcheck`):
format parsing, validation grammars, byte alignment/resync, structure inference,
or anything that decides what a byte *means*. `src/multihex/layout_overlay_v1.py`
and `docs/layout-overlay-v1.md` are a vendored copy of the shared contract and
must stay byte-identical to the bintools copy.

**Do not overfit examples or fixtures to one binary format.** Binary formats do
not necessarily have a magic field, a fixed header size, 4-byte alignment, `u32`
fields, a fixed payload offset, or fixed endianness. Keep fixtures deliberately
varied (the existing ones use short non-4-byte magics, unaligned offsets, and
mixed endianness on purpose).

## Build, Test, and Development Commands

- `pip install -e '.[dev]'`: install the console scripts plus test/lint deps.
  Add the `[gui]` extra (PySide6) for `multihex-gui`, `[ui-test]` for the
  visual-regression suite.
- `multihex FILE1 FILE2 --json`: run the batch CLI locally.
- `multihex --offset 0x40 --length 0x80 FILE1 FILE2`: inspect a fixed byte range
  (`0x40`/`0x80` are just sample values, not an assumed layout).
- `multihex --search-text RIFF FILE1 FILE2`: exact text search;
  `--search-hex "52 49 46 46"` for bytes, `--search-ignore-case` (ASCII) and
  `--search-context N` are also available.
- `multihex-tui FILE1 FILE2`: run the TUI; requires `textual` and `rich`
  (the `[tui]` or `[dev]` extra). Search keys: `/` text, `x` hex, `n` next,
  `N`/`p` previous.
- `multihex-gui FILE1 FILE2`: run the read-only desktop GUI; requires PySide6
  (the `[gui]` extra).

Validation commands (state clearly which lanes you ran):

- `python3 -m pytest`: unit + headless TUI/GUI tests (TUI tests skip without
  `textual`, GUI tests without `PySide6`).
- `ruff check .`: lint source and tests.
- `scripts/integration/run_all.sh`: end-to-end CLI/validator shell checks
  (not collected by pytest).
- `QT_QPA_PLATFORM=offscreen scripts/ui-tests/run_ui_tests.sh`: opt-in UI
  visual-regression suite in `tests_ui/` (needs the `[ui-test]` extra); heavier,
  not part of a bare pytest run. `scripts/ui-tests/update_snapshots.sh`
  regenerates baselines after an intentional UI change.
- `python3 tests/capture_goldens.py`: regenerate golden output files after an
  intentional CLI rendering change.

## Coding Style & Naming Conventions

Use Python 3 with standard-library dependencies in core and batch code unless a
frontend already requires otherwise. Follow the existing style: four-space
indentation, descriptive snake_case functions, PascalCase dataclasses/classes,
and concise docstrings for public helpers or non-obvious behavior. Keep
comparison semantics in `src/multihex/core.py`; frontends should render and navigate,
not reimplement marker rules. The core (`src/multihex/core.py`) and batch CLI
must stay stdlib-only; `overlay.py`, `layout_overlay_v1.py`, and `shortcuts.py`
also stay stdlib-only. The TUI may depend on `textual`/`rich`, and
`tui_config.py` may use `tomli` on Python 3.10 through the TUI/dev extras.
Only the GUI may depend on `PySide6`.

### Keyboard shortcuts — single source of truth

`src/multihex/shortcuts.py` is the **only** place frontend keyboard shortcuts and
their help text are defined; it is **stdlib-only** (no core/Textual/PySide6
imports). The TUI help popup (`_HELP = tui_help_text()`) and the GUI help dialog
(`gui_help_text()`) are generated from it, and the GUI's single-key dispatch is
built from `gui_text_map()`/`gui_key_names()`. **Never hand-edit either frontend's
help list or add a key in only one place.** To change a shortcut, the workflow is:

1. Edit `SHORTCUTS` in `src/multihex/shortcuts.py` (and the TUI `BINDINGS` /
   GUI `_action_slots` if you are adding/removing an action, not just rewording).
2. Run lane 1 (`python3 -m pytest`) — `tests/test_shortcuts.py` enforces that the
   TUI `BINDINGS` key-set equals the registry and that every GUI-applicable action
   is wired; the headless help-content assertions update here.
3. If you changed anything the help popup renders, regenerate the `tests_ui/`
   help-popup SVG with `scripts/ui-tests/update_snapshots.sh` and review the diff
   like a golden file before committing. That diff is the deliberate-review gate,
   **not** a regression to suppress.

## Testing Guidelines

Tests use pytest. Add characterization or golden coverage for user-visible CLI
output, and parity tests when core behavior must match frontend JSON output.
Headless TUI and GUI tests live in `tests/` and skip cleanly when `textual` /
`PySide6` are absent; the heavier visual-regression suite in `tests_ui/` (Textual
SVG snapshots + offscreen GUI render smoke) is opt-in, needs the `[ui-test]`
extra, and runs under `QT_QPA_PLATFORM=offscreen`. Name test files `test_*.py`
and test functions `test_*`. When updating `tests/goldens/*.out` or
`tests_ui/__snapshots__/*.svg`, review the diff carefully and include the reason
in the change description.

Mutation testing (`scripts/mutation/run_mutation.sh`, via `mutmut`) is a targeted, manual
quality audit of the deterministic core only - never the UI stack. It is **not**
part of `python3 -m pytest`, not a CI gate, and not a release blocker. Treat
surviving mutants as candidates for a missing assertion, not a score to chase:
add a focused test only when a survivor reveals a real gap. See the "Mutation
Testing" section in [`docs/TESTING.md`](docs/TESTING.md).

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
