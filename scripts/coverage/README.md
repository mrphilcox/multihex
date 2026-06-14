# Coverage runner

`scripts/coverage/run_coverage.sh` runs the default pytest suite with
subprocess-aware coverage:

```sh
scripts/coverage/run_coverage.sh
scripts/coverage/run_coverage.sh --html
scripts/coverage/run_coverage.sh --xml
scripts/coverage/run_coverage.sh --fail-under 65
```

The default run prints a terminal report and a clear total percentage. It does
not write HTML or XML reports unless requested; `--html` writes `htmlcov/`, and
`--xml` writes `coverage.xml`.

The runner sets `COVERAGE_PROCESS_START` and an absolute `COVERAGE_FILE`, then
puts the repository root on `PYTHONPATH` so CLI subprocesses can import
`sitecustomize.py`. That is required because many CLI tests execute
`python -m multihex.cli` in child processes; a plain `coverage run -m pytest`
would undercount those paths.

The default threshold is `80%`, roughly ten absolute percentage points below the
current measured total. It is a coarse regression guard for meaningful drops,
not a target to chase and not a 100% coverage policy.
