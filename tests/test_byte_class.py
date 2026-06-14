# Copyright (c) 2026 Philip Cox
# SPDX-License-Identifier: Apache-2.0

"""Pure byte-classification tests for multihex.core.classify_byte.

Classification is display-only and stdlib-only; these drive the helper directly.
"""

import os
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from multihex.core import ByteClass, classify_byte  # noqa: E402


@pytest.mark.parametrize(
    "value, expected",
    [
        (None, ByteClass.MISSING),
        (0x00, ByteClass.ZERO),
        (0x09, ByteClass.WHITESPACE),
        (0x0A, ByteClass.WHITESPACE),
        (0x0B, ByteClass.WHITESPACE),
        (0x0C, ByteClass.WHITESPACE),
        (0x0D, ByteClass.WHITESPACE),
        (0x20, ByteClass.WHITESPACE),       # space is whitespace, not printable
        # Control bytes that are not the recognized whitespace set fall to
        # OTHER, not WHITESPACE or PRINTABLE: 0x01..0x08 and 0x0E..0x1F.
        (0x01, ByteClass.OTHER),
        (0x08, ByteClass.OTHER),            # just below the 0x09 whitespace run
        (0x0E, ByteClass.OTHER),            # just above the 0x0D whitespace run
        (0x1F, ByteClass.OTHER),            # last control byte before space
        (0x21, ByteClass.PRINTABLE_ASCII),
        (0x41, ByteClass.PRINTABLE_ASCII),
        (0x7E, ByteClass.PRINTABLE_ASCII),
        (0x7F, ByteClass.OTHER),
        (0x80, ByteClass.OTHER),
        (0xFF, ByteClass.OTHER),
    ],
)
def test_classify_byte(value, expected):
    assert classify_byte(value) == expected
