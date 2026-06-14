"""multihex.core - shared core for multihex.cli and multihex.tui.

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
  * Column markers are three-state (Marker.SAME / DIFF / MISSING):
      - MISSING if any byte in the column is None (missing wins outright);
      - else SAME if every byte equals the pivot (the --ref byte, or
        column[0] when no --ref);
      - else DIFF.
  * Without --ref, the pivot is column[0] ("all files agree").
  * With --ref INDEX, the pivot is the reference file's byte.
  * Integer parsing matches multihex.cli: int(x, 0).
"""

from __future__ import annotations

import enum
import mmap
import os
from dataclasses import dataclass
from typing import List, Optional, Sequence, Union


def parse_int(text: str) -> int:
    """Parse an integer the same way multihex.cli does: ``int(x, 0)``.

    Accepts decimal, 0x.. (hex), 0o.. (octal), 0b.. (binary), with an
    optional leading sign.
    """
    return int(text, 0)


# --------------------------------------------------------------------------- #
# Column markers (three-state, single source of truth for both frontends)
# --------------------------------------------------------------------------- #
class Marker(enum.Enum):
    """State of one comparison column across all files."""

    SAME = "=="     # every byte equals the pivot
    DIFF = "!="     # all present, but at least one differs from the pivot
    MISSING = "--"  # at least one byte is missing (past a file's end)


def format_marker(marker: Marker) -> str:
    """Render a marker as its two-char text token."""
    return marker.value


# --------------------------------------------------------------------------- #
# Files
# --------------------------------------------------------------------------- #
@dataclass
class HexFile:
    """A single binary file exposed as random-access bytes.

    ``data`` is the backing buffer: either an ``mmap.mmap`` (lazy, demand-paged
    random access produced by :func:`load_files`) or a plain ``bytes`` object
    (e.g. for tests or in-memory construction). Indexing and ``len`` behave the
    same for both, so :meth:`byte_at` and :attr:`size` are backend-agnostic.
    """

    path: str
    data: Union[mmap.mmap, bytes, bytearray]

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


def _open_buffer(path: str) -> Union[mmap.mmap, bytes]:
    """Return a read-only random-access buffer for ``path``.

    Uses ``mmap`` so only touched pages are read in — a small window over a
    large file does not load the whole file. Empty files cannot be mmap'd, so
    they fall back to an empty ``bytes``. On POSIX the mapping stays valid after
    the file descriptor is closed, so no handle is retained.
    """
    with open(path, "rb") as fh:
        size = os.fstat(fh.fileno()).st_size
        if size == 0:
            return b""
        return mmap.mmap(fh.fileno(), size, access=mmap.ACCESS_READ)


def load_files(paths: Sequence[str]) -> List[HexFile]:
    """Open every path for lazy random access. Raises OSError on failure."""
    return [HexFile(path=p, data=_open_buffer(p)) for p in paths]


# --------------------------------------------------------------------------- #
# Row model
# --------------------------------------------------------------------------- #
@dataclass
class Row:
    """One block of the display: ``ncols`` columns across every file.

    ``ncols`` is normally the model width, but the final row of a bounded
    (length-limited) window may be narrower.
    """

    offset: int
    # One list per file, each of length ``ncols``; entries are byte (0..255)
    # or None for "missing" (past that file's end).
    cells: List[List[Optional[int]]]
    # One Marker per column.
    markers: List[Marker]

    @property
    def has_diff(self) -> bool:
        """True if any column is not SAME (i.e. differs or is missing)."""
        return any(m is not Marker.SAME for m in self.markers)


class HexModel:
    """Builds rows and computes markers for a fixed offset grid.

    The offset grid is fixed at construction: row ``i`` starts at
    ``start_offset + i * width``. Navigation/filtering belong to the
    frontend; the model only answers "what is in row i".

    ``length`` bounds the window independently of file sizes. When given, the
    window is ``[start_offset, start_offset + length)``: ``row_count`` is
    derived from ``length`` (not the largest file), the final row may be
    narrower than ``width``, and rows past every file's end are all-missing.
    When ``length`` is None (the TUI), the range is derived from the largest
    file and every row is full ``width``.
    """

    def __init__(
        self,
        files: List[HexFile],
        *,
        start_offset: int = 0,
        width: int = 16,
        ref: Optional[int] = None,
        length: Optional[int] = None,
    ) -> None:
        if not files:
            raise ValueError("need at least one file")
        if width <= 0:
            raise ValueError("width must be positive")
        if start_offset < 0:
            raise ValueError("offset must not be negative")
        if length is not None and length < 0:
            raise ValueError("length must not be negative")
        if ref is not None and not (0 <= ref < len(files)):
            raise ValueError(
                f"reference index {ref} out of range 0..{len(files) - 1}"
            )
        self.files = files
        self.start_offset = start_offset
        self.width = width
        self.ref = ref
        self.length = length
        self.max_size = max(f.size for f in files)
        # End of the bounded window, or None to derive from the largest file.
        self.end: Optional[int] = (
            None if length is None else start_offset + length
        )

    @property
    def row_count(self) -> int:
        if self.length is not None:
            if self.length <= 0:
                return 0
            return (self.length + self.width - 1) // self.width
        span = self.max_size - self.start_offset
        if span <= 0:
            return 0
        return (span + self.width - 1) // self.width

    def row_offset(self, index: int) -> int:
        return self.start_offset + index * self.width

    def _row_width(self, off: int) -> int:
        """Columns in the row at ``off`` (clamped to the bounded window end)."""
        if self.end is not None:
            return max(0, min(self.width, self.end - off))
        return self.width

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
        ncols = self._row_width(off)
        cells: List[List[Optional[int]]] = [
            [f.byte_at(off + i) for i in range(ncols)] for f in self.files
        ]
        return Row(offset=off, cells=cells, markers=self._markers(cells))

    def _markers(self, cells: List[List[Optional[int]]]) -> List[Marker]:
        ncols = len(cells[0]) if cells else 0
        markers: List[Marker] = []
        for i in range(ncols):
            column = [c[i] for c in cells]
            # Missing wins outright over any agreement check.
            if any(b is None for b in column):
                markers.append(Marker.MISSING)
                continue
            pivot = column[self.ref] if self.ref is not None else column[0]
            same = all(b == pivot for b in column)
            markers.append(Marker.SAME if same else Marker.DIFF)
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
        marks = " ".join(format_marker(m) for m in row.markers)
        lines.append(prefix + marks)
    return lines
