"""Shared setup for the opt-in UI visual-regression suite (``tests_ui/``).

This directory is deliberately NOT collected by a bare ``pytest`` run: the
project's ``[tool.pytest.ini_options] testpaths = ["tests"]`` restricts default
discovery to ``tests/``. Run this layer explicitly:

    scripts/ui-tests/run_ui_tests.sh      # or: python3 -m pytest tests_ui

See ``tests_ui/README.md`` for what these cover and how to update snapshots.
"""

import os

# Render Qt headlessly so the GUI tests need no display server. Set before any
# PySide6 import happens in this suite; ``setdefault`` lets an outer override
# (e.g. a contributor forcing ``xcb``) still win.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
