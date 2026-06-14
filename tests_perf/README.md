# Performance tests (`tests_perf/`)

This directory is the opt-in performance-test layer for `multihex`. It guards the
paths that actually cost something - the render loop, exact search, overlay range
lookup, and JSON row building - against algorithmic regressions, without ever
failing on a slow or loaded machine.

Performance tests measure timing, throughput, and scaling. They are separate from
stress tests: `scripts/stress/` probes correctness and robustness under hostile
and oversized inputs; this layer records how representative operations scale.

## How it stays meaningful without flaking: two tiers

A perf test that flakes on a busy host is worse than none, so the signal is split
in two:

1. **Operation-count gates (deterministic; the only hard assertions).** These
   count work, not time, so they cannot flake and they lock in complexity:
   - `build_row` reads each in-bounds byte exactly once and never reads a missing
     byte (render stays O(ncols x nfiles) per row, no re-scan);
   - a corpus with a known number of planted needles returns exactly that many
     matches, in order, with fixed overlap/non-overlap counts;
   - a single overlay `covers`/`ranges_at` lookup invokes `OverlayRange.covers`
     at most `nranges` times (lookup stays O(nranges) - a nested scan would show
     up as O(nranges**2) and fail).

   Instrumentation lives entirely test-side (a counting buffer; a `monkeypatch`
   of `OverlayRange.covers`); `src/multihex` is never touched.

2. **Timing envelopes (advisory by default).** Each measured operation is run at
   N, 2N, 4N and the doubling ratios are reported. A ratio of two same-host,
   same-process measurements is self-normalising - not a host-speed threshold -
   so it stays meaningful across machines. By default the ratios are only
   printed; set `PERF_STRICT=1` to assert that each doubling stays within a
   generous envelope (`ceiling=3.0`, well above the linear ideal of 2.0).
   Samples below timer resolution are reported but never gated.

`classify_byte` is intentionally not covered: it is O(1) per byte, so a
micro-benchmark would be noise with no regression value - its cost rides in the
render envelope. Whole-file JSON *memory* is not asserted here either (portable
in-process RSS gating is unreliable); it is characterised as a subprocess
peak-RSS measurement in `scripts/performance/run_all.sh`.

## Running

The lane is excluded from the default test run: `pyproject.toml` sets
`testpaths = ["tests"]`, so a bare `python3 -m pytest` does not collect this
sibling directory. Run it explicitly:

```sh
scripts/performance/run_all.sh          # pytest guardrails + subprocess characterizations
python3 -m pytest tests_perf            # pytest guardrails only
PERF_STRICT=1 python3 -m pytest tests_perf   # turn the advisory ratios into gates
```

## Reading the output

Each timing test prints a `PERF` line; the subprocess stage prints `PERF_CHAR`:

```
PERF render_rows n=2000:0.031s n=4000:0.062s n=8000:0.124s | doubling_ratios=2.00x 1.99x ceiling=3.0 strict=0
PERF_CHAR json_whole_file rc=0 secs=4.566 peak_kb=1403648 timed_out=0 rss_exceeded=0
```

- `n=<scale>:<seconds>` - the best-of-N (minimum) time at each input size.
- `doubling_ratios` - `seconds[2N]/seconds[N]`, ...; near `2.0x` means linear.
- `strict` - whether the ratios were asserted (`PERF_STRICT`) on this run.
- `PERF_CHAR ... peak_kb=` - peak RSS of a whole CLI process (see the scripts
  README); informational, never a pass/fail.

## Adding a benchmark

- Prefer a deterministic op-count gate; reach for a timing envelope only for what
  a count cannot capture, and keep it advisory.
- Generate inputs at runtime with the seeded helpers in `perflib.py`; never
  commit binary blobs and never assume a binary format.
- If a path cannot get a stable, meaningful signal, leave it out and say why
  rather than ship a flaky test.
