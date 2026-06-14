#!/usr/bin/env bash
# Run every multihex integration script and aggregate the result.
#
#     scripts/integration/run_all.sh
#
# Each sub-script owns its own temp dir, cleanup, and PASS/FAIL/SKIP output;
# this wrapper just runs them and exits non-zero if any failed. Honour KEEP_WORK=1
# (passed through the environment) to preserve sub-script temp dirs.
set -uo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

SCRIPTS=(run_smoke.sh run_layout_overlay.sh run_examples.sh)
failed=0

for s in "${SCRIPTS[@]}"; do
  printf '\n==== %s ====\n' "$s"
  if ! "$DIR/$s"; then
    failed=$((failed + 1))
  fi
done

printf '\n========================\n'
if [ "$failed" -eq 0 ]; then
  echo "All integration scripts passed."
else
  echo "==> $failed integration script(s) failed."
fi
exit "$( [ "$failed" -eq 0 ] && echo 0 || echo 1 )"
