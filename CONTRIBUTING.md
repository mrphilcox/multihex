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
  core.py    # stdlib-only comparison + search engine (the "meaning")
  cli.py     # batch frontend: text/JSON/color, argument parsing  -> `multihex`
  tui.py     # interactive Textual frontend                       -> `multihex-tui`
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
```

## Running tests

```bash
# Everything:
python3 -m pytest

# A single file:
python3 -m pytest tests/test_core_parity.py

# A single test (by node id):
python3 -m pytest tests/test_multihex_characterization.py::test_stdout_matches_golden[basic]
```

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

### Add a TUI key or behavior
1. Add a `Binding` and an `action_*` method in `src/multihex/tui.py`, and update
   the in-app `HelpScreen` and the module docstring's key list.
2. Keep navigation/highlight state on the widget/app; pull bytes and markers from
   the core model — never recompute comparison meaning in the TUI.
3. Add a headless test in `tests/test_tui_search.py` / `tests/test_tui_smoke.py`.

### Add a core capability
1. Implement it in `src/multihex/core.py` (it must stay **stdlib-only**).
2. Add core tests, and a parity test if a frontend must mirror the behavior.
3. Keep all comparison **and search** semantics here so both frontends stay in
   lockstep.

## Invariants you must preserve

- **Fixed-offset comparison only** — no alignment, resync, or inference. Missing
  bytes render as `--`. Marker logic stays in `HexModel._markers()`.
- **Exact search only** — observed byte matches, no wildcards or inference. Search
  semantics stay in the core.
- **The core stays stdlib-only.** The TUI may use `textual`/`rich`; `core.py` and
  `cli.py` may not import third-party packages.
- **The CLI and TUI color differently by design** — do not unify the two schemes.

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
