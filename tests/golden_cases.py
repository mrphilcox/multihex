# Copyright (c) 2026 Philip Cox
# SPDX-License-Identifier: Apache-2.0

"""The characterization contract: (name, scenario, extra_args) cases.

Shared by capture_goldens.py (writes goldens from the pre-refactor tool) and
test_multihex_characterization.py (asserts the post-refactor tool matches).
Each case runs ``multihex.py <scenario basenames> <extra_args>`` with cwd set
to the fixture dir, capturing stdout byte-for-byte.
"""

CASES = [
    # equal-length set (3 files, 70 bytes, width default 16)
    ("equal_default", "equal", []),
    ("equal_ref0", "equal", ["--ref", "0"]),
    ("equal_only_diff", "equal", ["--only-diff"]),
    ("equal_no_ascii", "equal", ["--no-ascii"]),
    ("equal_color_never", "equal", ["--color", "never"]),
    ("equal_color_always", "equal", ["--color", "always"]),
    ("equal_json", "equal", ["--json"]),
    ("equal_limit_rows", "equal", ["--limit-rows", "2"]),
    ("equal_around", "equal", ["--around", "0x20:32"]),
    ("equal_markers_single", "equal", ["--markers", "single"]),
    ("equal_markers_repeat", "equal", ["--markers", "repeat"]),
    ("equal_markers_none", "equal", ["--markers", "none"]),
    ("equal_markers_none_only_diff", "equal", ["--markers", "none", "--only-diff"]),

    # single-file: the marker strip defaults to hidden (no comparison partner);
    # an explicit --markers single still draws it.
    ("single_default", "single", []),
    ("single_markers_single", "single", ["--markers", "single"]),

    # unequal-length set (20 / 50 / 100 bytes); lengths chosen to run past EOF
    # and to be non-multiples of width (locks the partial last row).
    ("unequal_default", "unequal", []),
    ("unequal_length_full_past_eof", "unequal", ["--length", "0x80", "--width", "16"]),
    ("unequal_length_partial", "unequal", ["--length", "0x4a", "--width", "16"]),
    ("unequal_length_past_all", "unequal", ["--length", "0x96", "--width", "16"]),
    ("unequal_ref0", "unequal", ["--ref", "0", "--length", "0x40"]),
    ("unequal_ref1_only_diff", "unequal", ["--ref", "1", "--only-diff", "--length", "0x40"]),
    ("unequal_offset", "unequal", ["--offset", "0x10", "--length", "0x30"]),
    ("unequal_json", "unequal", ["--length", "0x30", "--json"]),
    ("unequal_color_always", "unequal", ["--length", "0x40", "--color", "always"]),

    # all-identical set
    ("identical_default", "identical", []),
    ("identical_only_diff", "identical", ["--only-diff"]),
    ("identical_ref0", "identical", ["--ref", "0"]),
    ("identical_json", "identical", ["--json"]),

    # all-differing set
    ("differing_default", "differing", []),
    ("differing_ref0", "differing", ["--ref", "0"]),
    ("differing_only_diff", "differing", ["--only-diff"]),
    ("differing_color_always", "differing", ["--color", "always"]),
    ("differing_json", "differing", ["--json"]),

    # empty + non-empty
    ("empty_default", "empty", []),
    ("empty_length", "empty", ["--length", "0x20"]),
    ("empty_json", "empty", ["--length", "0x20", "--json"]),
]
