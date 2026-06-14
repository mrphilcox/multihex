#!/usr/bin/env python3
"""multihex_core.py - shared core for multihex.py and multihex-tui.py.

Stdlib-only. This module owns all the *meaning* of a multi-file hex
comparison so that the batch frontend and the interactive TUI frontend
behave identically. It provides:

  * file loading            -> load_files()
  * the row model           -> HexModel / Row
  * marker computation      -> HexModel._markers()
  * cell formatting         -> format_byte() / format_ascii() / render_row_text()

Design notes / semantics (per spec):
  * Always compare *fixed* offsets. No inference, no resync, no alignment.
  * Missing bytes (offset past a file's end) display as "--".
  * Missing bytes are always marked as different.
  * Without --ref, a column marker means "all files agree".
  * With --ref INDEX, a column marker means "every file equals the
    reference file at that column" (a missing reference byte => differ).
  * Integer parsing matches multihex.py: int(x, 0).
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import List, Optional, Sequence, Union


def parse_int(text: str) -> int:
    """Parse an integer the same way multihex.py does: ``int(x, 0)``.

    Accepts decimal, 0x.. (hex), 0o.. (octal), 0b.. (binary), with an
    optional leading sign.
    """
    return int(text, 0)


# --------------------------------------------------------------------------- #
# Files
# --------------------------------------------------------------------------- #
@dataclass
class HexFile:
    """A single loaded binary file."""

    path: str
    data: bytes

    @property
    def size(self) -> int:
        return len(self.data)

    def byte_at(self, offset: int) -> Optional[int]:
        """Return the byte value at ``offset`` or ``None`` if out of range."""
        if 0 <= offset < len(self.data):
            return self.data[offset]
        return None

    def display_name(self, mode: str = "basename") -> str:
        if mode == "path":
            return self.path
        return os.path.basename(self.path)


def load_files(paths: Sequence[str]) -> List[HexFile]:
    """Load every path fully into memory. Raises OSError on failure."""
    files: List[HexFile] = []
    for p in paths:
        with open(p, "rb") as fh:
            files.append(HexFile(path=p, data=fh.read()))
    return files


# --------------------------------------------------------------------------- #
# Row model
# --------------------------------------------------------------------------- #
@dataclass
class Row:
    """One block of the display: ``width`` columns across every file."""

    offset: int
    # One list per file, each of length ``width``; entries are byte (0..255)
    # or None for "missing" (past that file's end).
    cells: List[List[Optional[int]]]
    # One bool per column; True means "this column differs".
    markers: List[bool]

    @property
    def has_diff(self) -> bool:
        return any(self.markers)


class HexModel:
    """Builds rows and computes markers for a fixed offset grid.

    The offset grid is fixed at construction: row ``i`` starts at
    ``start_offset + i * width``. Navigation/filtering belong to the
    frontend; the model only answers "what is in row i".
    """

    def __init__(
        self,
        files: List[HexFile],
        *,
        start_offset: int = 0,
        width: int = 16,
        ref: Optional[int] = None,
    ) -> None:
        if not files:
            raise ValueError("need at least one file")
        if width <= 0:
            raise ValueError("width must be positive")
        if start_offset < 0:
            raise ValueError("offset must not be negative")
        if ref is not None and not (0 <= ref < len(files)):
            raise ValueError(
                f"reference index {ref} out of range 0..{len(files) - 1}"
            )
        self.files = files
        self.start_offset = start_offset
        self.width = width
        self.ref = ref
        self.max_size = max(f.size for f in files)

    @property
    def row_count(self) -> int:
        span = self.max_size - self.start_offset
        if span <= 0:
            return 0
        return (span + self.width - 1) // self.width

    def row_offset(self, index: int) -> int:
        return self.start_offset + index * self.width

    def index_for_offset(self, offset: int) -> int:
        """Row index whose block contains ``offset`` (clamped to range)."""
        if self.row_count == 0:
            return 0
        if offset <= self.start_offset:
            return 0
        idx = (offset - self.start_offset) // self.width
        return min(idx, self.row_count - 1)

    def build_row(self, index: int) -> Row:
        off = self.row_offset(index)
        cells: List[List[Optional[int]]] = [
            [f.byte_at(off + i) for i in range(self.width)] for f in self.files
        ]
        return Row(offset=off, cells=cells, markers=self._markers(cells))

    def _markers(self, cells: List[List[Optional[int]]]) -> List[bool]:
        markers: List[bool] = []
        for i in range(self.width):
            column = [c[i] for c in cells]
            if self.ref is not None:
                ref_byte = cells[self.ref][i]
                # Missing reference byte => everything is "different".
                # Otherwise any file that is missing or unequal differs.
                differ = ref_byte is None or any(b != ref_byte for b in column)
            else:
                first = column[0]
                # Missing first byte => different; otherwise any mismatch
                # (a None never equals an int, so missing is caught here).
                differ = first is None or any(b != first for b in column)
            markers.append(differ)
        return markers


# --------------------------------------------------------------------------- #
# Cell formatting
# --------------------------------------------------------------------------- #
def format_byte(byte: Optional[int]) -> str:
    """Two-char hex, or ``--`` for a missing byte."""
    return "--" if byte is None else f"{byte:02x}"


def format_ascii_char(byte: Optional[int]) -> str:
    """One printable char for the ASCII gutter."""
    if byte is None:
        return " "
    if 0x20 <= byte <= 0x7E:
        return chr(byte)
    return "."


def format_ascii(row_bytes: Sequence[Optional[int]]) -> str:
    return "".join(format_ascii_char(b) for b in row_bytes)


def name_column_width(files: Sequence[HexFile], mode: str = "basename") -> int:
    return max(len(f.display_name(mode)) for f in files)


def marker_prefix_width(name_width: int) -> int:
    """Left padding so the marker row aligns under the hex columns.

    Layout per file line: 2 (indent) + name_width + 2 (gap) + hex...
    """
    return 2 + name_width + 2


def render_row_text(
    row: Row,
    files: Sequence[HexFile],
    *,
    name_mode: str = "basename",
    ascii_on: bool = True,
    show_markers: bool = True,
    name_width: Optional[int] = None,
) -> List[str]:
    """Render a row as a list of plain-text lines.

    This is the shared, un-styled layout used by the batch frontend and as
    the geometry reference for the TUI's styled rendering.
    """
    if name_width is None:
        name_width = name_column_width(files, name_mode)
    lines: List[str] = [f"0x{row.offset:08x}"]
    for f, row_bytes in zip(files, row.cells):
        name = f.display_name(name_mode).ljust(name_width)
        hexpart = " ".join(format_byte(b) for b in row_bytes)
        line = f"  {name}  {hexpart}"
        if ascii_on:
            line += f"  |{format_ascii(row_bytes)}|"
        lines.append(line)
    if show_markers:
        prefix = " " * marker_prefix_width(name_width)
        marks = " ".join("!=" if d else "==" for d in row.markers)
        lines.append(prefix + marks)
    return lines
