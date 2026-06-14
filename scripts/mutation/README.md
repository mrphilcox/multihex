# Mutation testing

This directory contains the manual mutation-testing lane for `multihex`.

Mutation testing changes source code one small edit at a time and reruns the
test suite. If the tests still pass, the changed code is a surviving mutant: it
may point to a behavior that is not asserted well enough. Use this lane as a
focused quality audit, not as a score to optimize.

## Scope

The runner uses `mutmut` and the targets configured in `[tool.mutmut]` in
`pyproject.toml`.

Currently mutated:

- `src/multihex/core.py`
- `src/multihex/overlay.py`
- `src/multihex/layout_overlay_v1.py`
- `src/multihex/shortcuts.py`
- `src/multihex/tui_config.py`

Currently excluded by omission:

- `src/multihex/tui.py` and `src/multihex/gui.py`: UI frontends are better
  covered by behavior tests, snapshots, and offscreen render checks.
- `src/multihex/cli.py`: command-line argument glue is covered by
  characterization and golden-output tests.
- `src/multihex/__init__.py`: version metadata only.

This lane is not part of a bare `python3 -m pytest`, not a normal CI gate, and
not a release blocker. It is intentionally scoped to deterministic,
stdlib-friendly code where a mutant usually has a clear behavioral meaning.

## Prerequisites

Install the development extra:

```sh
pip install -e '.[dev]'
```

The `dev` extra pins `mutmut` to the 2.x series. Do not casually upgrade to
`mutmut` 3.x; its config keys, cache behavior, and result workflow are
incompatible with this repo's current setup.

## Running

Run the configured mutation audit:

```sh
scripts/mutation/run_mutation.sh
```

Scope a run while iterating:

```sh
scripts/mutation/run_mutation.sh --paths-to-mutate src/multihex/shortcuts.py
```

Any extra arguments are passed through to `mutmut run`.

You can also include the mutation lane in the top-level suite explicitly:

```sh
scripts/run-full-test-suite.sh --include-mutation
scripts/run-full-test-suite.sh --all
```

The full-suite runner keeps mutation testing opt-in and runs it last because it
is slow and informational.

## Inspecting results

After a run:

```sh
mutmut results
mutmut show <ID>
mutmut browse
```

`mutmut results` lists killed and surviving mutants. `mutmut show <ID>` is the
most useful first step for triage because it shows the exact code change that
survived.

`scripts/mutation/run_mutation.sh` exits successfully even when `mutmut run`
returns nonzero because surviving mutants are expected audit findings, not a
script failure.

## Caching and reruns

`mutmut` caches results in `.mutmut-cache`, which is gitignored. Delete it to
force a full rerun:

```sh
rm .mutmut-cache
```

A full run reruns the default pytest suite once per mutant, so prefer scoped
runs while developing a focused test.

## Working tree safety

The runner warns, but does not abort, when the working tree is dirty. That is
deliberate: you may be inspecting an applied mutant, working on an unrelated
change, or testing a local draft. Remember that `mutmut` mutates the current
files it sees, so commit or stash first if you need a pristine baseline.

Normal `mutmut` runs restore each file after testing a mutant. A hard interrupt
such as Ctrl-C or an external `timeout` kill can leave the last mutant applied
next to a `<file>.bak`. If that happens:

```sh
git status --short
mutmut show <ID>  # if you know which mutant was active
```

Then restore the affected file from git or move the `.bak` back, and delete the
leftover `.bak`. Do not restore unrelated user edits.

## Survivor triage

Treat a surviving mutant as a prompt to inspect behavior:

1. Run `mutmut show <ID>` and read the diff.
2. Decide whether the mutated behavior is observable and meaningful.
3. If it exposes a real gap, add a focused test for that behavior.
4. If it is equivalent or irrelevant, document the reason if you decide to
   ignore it.

Do not add brittle tests only to improve the mutation score. A useful mutation
test follow-up should describe behavior the project actually cares about:
fixed-offset comparison semantics, exact search behavior, overlay validation,
shortcut registry consistency, or persisted TUI preference parsing.

See `docs/TESTING.md` for how this lane fits into the broader test strategy.
