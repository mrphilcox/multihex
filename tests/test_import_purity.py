# Copyright (c) 2026 Philip Cox
# SPDX-License-Identifier: Apache-2.0

"""Guard the stdlib-only invariant for the comparison core and shortcut registry.

``multihex.core`` and ``multihex.shortcuts`` are promised to import only the
standard library (README / docs / AGENTS all rely on it: the core is what keeps
``multihex`` installable and runnable without any frontend extra). A regression
that pulls a third-party dependency into either module would silently break that
contract.

The check runs in a *clean subprocess*: by the time this test executes, pytest
itself and the headless TUI/GUI tests may already have imported ``textual``,
``rich``, ``PySide6``, ``pytest`` etc. into the running interpreter, so an
in-process ``sys.modules`` inspection would report those regardless of what the
core actually pulls in. A fresh interpreter that imports only the two target
modules gives an honest answer.
"""

import os
import subprocess
import sys
from pathlib import Path

# Top-level (first dotted component) names of every declared frontend and test
# dependency in pyproject.toml. None of these may appear after importing the
# core/shortcuts modules. This is an explicit forbid-list of known third-party
# packages rather than a stdlib allow-list, which would be brittle across
# Python versions.
FORBIDDEN_TOP_LEVEL = {
    "textual",
    "rich",
    "PySide6",
    "shiboken6",  # PySide6's companion runtime
    "pytest",
    "_pytest",
    "pluggy",
    "tomli",
    "pytest_textual_snapshot",
}

# Print the top-level name of every module loaded after importing the two
# modules under test, one per line.
_PROBE = (
    "import sys\n"
    "import multihex.core\n"
    "import multihex.shortcuts\n"
    "names = sorted({m.split('.', 1)[0] for m in sys.modules})\n"
    "print('\\n'.join(names))\n"
)


def test_core_and_shortcuts_import_only_stdlib():
    repo_root = Path(__file__).resolve().parent.parent
    src = repo_root / "src"

    env = dict(os.environ)
    # Make ``multihex`` importable in the child whether or not it was installed
    # as an editable package, without depending on the parent's sys.path.
    existing = env.get("PYTHONPATH")
    env["PYTHONPATH"] = str(src) + (os.pathsep + existing if existing else "")

    result = subprocess.run(
        [sys.executable, "-c", _PROBE],
        capture_output=True,
        text=True,
        env=env,
        check=True,
    )

    loaded = set(result.stdout.split())
    leaked = sorted(FORBIDDEN_TOP_LEVEL & loaded)
    assert not leaked, (
        "multihex.core / multihex.shortcuts pulled in forbidden third-party "
        f"module(s): {leaked}. These modules must import only the standard "
        "library."
    )
