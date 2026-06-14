# Copyright (c) 2026 Philip Cox
# SPDX-License-Identifier: Apache-2.0

"""Performance-test local configuration.

Allow ``python3 -m pytest tests_perf`` to run from a checkout before an editable
install by putting ``src/`` on ``sys.path``, and make the lane's shared
``perflib`` helpers importable regardless of how pytest is invoked.
"""

from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
SRC = ROOT / "src"
for entry in (SRC, HERE):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))
