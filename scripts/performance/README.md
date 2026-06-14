# multihex performance tests

This directory runs the opt-in performance lane. It is a SEPARATE validation lane
from the default unit tests: it is not part of a bare `python3 -m pytest`, the
integration runner, the UI runner, or the stress runner. In the full suite it is
gated behind `scripts/run-full-test-suite.sh --include-performance` and skipped
by default.

Performance tests measure timing, throughput, and scaling - environment-sensitive
measurements, not correctness gates. Correctness/robustness probes live in
`scripts/stress/`.

## Two stages

`run_all.sh` runs both, in order:

1. **In-process pytest guardrails** (`tests_perf/`). Deterministic
   operation-count gates (hard assertions that cannot flake) plus advisory timing
   envelopes. See `tests_perf/README.md` for the two-tier model and the `PERF`
   line format. Extra arguments are forwarded to pytest; `PERF_STRICT=1` turns
   the advisory ratios into assertions.

   ```sh
   scripts/performance/run_all.sh -q -k render
   PERF_STRICT=1 scripts/performance/run_all.sh
   ```

2. **Subprocess CLI characterizations.** The real `multihex` entry points are
   driven under `scripts/stress/measure.py`, which reports wall-clock seconds and
   peak RSS for paths that only matter as a whole process:
   - `--json` over three whole files - materializes every byte as a Python
     object before serializing, so its peak RSS is hundreds of times the input.
     A small input is used on purpose (the blow-up is visible at any size) with
     an RSS safety cap so a pathological run can never OOM the host.
   - case-insensitive `--search-text` over a large file - folds a full copy of
     the file before scanning.

   These are **informational**: they print numbers and never assert thresholds.
   Inputs are generated at runtime by `make_input.py` (seeded, no committed
   blobs) into a temp dir that is removed on exit.

Each characterization prints one line:

```
PERF_CHAR json_whole_file rc=0 secs=4.566 peak_kb=1403648 timed_out=0 rss_exceeded=0
```

- `rc` - the child's exit status; `secs` - wall-clock; `peak_kb` - peak RSS (kB).
- `timed_out` / `rss_exceeded` - whether the wall-clock or RSS safety ceiling was
  hit (the child is then killed and the run is bounded, not a host crash).
- `PERF_CHAR <label> SKIP reason=no-procfs` - `measure.py` needs Linux procfs;
  the characterizations skip cleanly elsewhere while the pytest guardrails still
  run (they are cross-platform).

## Tunables (environment variables)

| Variable | Default | Effect |
| --- | --- | --- |
| `PERF_STRICT` | unset | Assert the advisory timing ratios (stage 1). |
| `PERF_SEARCH_MB` | 16 | Size (MiB) of the large search input. |
| `PERF_JSON_MB` | 2 | Per-file size (MiB) of the three JSON inputs. |
| `PERF_JSON_RSS_CAP_MB` | 4096 | Peak-RSS safety ceiling for the JSON child. |
| `PERF_TIMEOUT` | 180 | Wall-clock ceiling (s) for each measured child. |
| `PYTHON` | `python3` | Interpreter used to run pytest and the children. |

## Adding characterizations

- Generate inputs at runtime; never commit binaries or assume a binary format.
- Keep them informational - describe operation, scale, and metric; do not add
  machine-specific pass/fail thresholds.
- Keep benchmark dependencies out; reuse the stdlib `measure.py`.
- Keep stress/correctness probes in `scripts/stress/`, not here.
