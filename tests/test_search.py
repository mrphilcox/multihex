# Copyright (c) 2026 Philip Cox
# SPDX-License-Identifier: Apache-2.0

"""Backend search tests: parser, exact search, multi-file, navigation.

Search semantics live entirely in multihex.core, so these tests drive the core
API directly. HexFile accepts a plain ``bytes`` backing, so files are built in
memory with no temp files.
"""

import os
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from multihex.core import (  # noqa: E402
    DEFAULT_SEARCH_MAX_RESULTS,
    HexFile,
    HexModel,
    SearchError,
    SearchMatch,
    SearchQuery,
    SearchResults,
    first_match_index,
    make_hex_query,
    make_text_query,
    match_index_after,
    match_index_before,
    next_match_index,
    parse_hex_pattern,
    prev_match_index,
    search_files,
    search_files_bounded,
)


def _file(name, data):
    return HexFile(path=name, data=bytes(data))


def _offsets(matches):
    return [m.offset for m in matches]


# --------------------------------------------------------------------------- #
# Hex parser
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "text",
    [
        "DE AD BE EF",
        "deadbeef",
        "0xDE 0xAD 0xBE 0xEF",
        "DE:AD:BE:EF",
        "de-ad-be-ef",
        "DE,AD,BE,EF",
        "  DE AD BE EF  ",
        "0xdeadbeef",
    ],
)
def test_parse_hex_valid_forms(text):
    assert parse_hex_pattern(text) == b"\xde\xad\xbe\xef"


@pytest.mark.parametrize(
    "text",
    [
        "D",            # single nibble
        "GG",           # non-hex chars
        "0x",           # bare 0x token
        "DE AD B",      # odd total digits
        "DE AD 0xZZ",   # non-hex in a token
        "",             # empty
        "   ",          # whitespace only
        ",",            # separators only -> no digits after tokenizing
        ":-,",          # every accepted separator, still no digits
    ],
)
def test_parse_hex_invalid_forms_raise(text):
    with pytest.raises(SearchError):
        parse_hex_pattern(text)


def test_make_hex_query_invalid_raises():
    with pytest.raises(SearchError):
        make_hex_query("GG")


def test_empty_needle_yields_no_matches_without_hanging():
    # The public query builders reject empty input, but search_files must still
    # be defensive: an empty needle has to terminate with zero matches rather
    # than spin (bytes.find("", start) always succeeds at `start`).
    f = _file("a", b"abc")
    query = SearchQuery(mode="hex", pattern="", needle=b"")
    assert search_files([f], query) == []


@pytest.mark.parametrize(
    "upper, lower",
    [
        ("D9", "d9"),
        ("DE AD BE EF", "de ad be ef"),
        ("0xDE 0xAD", "0xde 0xad"),
        ("DE:AD:BE:EF", "de:ad:be:ef"),
    ],
)
def test_parse_hex_case_insensitive_identical_bytes(upper, lower):
    # Hex digit case must not matter: both spellings yield identical bytes.
    assert parse_hex_pattern(upper) == parse_hex_pattern(lower)


def test_make_text_query_empty_raises():
    with pytest.raises(SearchError):
        make_text_query("")


# --------------------------------------------------------------------------- #
# Text search
# --------------------------------------------------------------------------- #
def test_text_simple_match():
    f = _file("a", b"....RIFF....")
    matches = search_files([f], make_text_query("RIFF"))
    assert _offsets(matches) == [4]
    assert matches[0].matched == b"RIFF"
    assert matches[0].length == 4
    assert matches[0].file_index == 0
    assert matches[0].path == "a"


def test_text_no_match():
    f = _file("a", b"no needle here")
    assert search_files([f], make_text_query("RIFF")) == []


def test_text_multiple_matches_non_overlapping():
    f = _file("a", b"abXXabXXab")
    assert _offsets(search_files([f], make_text_query("ab"))) == [0, 4, 8]


def test_text_match_at_offset_zero():
    f = _file("a", b"RIFFxxxx")
    assert _offsets(search_files([f], make_text_query("RIFF"))) == [0]


def test_text_match_at_eof_boundary():
    f = _file("a", b"xxxxRIFF")
    matches = search_files([f], make_text_query("RIFF"))
    assert _offsets(matches) == [4]
    # match runs exactly to the last byte
    assert matches[0].offset + matches[0].length == f.size


def test_text_case_sensitive_default_misses():
    f = _file("a", b"Content-Type: text")
    assert search_files([f], make_text_query("content-type")) == []


def test_text_case_insensitive_ascii_hits():
    f = _file("a", b"Content-Type: text")
    matches = search_files([f], make_text_query("content-type", case_sensitive=False))
    assert _offsets(matches) == [0]
    # matched bytes are the *original* casing, not folded
    assert matches[0].matched == b"Content-Type"


def test_case_insensitive_multiple_mixed_case():
    f = _file("a", b"FooFOOfoo")
    matches = search_files([f], make_text_query("foo", case_sensitive=False))
    assert _offsets(matches) == [0, 3, 6]


