#!/usr/bin/env python3
# Copyright (c) 2026 Philip Cox
# SPDX-License-Identifier: Apache-2.0

"""Structural-validity guard for the committed example overlays.

Every `examples/layouts/*.overlay.json` must pass the layout-overlay-v1
*structural* validator (no source binary). Warnings are allowed — real formats
have legitimate encoding quirks (see examples/layouts/README.md "Type-mapping
caveats"). Error-severity diagnostics fail the test.
"""

import json
from pathlib import Path

import pytest

from multihex.layout_overlay_v1 import validate_structural

EXAMPLES_DIR = Path(__file__).resolve().parent.parent / "examples" / "layouts"
EXAMPLES = sorted(EXAMPLES_DIR.glob("*.overlay.json"))


def test_examples_present():
    """Guard against a vacuous pass if the examples dir is empty/missing."""
    assert EXAMPLES, f"no *.overlay.json found under {EXAMPLES_DIR}"


@pytest.mark.parametrize("path", EXAMPLES, ids=lambda p: p.name)
def test_example_overlay_structural_valid(path):
    doc = json.loads(path.read_text())
    result = validate_structural(doc)
    if not result.ok:
        details = "\n".join(
            f"  {path.name}: {d.code}: {d.message}" for d in result.errors
        )
        pytest.fail(f"{path.name} has error-severity diagnostics:\n{details}")
