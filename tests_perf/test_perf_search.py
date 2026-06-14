# Copyright (c) 2026 Philip Cox
# SPDX-License-Identifier: Apache-2.0

"""Performance guardrails for exact search (``search_files`` / ``_find_in_file``).

Search is ``memmem``-backed and linear in corpus size per file; case-insensitive
text additionally copies the whole file to fold case. Two tiers guard it:

* a deterministic **match-count gate** -- a corpus with a known number of
  planted needles returns exactly that many matches, in ``(file_index, offset)``
  order, for text and hex, with the documented overlap vs non-overlap counts; and
* an advisory **timing envelope** -- searching N, 2N, 4N bytes for an absent
  needle (forcing a full scan) stays within the doubling envelope, with the
  case-insensitive copy path reported alongside.
"""

from __future__ import annotations

import perflib

from multihex.core import (
    HexFile,
    make_hex_query,
    make_text_query,
    search_files,
)

NEEDLE = b"PERFNEDL"  # 8 bytes, no internal repeat of the whole needle


# -- match-count gates (deterministic) --------------------------------------- #
def test_text_search_finds_exactly_planted_matches():
    count = 50
    data, offsets = perflib.plant(NEEDLE, count, gap=64, fill=0x00)
    f = HexFile(path="c.bin", data=data)

    matches = search_files([f], make_text_query(NEEDLE.decode("ascii")))

    assert len(matches) == count
    assert [m.offset for m in matches] == offsets


def test_hex_search_matches_text_search_offsets():
    count = 30
    data, offsets = perflib.plant(NEEDLE, count, gap=48, fill=0x00)
    f = HexFile(path="c.bin", data=data)

    pattern = " ".join(f"{b:02x}" for b in NEEDLE)
    matches = search_files([f], make_hex_query(pattern))

    assert [m.offset for m in matches] == offsets


def test_multi_file_matches_ordered_by_file_then_offset():
    count = 10
    data, offsets = perflib.plant(NEEDLE, count, gap=32, fill=0x00)
    files = [HexFile(path="a.bin", data=data), HexFile(path="b.bin", data=data)]

    matches = search_files(files, make_text_query(NEEDLE.decode("ascii")))

    assert len(matches) == 2 * count
    keys = [(m.file_index, m.offset) for m in matches]
    assert keys == sorted(keys)
    assert all(m.file_index == 0 for m in matches[:count])
    assert all(m.file_index == 1 for m in matches[count:])


def test_overlap_flag_changes_match_count_deterministically():
    # "ABA" in "ABABABA": non-overlapping finds 2 (at 0, 4); overlapping finds
    # 3 (at 0, 2, 4). Both counts are fixed properties of the input.
    f = HexFile(path="c.bin", data=b"ABABABA")
    q = make_text_query("ABA")

    non_overlap = search_files([f], q)
    overlap = search_files([f], q, overlap=True)

    assert [m.offset for m in non_overlap] == [0, 4]
    assert [m.offset for m in overlap] == [0, 2, 4]


# -- advisory timing envelope ------------------------------------------------ #
def _absent_corpus(size):
    # All-zero corpus; the needle below never occurs, so every search scans the
    # whole buffer -- the linear worst case the envelope is meant to track.
    return HexFile(path="c.bin", data=bytes(size))


def test_case_sensitive_search_scaling_within_envelope(capsys):
    base = 1 << 20  # 1 MiB
    q = make_text_query("\x01" * 8)  # absent in an all-zero corpus
    points = []
    for mult in (1, 2, 4):
        f = _absent_corpus(base * mult)
        points.append((base * mult, perflib.best_of(lambda: search_files([f], q))))
    with capsys.disabled():
        perflib.report_envelope("search_text_cs", points)


def test_hex_search_scaling_within_envelope(capsys):
    base = 1 << 20
    q = make_hex_query("01 02 03 04 05 06 07 08")  # absent in all-zero corpus
    points = []
    for mult in (1, 2, 4):
        f = _absent_corpus(base * mult)
        points.append((base * mult, perflib.best_of(lambda: search_files([f], q))))
    with capsys.disabled():
        perflib.report_envelope("search_hex", points)


def test_case_insensitive_search_scaling_within_envelope(capsys):
    # Case-insensitive text folds a full copy of the file before scanning; the
    # envelope still holds (copy + scan are both linear), and the PERF line makes
    # the larger constant factor visible next to the case-sensitive run.
    base = 1 << 20
    q = make_text_query("zzzzzzzz", case_sensitive=False)  # absent in all-zero corpus
    points = []
    for mult in (1, 2, 4):
        f = _absent_corpus(base * mult)
        points.append((base * mult, perflib.best_of(lambda: search_files([f], q))))
    with capsys.disabled():
        perflib.report_envelope("search_text_ci", points)
