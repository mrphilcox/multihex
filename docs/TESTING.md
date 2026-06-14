# Testing

`multihex` has several validation layers. The fast default tests are the usual
development loop; the full-suite runner is a convenience command that orchestrates
the existing runners without merging or duplicating their logic.

## Fast Default Checks

Run the default pytest suite for unit, characterization, and headless frontend
coverage:

```sh
python3 -m pytest
```

`pyproject.toml` sets `testpaths = ["tests"]`, so a bare pytest run does not
collect `tests_ui/`, `tests_perf/`, or shell integration assets. Optional TUI and
GUI tests in `tests/` skip cleanly when their dependencies are unavailable.

Run lint separately:

```sh
ruff check .
```

## Integration Tests

Integration tests live under `scripts/integration/` and drive the real command
line entry points plus generated overlay fixtures. They are not part of default
pytest collection.

```sh
scripts/integration/run_all.sh
```

## Coverage

The coverage runner measures the default pytest suite with subprocess-aware
coverage:

```sh
scripts/coverage/run_coverage.sh
scripts/coverage/run_coverage.sh --html
scripts/coverage/run_coverage.sh --xml
scripts/coverage/run_coverage.sh --fail-under 65
```

Many CLI tests run `multihex` in child processes, so the runner sets
`COVERAGE_PROCESS_START`, an absolute `COVERAGE_FILE`, and `PYTHONPATH` so those
children record coverage fragments through `sitecustomize.py`. The default run
prints only the terminal summary and total percentage; HTML (`htmlcov/`) and XML
(`coverage.xml`) are opt-in. The fail-under threshold is a coarse regression
guard, not a 100% coverage goal.

## Mutation Testing

Mutation testing is a targeted, manual quality audit. It changes (mutates) the
source one edit at a time and reruns the tests; a mutant that survives means the
tests did not notice that change, which points at a missing assertion. It is a
way to ask whether the tests actually constrain behavior or merely execute code.

This lane is deliberately scoped and is **not** part of `python3 -m pytest`,
**not** a CI gate, and **not** a release blocker. It mutates only the
deterministic, stdlib-only core and skips the UI stack, which is snapshot and
offscreen tested and too noisy to mutate usefully.

It uses [`mutmut`](https://mutmut.readthedocs.io/) (pinned to the 2.x series in
the `dev` extra; its config keys, cache file, and result commands changed
incompatibly in 3.x). The targets are configured in `[tool.mutmut]` in
`pyproject.toml`:

- Mutated: `core.py`, `overlay.py`, `layout_overlay_v1.py`, `shortcuts.py`,
  `tui_config.py`.
- Excluded: `tui.py` and `gui.py` (UI widgets), `cli.py` (argument glue covered
  by characterization goldens), and `__init__.py` (version string only).

Workflow:

```sh
scripts/mutation/run_mutation.sh  # runs `mutmut run` against the configured targets
mutmut results               # list survived/killed mutants
mutmut show <ID>             # inspect a specific mutant's diff
mutmut browse                # interactive results browser
```

The runner warns (but does not abort) on a dirty working tree, passes extra
arguments through to `mutmut run` (for example
`scripts/mutation/run_mutation.sh --paths-to-mutate src/multihex/shortcuts.py` to scope a
run), and never applies a mutant to the working tree. `mutmut` caches results in
`.mutmut-cache` (gitignored); delete it to force a full re-run.

A full run is slow: it reruns the whole pytest suite once per mutant, so scope it
with `--paths-to-mutate` while iterating. `mutmut` restores each file after
testing its mutant, but a hard interrupt (Ctrl-C or a `timeout` kill) can leave
the last mutant applied next to a `<file>.bak`; recover with
`git checkout -- <file>` and delete the leftover `.bak`.

Handling surviving mutants:

- Inspect the mutant with `mutmut show <ID>` and read the diff.
- Decide whether it exposes a genuinely missing assertion. Many survivors are
  equivalent mutants (no observable behavior change) and are not worth chasing.
- If it is a real gap, add a focused test for that behavior. Do not chase the
  mutation score with brittle tests written only to kill a mutant.
- Do not mark a mutant as ignored without a comment explaining why.

## UI And Visual Tests

The visual-regression suite lives in `tests_ui/` and runs through the UI test
runner. It covers Textual SVG snapshots and offscreen GUI rendering. Install the
optional UI test dependencies before expecting the full visual layer to run.

```sh
scripts/ui-tests/run_ui_tests.sh
```

After intentional visual changes, regenerate snapshots with:

```sh
scripts/ui-tests/update_snapshots.sh
```

See [`ui-testing.md`](ui-testing.md) and [`../tests_ui/README.md`](../tests_ui/README.md)
for visual-regression details.

## Stress Tests

Stress tests live under `scripts/stress/`. They are correctness and robustness
tests: they push hostile inputs, scale edges, resource pressure, and unusual I/O
states, then check for defined behavior. They may be heavier than unit tests, but
they are still correctness-oriented and are included in the default full suite.

```sh
scripts/stress/run_all.sh
```

Useful knobs include:

```sh
STRESS_FAST=1 scripts/stress/run_all.sh
KEEP_WORK=1 scripts/stress/run_all.sh
```

## Performance Tests

Performance tests live in `tests_perf/` and run through
`scripts/performance/run_all.sh`. They measure timing, throughput, memory,
scaling, or other resource behavior. Results depend on CPU, filesystem, Python
version, installed environment, and background load, so this layer is opt-in and
is not part of default pytest collection or the default full-suite run.

```sh
scripts/performance/run_all.sh
python3 -m pytest tests_perf
```

To stay meaningful without flaking, the lane separates its signal: deterministic
operation-count gates (the only hard assertions - e.g. a render reads each byte
once, an overlay lookup scans at most `nranges` ranges) plus advisory timing
envelopes that assert only under `PERF_STRICT=1`. `run_all.sh` also runs
subprocess CLI characterizations (wall-clock + peak RSS) that are reported, never
pass/fail. See [`tests_perf/README.md`](../tests_perf/README.md).

Keep stress and performance separate: stress tests are correctness gates for hard
or hostile cases; performance tests are environment-sensitive measurements.

## Full Suite Runner

Use the top-level runner when you want one command to run the default correctness
layers:

```sh
scripts/run-full-test-suite.sh
```

By default it runs:

1. `ruff check .`
2. `python3 -m pytest`
3. `scripts/coverage/run_coverage.sh`
4. `scripts/integration/run_all.sh`
5. `scripts/ui-tests/run_ui_tests.sh`
6. `scripts/stress/run_all.sh`

It skips performance tests by default with a message explaining how to opt in.
Pass `--include-performance` to add the performance runner:

```sh
scripts/run-full-test-suite.sh --include-performance
```

The runner fails fast by default. To run later layers after a failure and still
exit nonzero at the end if anything failed, use:

```sh
scripts/run-full-test-suite.sh --keep-going
scripts/run-full-test-suite.sh --include-performance --keep-going
```
