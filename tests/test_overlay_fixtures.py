# Copyright (c) 2026 Philip Cox
# SPDX-License-Identifier: Apache-2.0

"""Negative-path coverage for the layout-overlay v1 validator's diagnostic codes.

Driven by the deliberately-broken fixtures from `layout-3.zip`, copied into
`tests/fixtures/overlays/invalid/`. `manifest.json` is the machine-readable
source of truth: each entry names the fixture, its validation `layer`, and the
diagnostic `code`/`severity` the validator emits today (the original snake_case
names from the zip are preserved as `suggested_code`). The test loads the
manifest at collection time and asserts each fixture against the actual
validator output -- no in-test code translation.

Two defects the validator does not detect yet (`validator_gap: true`) are
xfailed strict, so they go green now and fail loudly once the validator learns
to catch them (the signal to drop the xfail). See the gap report in the plan.
"""

import glob
import hashlib
import json
import os
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from multihex import layout_overlay_v1  # noqa: E402

FIXTURE_DIR = os.path.join(HERE, "fixtures", "overlays", "invalid")
MANIFEST_PATH = os.path.join(FIXTURE_DIR, "manifest.json")

with open(MANIFEST_PATH, encoding="utf-8") as _f:
    MANIFEST = json.load(_f)

FIXTURES = MANIFEST["fixtures"]


def _load_doc(name):
    with open(os.path.join(FIXTURE_DIR, name), encoding="utf-8") as f:
        return json.load(f)


def _sample_bytes():
    with open(os.path.join(FIXTURE_DIR, MANIFEST["companion_file"]), "rb") as f:
        return f.read()


def test_manifest_files_exist_on_disk():
    """Every file the manifest references is actually present."""
    missing = [
        fx["file"] for fx in FIXTURES
        if not os.path.isfile(os.path.join(FIXTURE_DIR, fx["file"]))
    ]
    assert not missing, f"manifest lists files not on disk: {missing}"
    assert os.path.isfile(os.path.join(FIXTURE_DIR, MANIFEST["companion_file"]))


def test_no_unlisted_invalid_fixtures():
    """No invalid_*.json on disk is missing from the manifest (and vice versa)."""
    on_disk = {
        os.path.basename(p)
        for p in glob.glob(os.path.join(FIXTURE_DIR, "invalid_*.json"))
    }
    listed = {fx["file"] for fx in FIXTURES}
    assert on_disk == listed, (
        f"on disk but unlisted: {sorted(on_disk - listed)}; "
        f"listed but missing: {sorted(listed - on_disk)}"
    )


def test_sample_sha256_matches_manifest():
    """The companion binary on disk matches the manifest's recorded hash."""
    actual = hashlib.sha256(_sample_bytes()).hexdigest()
    assert actual == MANIFEST["companion_sha256"]


def _param(fx):
    marks = []
    if fx.get("validator_gap"):
        marks.append(pytest.mark.xfail(
            reason=f"validator gap: {fx['description']}", strict=True))
    return pytest.param(fx, id=fx["file"], marks=marks)


@pytest.mark.parametrize("fx", [_param(fx) for fx in FIXTURES])
def test_fixture_emits_expected_diagnostic(fx):
    """The validator emits the manifest's expected code at the right severity."""
    doc = _load_doc(fx["file"])
    if fx["layer"] == "structural":
        result = layout_overlay_v1.validate_structural(doc)
    elif fx["layer"] == "file-aware":
        result = layout_overlay_v1.validate(doc, _sample_bytes())
    else:
        raise AssertionError(f"unknown layer {fx['layer']!r} in manifest")

    returned = [(d.code, d.severity, d.message) for d in result.diagnostics]
    detail = (
        f"\nfixture: {fx['file']} (layer={fx['layer']})"
        f"\nexpected: code={fx['expected_code']!r} severity={fx['severity']!r}"
        f"\nreturned diagnostics: {returned}"
    )

    matches = [d for d in result.diagnostics if d.code == fx["expected_code"]]
    assert matches, f"expected code not emitted.{detail}"
    assert matches[0].severity == fx["severity"], f"severity mismatch.{detail}"
