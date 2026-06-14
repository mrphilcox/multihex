# multihex performance tests

This directory contains the runner for the opt-in performance-test layer in
`tests_perf/`.

Performance tests measure timing, throughput, memory, scaling, or resource
usage. They are different from stress tests: `scripts/stress/` probes
correctness and robustness under scale, hostile inputs, and unusual states, with
defined pass/fail behavior. Performance tests are environment-sensitive
measurements and should not be treated as default correctness gates.

Run the scaffold explicitly:

```sh
scripts/performance/run_all.sh
python3 -m pytest tests_perf
```

Additional pytest arguments are passed through by the runner:

```sh
scripts/performance/run_all.sh -q -k core_render
```

The layer is opt-in because wall-clock and resource results depend on the
machine, filesystem, Python version, installed environment, and current system
load. The initial smoke test records elapsed time but has no strict threshold,
no committed baseline, and no claim to be a benchmark. It exists to prove the
harness runs and produces a small result summary.

When adding future real benchmarks:

- generate deterministic inputs at runtime instead of committing large binaries;
- describe the operation, input scale, and output metric clearly;
- avoid machine-specific pass/fail thresholds unless the runtime environment is
  controlled;
- keep benchmark dependencies out unless there is a strong reason to add one;
- keep stress/correctness probes in `scripts/stress/`, not here.
