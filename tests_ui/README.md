# UI visual-regression tests (`tests_ui/`)

This is a **separate, opt-in, heavier** validation layer. It exists to catch
*visual* regressions in the two interactive frontends:

- the **Textual TUI** (`multihex.tui.MultiHexApp`) — SVG snapshots via
  [`pytest-textual-snapshot`](https://github.com/Textualize/pytest-textual-snapshot)
- the **PySide6 GUI** (`multihex.gui.MainWindow`) — rendered to a PNG with
  `QWidget.grab()` and checked conservatively (non-null, correct non-zero
  size, actually painted) — no pixel-perfect comparison.

It is **not** a replacement for the fast headless UI tests in `tests/`
(`test_tui_*.py`, `test_gui_*.py`), which assert widget/state behaviour and
stay in the default `pytest` path. These tests prove the rendered output stays
stable; they intentionally do not re-test all UI behaviour.

## The four validation lanes

```bash
python3 -m pytest                  # fast unit + headless UI tests (unchanged)
ruff check .                       # lint (unchanged)
scripts/integration/run_all.sh     # shell integration tests (unchanged)
scripts/ui-tests/run_ui_tests.sh   # this opt-in UI visual-regression layer
```

## Why it is excluded from the default run

The project sets `testpaths = ["tests"]` in `pyproject.toml`, so a bare
`python3 -m pytest` only discovers `tests/`. `tests_ui/` is a *sibling*
directory, so it is never auto-collected — no marker/`norecursedirs` trick
needed. Passing it explicitly (`pytest tests_ui`, as the run script does)
overrides `testpaths` so the layer still runs on demand.

Verify the exclusion:

```bash
python3 -m pytest --collect-only -q | grep tests_ui   # → no output
```

## Optional dependencies

These are **not** installed by a normal or `[dev]` install. Install the extra:

```bash
pip install -e '.[ui-test]'
```

That pulls in `textual`, `rich`, `PySide6`, `pytest`, and
`pytest-textual-snapshot`. Each test skips cleanly when its dependency is
missing:

- whole TUI module skips without `textual`;
- the SVG snapshot tests skip without `pytest-textual-snapshot` (the thin TUI
  launch-smoke still runs);
- the GUI tests skip without `PySide6`.

## Running

```bash
scripts/ui-tests/run_ui_tests.sh             # run everything
scripts/ui-tests/run_ui_tests.sh -k snapshot # just the snapshots
```

The runner exports `QT_QPA_PLATFORM=offscreen` (also set in `conftest.py`) so
the GUI renders **headless**, with no display server. GUI PNG artifacts are
written to `tests_ui/_artifacts/` (gitignored) for inspection.

## Updating snapshots

After an **intentional** TUI rendering change, regenerate the SVG baselines and
review the diff before committing (treat it like `tests/goldens/*.out`):

```bash
scripts/ui-tests/update_snapshots.sh                       # all
scripts/ui-tests/update_snapshots.sh -k snapshot_diff_view # one
```

SVG baselines live under `tests_ui/__snapshots__/` and are committed.

## Fixtures

`fixtures_ui.py` builds tiny, deterministic, format-agnostic binaries (no
magic, a short 3-byte id, an unaligned payload, text mixed with NUL/high
bytes, and a one-byte-diff pair). `data/overlay_sample.json` is a
`bintools.layout-overlay` v1 file with a 3-byte identifier, a 2-byte
big-endian integer, an unaligned payload range, and one out-of-bounds range
that produces a non-error *warning* — exercising overlay status display
without blocking application.
