# Copyright (c) 2026 Philip Cox
# SPDX-License-Identifier: Apache-2.0

"""Performance-test local configuration.

Allow ``python3 -m pytest tests_perf`` to run from a checkout before an editable
install by putting ``src/`` on ``sys.path``.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))
