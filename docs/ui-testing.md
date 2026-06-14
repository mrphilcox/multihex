# UI testing

multihex has two layers of UI testing:

1. **Fast headless UI tests** in `tests/` (`test_tui_*.py`, `test_gui_*.py`) —
   state-level assertions run by the default `python3 -m pytest`. They skip
   cleanly when `textual` / `PySide6` are absent.

2. **Opt-in UI visual-regression tests** in `tests_ui/` — heavier SVG/PNG
   snapshot checks that prove the *rendered* output stays stable. These are
   excluded from the default `pytest` run and from the shell integration
   runner.

For the visual-regression layer — how to install deps, run it, update
snapshots, and why it is excluded from default collection — see
[`tests_ui/README.md`](../tests_ui/README.md).

Quick reference:

```bash
pip install -e '.[ui-test]'          # optional heavy UI/test deps
scripts/ui-tests/run_ui_tests.sh     # run the visual-regression layer (headless)
scripts/ui-tests/update_snapshots.sh # regenerate TUI SVG baselines (intentional changes)
```
