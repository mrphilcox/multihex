# Contributing to multihex

Thanks for working on `multihex`. This guide covers local setup, the test and lint
workflow, the layout of the test suite, and how to extend the tool without
breaking its invariants. For the design itself see
[`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).

## Development setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
```

The `dev` extra installs `pytest`, `ruff`, and the TUI dependencies
(`textual`, `rich`).

## Tracking work

`TODO.md` at the repo root tracks repo-wide tasks and follow-ups. Check it before
starting work, and when you complete a tracked item move it to the **Done**
section — or add new follow-ups you discover along the way.

## Project layout

```
src/multihex/
  core.py              # stdlib-only comparison + search engine (the "meaning")
  cli.py               # batch frontend: text/JSON/color, parsing      -> `multihex`
  tui.py               # interactive Textual frontend                  -> `multihex-tui`
  gui.py               # read-only PySide6/Qt desktop frontend         -> `multihex-gui`
  overlay.py           # OverlayState/OverlayRange: load + query overlays
  layout_overlay_v1.py # overlay schema validator (shared with bintools)
  tui_config.py        # TUI-only persisted preferences (TOML)
  __init__.py
tests/
  fixtures.py                          # deterministic binary fixtures
  golden_cases.py                      # named CLI test-case definitions
  goldens/                             # expected stdout snapshots (*.out)
  capture_goldens.py                   # regenerates the goldens
  test_multihex_characterization.py    # CLI stdout == goldens, byte for byte
  test_core_parity.py                  # core model output == CLI JSON output
  test_search.py                       # core search: parser, text/hex, nav
  test_cli_search.py                   # CLI --search-* output + error handling
  test_tui_search.py                   # headless TUI search state + status line
  test_tui_smoke.py                    # TUI smoke tests
  test_cli_overlay.py / test_tui_overlay.py / test_gui_overlay.py  # overlay glue
  test_gui_viewstate.py / test_gui_smoke.py / test_gui_widget.py   # GUI (skip w/o PySide6)
  ...                                  # markers, byte-classes, layout, config, etc.
tests_ui/                              # opt-in UI visual-regression (SVG/PNG snapshots)
scripts/integration/                   # end-to-end CLI/validator shell checks
scripts/ui-tests/                      # run / update the tests_ui/ suite
```

TUI/GUI tests skip cleanly when `textual` / `PySide6` are absent. The `dev` extra
installs `textual`/`rich`; add the `[gui]` extra for PySide6 and `[ui-test]` for
the visual-regression suite.

## Running tests

```bash
# Everything:
python3 -m pytest

# A single file:
python3 -m pytest tests/test_core_parity.py

# A single test (by node id):
python3 -m pytest tests/test_multihex_characterization.py::test_stdout_matches_golden[basic]
```

## Integration tests

End-to-end shell checks live in `scripts/integration/` and drive the real
command-line entry points and the `layout_overlay_v1` validator against a
generated corpus (`tests/integration/generators/`). They are **not** part of the
pytest run (excluded via `norecursedirs`); run them manually:

```bash
scripts/integration/run_all.sh          # smoke + layout-overlay + examples
scripts/integration/run_smoke.sh        # entry-point --help and a real comparison
scripts/integration/run_layout_overlay.sh
KEEP_WORK=1 scripts/integration/run_all.sh   # preserve temp dirs for debugging
```

Each script prints `PASS`/`FAIL`/`SKIP` lines, cleans up its own `mktemp -d`
work dir, and skips optional frontends (e.g. the Textual TUI) when their
dependencies are absent.

## UI tests (opt-in)

The heavier visual-regression suite lives in `tests_ui/` and is **not** part of a
bare `pytest` run. It needs the `[ui-test]` extra and runs offscreen:

```bash
pip install -e '.[ui-test]'
QT_QPA_PLATFORM=offscreen scripts/ui-tests/run_ui_tests.sh
```

It covers Textual SVG snapshots and an offscreen GUI render smoke test. After an
**intentional** UI change, regenerate the baselines and review the diff like a
golden:

```bash
scripts/ui-tests/update_snapshots.sh            # all
scripts/ui-tests/update_snapshots.sh -k diff_view  # one
```

See [`docs/ui-testing.md`](docs/ui-testing.md) for details.

## Stress tests (opt-in)

A separate suite in `scripts/stress/` probes where multihex breaks under
**scale, resource pressure, and hostile inputs** (huge sparse files, FD
exhaustion, the search match-list explosion, overlay scale, `/dev/full`, FIFOs,
extreme TUI/GUI geometry). It is **not** part of `pytest`, `scripts/integration/`,
or any automatic CI lane. Every heavy/hostile command runs under
`scripts/stress/measure.py`, which contains it in a process group with a
wall-clock timeout and an RSS cap, so it is safe to run on a workstation.

```bash
scripts/stress/run_all.sh                 # full suite
STRESS_FAST=1 scripts/stress/run_all.sh   # quick smoke (shrunk scales)
KEEP_WORK=1 scripts/stress/run_all.sh     # keep temp dirs for inspection
```

It prints `PASS`/`FAIL`/`SKIP` plus `FINDING` (a confirmed, documented hazard)
and `CHAR` (an observed resource ceiling) lines; it exits non-zero only on
`FAIL`. See [`scripts/stress/README.md`](scripts/stress/README.md) for the
dimensions, env knobs, and verdict meanings, and `TODO.md` for the findings it
surfaced.

## Linting

```bash
ruff check .
```

Ruff is configured in `pyproject.toml`: line length 100, rule sets `E`, `F`, `W`,
`I` (including import sorting). Run it before sending a change.

## Golden output files

`tests/goldens/*.out` are byte-for-byte snapshots of CLI stdout for the cases in
`tests/golden_cases.py`. After an **intentional** change to CLI rendering,
regenerate them:

```bash
python3 tests/capture_goldens.py
```

Then **review the diff carefully** and explain the reason in your commit message.
A golden diff you didn't expect means a real behavior change — investigate before
committing it.

## How to extend the tool

### Add a CLI flag
1. Add the argument in `build_parser()` in `src/multihex/cli.py`.
2. Wire it into the relevant renderer (`render_text_row`, `build_json_row`, or
   `run_search`) — frontends *render and navigate only*.
3. Add a named case in `tests/golden_cases.py` and regenerate goldens; add a
   characterization or search test as appropriate.

### Add or change a frontend keyboard shortcut
Frontend shortcuts and their help text have **one** home:
`src/multihex/shortcuts.py` (stdlib-only). Never hand-edit a frontend's help list
or add a key in only one place — the TUI help popup and the GUI help dialog are
both generated from the registry. The workflow:
1. Edit `SHORTCUTS` in `src/multihex/shortcuts.py` (display keys, help text,
   `tui_keys`/`gui_keys`, applicability). Add the TUI `Binding`/`action_*` in
   `src/multihex/tui.py` and/or the GUI `_action_slots` entry in
   `src/multihex/gui.py` only when adding/removing an action.
2. Run `python3 -m pytest` — `tests/test_shortcuts.py` enforces that the TUI
   `BINDINGS` key-set equals the registry, every binding has an `action_*` method,
   and every GUI-applicable action is wired; update the headless help-content
   assertions there.
3. If the help popup's rendered text changed, regenerate the `tests_ui/` help-popup
   SVG with `scripts/ui-tests/update_snapshots.sh` and review the diff like a golden
   file. The diff is the deliberate-review gate, not a regression to silence.

### Add a TUI key or behavior
1. Add the shortcut to the registry first (see above), plus a `Binding` and an
   `action_*` method in `src/multihex/tui.py`.
2. Keep navigation/highlight state on the widget/app; pull bytes and markers from
   the core model — never recompute comparison meaning in the TUI.
3. Add a headless test in `tests/test_tui_*` (e.g. `test_tui_home_end.py`).

### Add a GUI behavior
1. Add the widget/menu/action in `src/multihex/gui.py`. For a keyboard shortcut,
   register it (see above) and wire `_action_slots`. Keep Qt-free
   navigation/filter/status logic in the `ViewState`/`format_status` helpers, and
   factor dialog-driven logic (e.g. `run_search`) into non-modal methods so it
   stays unit-testable without a display (drive them via `trigger_action`).
2. Pull bytes and markers from the core model — never recompute comparison
   meaning in the GUI. PySide6 stays import-guarded (the GUI is optional).
3. Add a headless test in `tests/test_gui_*` (offscreen). For a visible rendering
   change, add/update a `tests_ui/` snapshot (see "UI tests" below).

### Add a core capability
1. Implement it in `src/multihex/core.py` (it must stay **stdlib-only**).
2. Add core tests, and a parity test if a frontend must mirror the behavior.
3. Keep all comparison **and search** semantics here so all frontends stay in
   lockstep.

## Invariants you must preserve

- **Fixed-offset comparison only** — no alignment, resync, or inference. Missing
  bytes render as `--`. Marker logic stays in `HexModel._markers()`.
- **Exact search only** — observed byte matches, no wildcards or inference. Search
  semantics stay in the core.
- **The core stays stdlib-only.** The TUI may use `textual`/`rich`; `core.py` and
  `cli.py` may not import third-party packages.
- **Frontend color schemes differ by design** — do not unify them.

## Style

- Python 3, four-space indentation.
- `snake_case` functions, `PascalCase` classes/dataclasses.
- Concise docstrings for public helpers and any non-obvious behavior.

## Commits & pull requests

- Use short, imperative commit summaries describing the user-visible or structural
  change (e.g. `add exact text/hex search`).
- Keep commits focused.
- PRs should include a concise summary, the commands you ran, and a note about any
  regenerated golden files (with the reason). Link related issues. For TUI changes
  that affect display, include a terminal capture or screenshot.