# --------------------------------------------------------------------------- #
# Hex search
# --------------------------------------------------------------------------- #
def test_hex_search_finds_bytes():
    f = _file("a", bytes([0x00, 0xDE, 0xAD, 0xBE, 0xEF, 0x00]))
    matches = search_files([f], make_hex_query("DE AD BE EF"))
    assert _offsets(matches) == [1]
    assert matches[0].matched == b"\xde\xad\xbe\xef"


# Hex search must match *byte values*, never the ASCII spelling of the hex
# input. This file holds byte 0xd9 at offset 0 and the ASCII text "D9"
# (bytes 0x44 0x39) at offset 1, so the two are unambiguously distinguishable.
_HEX_VS_ASCII = bytes([0xD9]) + b"D9"  # 0xd9, then 0x44 0x39


def test_hex_search_uppercase_finds_byte_not_ascii():
    f = _file("a", _HEX_VS_ASCII)
    assert _offsets(search_files([f], make_hex_query("D9"))) == [0]


def test_hex_search_lowercase_finds_same_byte():
    f = _file("a", _HEX_VS_ASCII)
    assert _offsets(search_files([f], make_hex_query("d9"))) == [0]


def test_hex_search_for_ascii_bytes_finds_the_ascii():
    f = _file("a", _HEX_VS_ASCII)
    # "44 39" is the byte form of ASCII "D9"; it should match offset 1, not 0.
    assert _offsets(search_files([f], make_hex_query("44 39"))) == [1]


def test_text_search_finds_ascii_spelling():
    f = _file("a", _HEX_VS_ASCII)
    # Text search for "D9" finds the ASCII bytes (offset 1), not the 0xd9 byte.
    assert _offsets(search_files([f], make_text_query("D9"))) == [1]


# --------------------------------------------------------------------------- #
# Overlap
# --------------------------------------------------------------------------- #
def test_overlap_default_non_overlapping():
    f = _file("a", bytes([0xAA, 0xAA, 0xAA]))
    assert _offsets(search_files([f], make_hex_query("AA AA"))) == [0]


def test_overlap_enabled():
    f = _file("a", bytes([0xAA, 0xAA, 0xAA]))
    assert _offsets(search_files([f], make_hex_query("AA AA"), overlap=True)) == [0, 1]


# --------------------------------------------------------------------------- #
# Multi-file
# --------------------------------------------------------------------------- #
def test_multi_file_match_in_one():
    f0 = _file("zero", b"nothing")
    f1 = _file("one", b"..RIFF")
    matches = search_files([f0, f1], make_text_query("RIFF"))
    assert [(m.file_index, m.offset) for m in matches] == [(1, 2)]


def test_multi_file_match_in_several_ordered():
    f0 = _file("zero", b"RIFF..RIFF")
    f1 = _file("one", b"xRIFF")
    matches = search_files([f0, f1], make_text_query("RIFF"))
    # deterministic order: (file_index, offset)
    assert [(m.file_index, m.offset) for m in matches] == [(0, 0), (0, 6), (1, 1)]


def test_file_index_selection_restricts():
    f0 = _file("zero", b"RIFF")
    f1 = _file("one", b"RIFF")
    q = make_text_query("RIFF", file_index=1)
    matches = search_files([f0, f1], q)
    assert [m.file_index for m in matches] == [1]


def test_file_index_out_of_range_raises():
    f0 = _file("zero", b"RIFF")
    q = make_text_query("RIFF", file_index=5)
    with pytest.raises(SearchError):
        search_files([f0], q)


def test_max_results_caps_in_order():
    f0 = _file("zero", b"aaaa")  # 'a' at 0,1,2,3
    f1 = _file("one", b"aa")
    matches = search_files([f0, f1], make_text_query("a"), max_results=3)
    assert [(m.file_index, m.offset) for m in matches] == [(0, 0), (0, 1), (0, 2)]


# --------------------------------------------------------------------------- #
# Bounded search (search_files_bounded): default cap + truncation reporting
# --------------------------------------------------------------------------- #
def test_bounded_returns_all_when_under_cap():
    f = _file("a", b"aaaa")  # 4 matches, well under any cap
    result = search_files_bounded([f], make_text_query("a"), max_results=10)
    assert isinstance(result, SearchResults)
    assert [m.offset for m in result.matches] == [0, 1, 2, 3]
    assert result.truncated is False
    assert result.limit == 10


def test_bounded_exactly_at_cap_is_not_truncated():
    f = _file("a", b"aaaa")  # exactly 4 matches
    result = search_files_bounded([f], make_text_query("a"), max_results=4)
    assert len(result.matches) == 4
    assert result.truncated is False


def test_bounded_one_past_cap_truncates_and_trims():
    f = _file("a", b"aaaaa")  # 5 matches, cap 4 -> drop one
    result = search_files_bounded([f], make_text_query("a"), max_results=4)
    assert [m.offset for m in result.matches] == [0, 1, 2, 3]
    assert result.truncated is True
    assert result.limit == 4


