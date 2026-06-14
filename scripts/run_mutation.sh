#!/usr/bin/env bash
# Copyright (c) 2026 Philip Cox
# SPDX-License-Identifier: Apache-2.0

# Run a targeted, manual mutation-testing audit of the deterministic core.
#
# This is NOT part of `python3 -m pytest`, not a CI gate, and not a release
# blocker. It mutates only the stdlib-only modules configured in
# [tool.mutmut] in pyproject.toml (core, overlay, layout_overlay_v1, shortcuts,
# tui_config) and runs the default pytest suite against each mutant. The UI
# frontends are deliberately out of scope. See docs/TESTING.md.
#
# This script is non-destructive: it never applies a mutant to the working tree.
# Inspect results afterwards with `mutmut results` / `mutmut show <ID>` and
# remove the cache with `rm .mutmut-cache` to force a full re-run.
#
# mutmut restores each source file after testing a mutant, but a hard interrupt
# (Ctrl-C or a `timeout` kill) can leave the last mutant applied alongside a
# `<file>.bak`. If that happens, restore with `git checkout -- <file>` (or move
# the `.bak` back) and delete the leftover `.bak`.
#
# Any extra arguments are passed through to `mutmut run`, e.g. to scope a run:
#   scripts/run_mutation.sh --paths-to-mutate src/multihex/shortcuts.py
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

cd "$REPO_ROOT"

if ! command -v mutmut >/dev/null 2>&1; then
  echo "error: mutmut is not installed. Install the dev extra first:" >&2
  echo "       pip install -e '.[dev]'" >&2
  exit 1
fi

echo "Mutation testing for multihex (targeted, manual; not a CI gate)."
echo "Targets come from [tool.mutmut] in pyproject.toml; UI frontends are excluded."
echo

# Warn but do not abort on a dirty tree. The user may be intentionally inspecting
# an applied mutant or have unrelated local edits; mutmut still runs against the
# current working tree, so the choice is theirs.
if [ -n "$(git status --porcelain 2>/dev/null)" ]; then
  echo "warning: working tree is not clean; mutmut will mutate the current files." >&2
  echo "         Commit or stash first if you want a pristine baseline." >&2
  echo
fi

run_rc=0
mutmut run "$@" || run_rc=$?

echo
echo "Done (mutmut run exit status: ${run_rc})."
echo "Next:"
echo "  mutmut results        # list survived/killed mutants"
echo "  mutmut show <ID>      # inspect one mutant's diff"
echo "  mutmut browse         # interactive results browser"
echo
echo "A surviving mutant means the tests did not notice that change. Decide whether"
echo "it exposes a missing assertion before adding a focused test; do not chase the"
echo "score with brittle tests. See docs/TESTING.md."

# mutmut run exits non-zero when mutants survive. That is expected output for a
# manual audit, not a script failure, so report it without failing the script.
exit 0
