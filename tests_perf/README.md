# Performance smoke tests (`tests_perf/`)

This directory is the opt-in performance-test layer for `multihex`.

Performance tests measure elapsed time, throughput, memory, scaling, or other
resource behavior. They are separate from stress tests: stress tests are
correctness and robustness probes for hostile inputs, large inputs, and unusual
states; performance tests record how representative operations behave on a
particular machine.

They are intentionally excluded from the default test run. The project sets
`testpaths = ["tests"]` in `pyproject.toml`, so a bare `python3 -m pytest` does
not collect this sibling directory. Run this layer explicitly:

```sh
scripts/performance/run_all.sh
python3 -m pytest tests_perf
```

The initial test is only a harness smoke test. It generates deterministic binary
fixtures, renders a bounded core view, records elapsed time with
`time.perf_counter()`, prints a small summary, and asserts only structural
validity. It has no strict timing threshold and no committed baseline because
wall-clock results vary by CPU, filesystem, Python version, background load, and
virtualization.

Future real benchmarks should be added deliberately:

- keep fixtures deterministic and generated at runtime;
- label what operation and scale are being measured;
- avoid machine-specific pass/fail thresholds unless the environment is
  controlled;
- prefer summaries that are easy to compare across local runs;
- keep correctness assertions basic and leave hostile-input regression gates in
  `scripts/stress/`.