def test_bounded_cap_is_global_across_files():
    # The cap counts total matches, not per-file: 4 in f0 leaves room for 1 in f1.
    f0 = _file("zero", b"aaaa")
    f1 = _file("one", b"aa")
    result = search_files_bounded([f0, f1], make_text_query("a"), max_results=5)
    assert [(m.file_index, m.offset) for m in result.matches] == [
        (0, 0), (0, 1), (0, 2), (0, 3), (1, 0)
    ]
    assert result.truncated is True  # (1, 1) exists past the cap


def test_bounded_counts_post_overlap_matches():
    # "aa" in "aaaa": non-overlapping yields 2 (offsets 0, 2); the cap counts
    # those post-overlap matches, so cap 2 is not truncated.
    f = _file("a", b"aaaa")
    result = search_files_bounded([f], make_text_query("aa"), max_results=2)
    assert [m.offset for m in result.matches] == [0, 2]
    assert result.truncated is False
    # With overlap=True the same text yields 3 (offsets 0, 1, 2); cap 2 truncates.
    overlapped = search_files_bounded(
        [f], make_text_query("aa"), max_results=2, overlap=True
    )
    assert [m.offset for m in overlapped.matches] == [0, 1]
    assert overlapped.truncated is True


def test_bounded_unlimited_collects_everything():
    f = _file("a", b"aaaa")
    result = search_files_bounded([f], make_text_query("a"), max_results=None)
    assert len(result.matches) == 4
    assert result.truncated is False
    assert result.limit is None


def test_bounded_default_cap_bounds_large_repetitive_input():
    # The memory-safety regression: a one-byte needle over a large repetitive
    # buffer must stop at the default cap rather than collecting every byte.
    data = bytes(DEFAULT_SEARCH_MAX_RESULTS * 5)  # all zero bytes
    f = _file("big", data)
    result = search_files_bounded([f], make_hex_query("00"))
    assert len(result.matches) == DEFAULT_SEARCH_MAX_RESULTS
    assert result.truncated is True
    assert result.limit == DEFAULT_SEARCH_MAX_RESULTS


# --------------------------------------------------------------------------- #
# Row/column locate via a model
# --------------------------------------------------------------------------- #
def test_match_row_column_with_model():
    f = _file("a", bytes(range(40)))
    model = HexModel([f], start_offset=0, width=16)
    # 0x12 (18) sits at row 1, column 2
    matches = search_files([f], make_hex_query("12"), model=model)
    assert matches[0].offset == 0x12
    assert matches[0].row_index == 1
    assert matches[0].column == 2


def test_match_row_column_none_without_model():
    f = _file("a", b"..RIFF")
    matches = search_files([f], make_text_query("RIFF"))
    assert matches[0].row_index is None
    assert matches[0].column is None


# --------------------------------------------------------------------------- #
# Navigation helpers
# --------------------------------------------------------------------------- #
def _matches(*keys):
    return [
        SearchMatch(file_index=fi, path=str(fi), offset=off, length=1, matched=b"x")
        for fi, off in keys
    ]


def test_navigation_first():
    ms = _matches((0, 0), (0, 16), (1, 4))
    assert first_match_index(ms) == 0
    assert first_match_index([]) is None


def test_navigation_next_and_wrap():
    ms = _matches((0, 0), (0, 16), (1, 4))
    assert next_match_index(ms, 0) == 1
    assert next_match_index(ms, 2) == 0          # wrap
    assert next_match_index(ms, 2, wrap=False) is None
    assert next_match_index([], 0) is None


def test_navigation_prev_and_wrap():
    ms = _matches((0, 0), (0, 16), (1, 4))
    assert prev_match_index(ms, 2) == 1
    assert prev_match_index(ms, 0) == 2          # wrap
    assert prev_match_index(ms, 0, wrap=False) is None
    assert prev_match_index([], 0) is None


def test_navigation_after():
    ms = _matches((0, 0), (0, 16), (1, 4))
    assert match_index_after(ms, 0, 16) == 1                 # inclusive
    assert match_index_after(ms, 0, 16, inclusive=False) == 2
    assert match_index_after(ms, 0, 1) == 1                  # between
    assert match_index_after(ms, 1, 100) == 0               # wrap to first
    assert match_index_after(ms, 1, 100, wrap=False) is None
    assert match_index_after([], 0, 0) is None


def test_navigation_before():
    ms = _matches((0, 0), (0, 16), (1, 4))
    assert match_index_before(ms, 0, 16) == 1               # inclusive
    assert match_index_before(ms, 0, 16, inclusive=False) == 0
    assert match_index_before(ms, 1, 4) == 2
    assert match_index_before(ms, 0, -1) == 2               # wrap to last
    assert match_index_before(ms, 0, -1, wrap=False) is None
    assert match_index_before([], 0, 0) is None
