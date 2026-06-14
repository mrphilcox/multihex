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
3. `scripts/integration/run_all.sh`
4. `scripts/ui-tests/run_ui_tests.sh`
5. `scripts/stress/run_all.sh`

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
