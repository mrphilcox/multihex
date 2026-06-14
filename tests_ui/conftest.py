# Copyright (c) 2026 Philip Cox
# SPDX-License-Identifier: Apache-2.0

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

# Make the Textual/Rich SVG snapshots reproducible across Rich/Textual versions.
#
# Rich's ``Console.export_svg(unique_id=...)`` uses ``unique_id`` as the *whole*
# CSS class/id prefix. Left to its default it is a version-dependent value such
# as ``terminal-<random-number>`` that pytest-textual-snapshot's normalizer
# (which only strips the purely-numeric ``terminal-\d+-`` form) may not remove --
# so committed baselines fail for contributors whose installed Rich/Textual emit
# a different id scheme. We pin it to ``terminal-0``, which the plugin always
# normalizes back to ``terminal-matrix``. This touches only the generated
# identifier, never the visible content/layout, so snapshots still catch real
# rendering regressions. Run before any screenshot is taken (module import time).
try:
    import rich.console as _rich_console

    _orig_export_svg = _rich_console.Console.export_svg

    def _export_svg_fixed(self, *args, unique_id=None, **kwargs):
        return _orig_export_svg(self, *args, unique_id=unique_id or "terminal-0", **kwargs)

    _rich_console.Console.export_svg = _export_svg_fixed
except Exception:  # rich absent (textual not installed) -> TUI snapshot tests skip
    pass
