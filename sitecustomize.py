# Copyright (c) 2026 Philip Cox
# SPDX-License-Identifier: Apache-2.0

"""Subprocess coverage bootstrap.

Most CLI tests run the tool in a child process (``python -m multihex.cli``),
which a plain ``coverage run`` cannot see. ``coverage.process_startup()`` makes
those children record coverage too, but only when the ``COVERAGE_PROCESS_START``
environment variable points at a coverage config; without it the call is a
no-op. So this file is inert during normal use and only activates during a
coverage run that opts in (see CONTRIBUTING.md "Coverage").

For child processes to import this module it must be on their ``sys.path``; the
documented coverage command sets ``PYTHONPATH`` to the repository root with an
absolute path so the fixture-dir working directory of each child does not hide
it. If ``coverage`` is not installed the import simply does nothing.
"""

try:
    import coverage

    coverage.process_startup()
except Exception:
    pass
