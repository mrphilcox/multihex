# Mutation runner

`scripts/mutation/run_mutation.sh` runs the targeted manual mutation-testing
audit for `multihex`:

```sh
scripts/mutation/run_mutation.sh
scripts/mutation/run_mutation.sh --paths-to-mutate src/multihex/shortcuts.py
```

The lane uses `mutmut` and the targets configured in `[tool.mutmut]` in
`pyproject.toml`. It is not part of a bare `python3 -m pytest`, not a CI gate,
and not a release blocker.

After a run, inspect results with:

```sh
mutmut results
mutmut show <ID>
mutmut browse
```

`mutmut` caches results in `.mutmut-cache`; delete that file to force a full
re-run. See `docs/TESTING.md` for the full workflow and survivor-triage policy.
