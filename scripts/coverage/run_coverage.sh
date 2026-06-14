#!/usr/bin/env bash
# Copyright (c) 2026 Philip Cox
# SPDX-License-Identifier: Apache-2.0

# Run the default pytest suite with subprocess-aware coverage.
#
# Most CLI tests execute `python -m multihex.cli` in child processes. The
# COVERAGE_PROCESS_START + sitecustomize.py path below makes those children
# record coverage fragments that are combined before reporting.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

fail_under=80
make_html=0
make_xml=0

usage() {
  cat <<EOF
Usage: scripts/coverage/run_coverage.sh [--html] [--xml] [--fail-under N]

Runs the default pytest suite with subprocess-aware coverage, prints a terminal
summary, and fails if total coverage is below the threshold.

Options:
  --html          Also write an HTML report to htmlcov/
  --xml           Also write an XML report to coverage.xml
  --fail-under N  Override the default coverage threshold (${fail_under}%)
  -h, --help      Show this help text
EOF
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --html)
      make_html=1
      ;;
    --xml)
      make_xml=1
      ;;
    --fail-under)
      if [ "$#" -lt 2 ]; then
        echo "--fail-under requires a value" >&2
        usage >&2
        exit 2
      fi
      fail_under="$2"
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown option: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
  shift
done

cd "$REPO_ROOT"

echo "Coverage run for multihex"
echo "Default pytest suite only; integration, UI/visual, stress, and performance are separate."
echo "Fail-under threshold: ${fail_under}%"
echo

# Avoid mixing old coverage fragments into this run. Keep the cleanup limited to
# coverage.py files in the repository root.
find "$REPO_ROOT" -maxdepth 1 \( -name ".coverage" -o -name ".coverage.*" \) -type f -delete

export COVERAGE_FILE="$REPO_ROOT/.coverage"
export COVERAGE_PROCESS_START="$REPO_ROOT/pyproject.toml"
export PYTHONPATH="$REPO_ROOT:$REPO_ROOT/src${PYTHONPATH:+:$PYTHONPATH}"

python3 -m coverage run -m pytest
unset COVERAGE_PROCESS_START
python3 -m coverage combine

echo
report_rc=0
python3 -m coverage report -m --fail-under "$fail_under" || report_rc=$?
total="$(python3 -m coverage report --format=total)"
echo "Total coverage: ${total}%"

if [ "$report_rc" -ne 0 ]; then
  exit "$report_rc"
fi

if [ "$make_html" -eq 1 ]; then
  echo
  python3 -m coverage html
  echo "HTML coverage report: htmlcov/index.html"
fi

if [ "$make_xml" -eq 1 ]; then
  echo
  python3 -m coverage xml -o coverage.xml
  echo "XML coverage report: coverage.xml"
fi
