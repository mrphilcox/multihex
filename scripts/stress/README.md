# multihex stress suite

A **standalone, opt-in** validation lane that probes where multihex breaks down
under **scale, resource pressure, and hostile inputs** — not a re-test of
correctness on normal inputs. It is deliberately kept out of the default lanes:

- not collected by `pytest` (the default `python3 -m pytest` run),
- not part of `scripts/integration/run_all.sh`,
- not wired into any automatic CI lane.

Run it explicitly:

```bash
scripts/stress/run_all.sh                 # full suite
STRESS_FAST=1 scripts/stress/run_all.sh   # quick harness smoke (shrunk scales)
KEEP_WORK=1 scripts/stress/run_all.sh     # keep temp dirs for inspection
scripts/stress/run_stress_search.sh       # one dimension on its own
```

## What it asserts

Each test has a concrete pass criterion — a **hard bound** or a **defined
failure mode**. The suite prints one verdict per test:

| Verdict | Meaning |
|---|---|
| `PASS` | a hard bound held (a real regression gate) |
| `FAIL` | a hard bound or defined mode was violated — a regression or new defect |
| `SKIP` | a resource was unavailable (no procfs, no `/dev/full`, no sparse FS, can't lower `ulimit`, `textual`/`PySide6` absent) |
| `FINDING` | a probe confirmed a **documented hazard** (a hang, an uncaught-error traceback, an unbounded match list). Counts as a pass — the test did its job — but is flagged for the report |
| `CHAR` | a characterization line recording an observed ceiling (peak RSS / seconds) for a known, generously bounded limit |

A `FINDING`/`CHAR` is **not** a failure. The script exits non-zero only on `FAIL`.
Because defined-mode probes assert the *specific* hazard (a timeout, a traceback
naming `RecursionError`, an exit code + message token), they flip to `FAIL` if
upstream behaviour silently changes — they are not unconditional passes.

## Safety

The suite is safe to run on a developer workstation:

- **`measure.py`** runs every heavy/hostile command in its own process group with
  a wall-clock timeout and an optional RSS cap (`--rss-cap-kb`), `SIGKILL`-ing the
  whole group if either is exceeded. An unbounded-memory defect cannot OOM the
  host; a hang cannot leak a blocked process. It measures peak RSS from procfs
  (`VmHWM`) and `SKIP`s cleanly where procfs is absent.
- Large-file tests use **sparse files** (`truncate`) that allocate ~no real disk;
  the suite checks free space and sparse support first and `SKIP`s otherwise.
- All fixtures are generated at runtime; **no large binaries are committed**.
- Everything is created under a `mktemp -d` work dir and cleaned on exit
  (including on failure) via a consolidated cleanup stack; `chmod`/`ulimit`
  changes are scoped or restored so they never leak to sibling tests.

## Env knobs

| Variable | Default | Effect |
|---|---|---|
| `KEEP_WORK` | `0` | `1` preserves each script's temp dir and prints its path |
| `STRESS_FAST` | `0` | `1` shrinks every scale dimension (sparse size, search size, range counts) for a fast smoke of the harness itself |
| `STRESS_LARGE_GIB` | `8` | sparse file size for the large-file dimension, in GiB |
| `STRESS_SEARCH_MIB` | `256` | data size for the case-insensitive-search characterization, in MiB |
| `PYTHON` | `python3` | interpreter used for the tool and the helpers |

## Layout

```
scripts/stress/
  lib.sh                    shared helpers (counters, measure, guards, cleanup, CHAR/FINDING)
  measure.py                subprocess supervisor: VmHWM poll + timeout/RSS-cap killpg
  gen_overlay.py            synthetic overlay JSON generator (ranges/overlap/extreme/nested/big)
  run_stress_*.sh           one script per stress dimension
  run_all.sh                aggregator
```

## Dimensions

| Script | Probes |
|---|---|
| `run_stress_degenerate.sh` | empty / 1-byte / single-repeated-byte files, `/dev/zero`, `/dev/null` |
| `run_stress_output.sh` | SIGPIPE (closed pipe), `/dev/full` on stdout/stderr (ENOSPC), SIGINT mid-dump |
| `run_stress_access.sh` | unreadable file/dir, directory-as-file, broken/looping symlink, FIFO-no-writer hang, truncate-after-mmap (SIGBUS) |
| `run_stress_args.sh` | extreme `--offset` (2³¹/2³²/2⁶³−1), huge `--width`/`--length` (no upper bound) |
| `run_stress_many_files.sh` | hundreds of files at once, FD exhaustion past `ulimit -n` |
| `run_stress_search.sh` | repeated-byte match explosion (capped vs uncapped), case-insensitive full-file copy, boundary patterns |
| `run_stress_large_files.sh` | navigation to EOF and search over a multi-GiB sparse file (mmap demand-paging) |
| `run_stress_overlay.sh` | 100k-range overlays, heavy overlap, extreme offsets, deeply nested JSON, large overlay files |
| `run_stress_ui.sh` | headless TUI (extreme terminal dims) and GUI (offscreen render) under saturated overlays |
