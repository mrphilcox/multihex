"""multihex.core - shared core for multihex.cli and multihex.tui.

Stdlib-only. This module owns all the *meaning* of a multi-file hex
comparison so that the batch frontend and the interactive TUI frontend
behave identically. It provides:

  * file loading            -> load_files()
  * the row model           -> HexModel / Row
  * marker computation      -> HexModel._markers()
  * cell formatting         -> format_byte() / format_ascii() / render_row_text()
  * exact search            -> SearchQuery / search_files() / navigation helpers

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
from typing import Iterator, List, Optional, Sequence, Tuple, Union


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
# Byte classification (display-only; data, never style)
# --------------------------------------------------------------------------- #
# Pure value classification used by both frontends to drive optional
# byte-class highlighting. This is *display-only*: it never affects loading,
# row construction, offsets, markers, reference comparison, --only-diff, search,
# or JSON. The core exposes the classification only -- it emits no ANSI and no
# Rich/Textual style objects; styling belongs to the frontend renderers.
class ByteClass(enum.Enum):
    """Coarse value class of one byte (or a missing byte)."""

    MISSING = "missing"                  # past a file's end (renders as "--")
    ZERO = "zero"                        # 0x00
    WHITESPACE = "whitespace"            # tab/newline/vtab/ff/cr/space
    PRINTABLE_ASCII = "printable_ascii"  # 0x21..0x7e (space is WHITESPACE)
    OTHER = "other"                      # everything else


# ASCII whitespace per spec: tab, LF, vertical tab, form feed, CR, and space.
# Space (0x20) is intentionally WHITESPACE here, not PRINTABLE_ASCII.
_WHITESPACE_BYTES = frozenset({0x09, 0x0A, 0x0B, 0x0C, 0x0D, 0x20})


def classify_byte(value: Optional[int]) -> ByteClass:
    """Classify a byte value (or ``None`` for missing) into a :class:`ByteClass`.

    Printable ASCII intentionally spans ``0x21..0x7e``; ``0x20`` (space) is
    WHITESPACE, and ``0x7f``/``0x80``/``0xff`` are OTHER.
    """
    if value is None:
        return ByteClass.MISSING
    if value == 0x00:
        return ByteClass.ZERO
    if value in _WHITESPACE_BYTES:
        return ByteClass.WHITESPACE
    if 0x21 <= value <= 0x7E:
        return ByteClass.PRINTABLE_ASCII
    return ByteClass.OTHER


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

    def locate(self, offset: int) -> Optional[Tuple[int, int]]:
        """Map an absolute ``offset`` to its ``(row_index, column)`` in the grid.

        Uses the same fixed grid the renderer does: row ``i`` starts at
        ``start_offset + i * width``. Returns ``None`` for offsets before the
        grid start. The row index is unbounded (it may point past a bounded
        window's last visible row); callers that only want visible rows can
        clamp with :meth:`index_for_offset`.
        """
        if offset < self.start_offset:
            return None
        rel = offset - self.start_offset
        return rel // self.width, rel % self.width

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


# --------------------------------------------------------------------------- #
# Exact search
# --------------------------------------------------------------------------- #
# Search is *exact*: it reports observed byte matches only. It never infers
# structure, alignment, or format, and it has no wildcards. The same semantics
# back both frontends; only UI glue lives in multihex.cli / multihex.tui.


class SearchError(ValueError):
    """A search query could not be built (bad hex, empty pattern, ...).

    Carries a human-readable message suitable for showing directly to the user
    (CLI exit message / TUI status line).
    """


# ASCII-only case fold (A-Z -> a-z). Bytes outside A-Z are left untouched, so
# case-insensitive matching is reliable for ASCII letters only; non-ASCII case
# folding is intentionally *not* attempted by this byte-oriented scheme.
_ASCII_FOLD = bytes.maketrans(
    bytes(range(0x41, 0x5B)), bytes(range(0x61, 0x7B))
)

_HEX_DIGITS = frozenset("0123456789abcdefABCDEF")


@dataclass(frozen=True)
class SearchQuery:
    """A fully-parsed, frontend-independent search request.

    ``needle`` is the exact byte sequence to look for. ``case_sensitive`` only
    has meaning for text mode (hex is always exact). ``file_index`` selects a
    single file, or None to search every file.
    """

    mode: str            # "text" | "hex"
    pattern: str         # original user string (for echoing in status output)
    needle: bytes        # exact bytes to search for
    case_sensitive: bool = True
    file_index: Optional[int] = None


@dataclass(frozen=True)
class SearchMatch:
    """One exact occurrence of a query's needle in one file.

    ``row_index`` / ``column`` locate the match's *first* byte in a model grid
    and are filled only when :func:`search_files` is given a ``model``.
    """

    file_index: int
    path: str
    offset: int
    length: int
    matched: bytes
    row_index: Optional[int] = None
    column: Optional[int] = None


def parse_hex_pattern(text: str) -> bytes:
    """Parse a flexible hex byte pattern into raw bytes.

    Accepts whitespace, ``:``, ``-`` and ``,`` separators and optional ``0x``
    prefixes per token, e.g. all of these yield ``b"\\xde\\xad\\xbe\\xef"``::

        "DE AD BE EF"  "deadbeef"  "0xDE 0xAD 0xBE 0xEF"
        "DE:AD:BE:EF"  "de-ad-be-ef"  "DE,AD,BE,EF"

    Raises :class:`SearchError` (with a useful message) on empty input, an odd
    number of hex digits, non-hex characters, or a bare ``0x`` token. There is
    no wildcard support.
    """
    s = (text or "").strip()
    if not s:
        raise SearchError("empty hex query")
    # Normalise every accepted separator to a space, then tokenise.
    for sep in ":-,":
        s = s.replace(sep, " ")
    digits: List[str] = []
    for token in s.split():
        body = token
        if body[:2] in ("0x", "0X"):
            body = body[2:]
            if not body:
                raise SearchError(f'invalid hex token "{token}" (0x with no digits)')
        for ch in body:
            if ch not in _HEX_DIGITS:
                raise SearchError(f'invalid hex byte "{token}"')
        digits.append(body)
    joined = "".join(digits)
    if not joined:
        raise SearchError("empty hex query")
    if len(joined) % 2 != 0:
        raise SearchError(f"odd number of hex digits in {text!r} (need whole bytes)")
    return bytes.fromhex(joined)


def make_text_query(
    pattern: str,
    *,
    case_sensitive: bool = True,
    file_index: Optional[int] = None,
) -> SearchQuery:
    """Build a UTF-8 text query. Empty pattern -> :class:`SearchError`."""
    if pattern == "":
        raise SearchError("empty search text")
    return SearchQuery(
        mode="text",
        pattern=pattern,
        needle=pattern.encode("utf-8"),
        case_sensitive=case_sensitive,
        file_index=file_index,
    )


def make_hex_query(
    pattern: str,
    *,
    file_index: Optional[int] = None,
) -> SearchQuery:
    """Build a hex query (always case-sensitive). Invalid -> :class:`SearchError`."""
    return SearchQuery(
        mode="hex",
        pattern=pattern,
        needle=parse_hex_pattern(pattern),
        case_sensitive=True,
        file_index=file_index,
    )


def _find_in_file(
    f: HexFile, query: SearchQuery, overlap: bool
) -> Iterator[Tuple[int, bytes]]:
    """Yield ``(offset, matched_bytes)`` for every match of ``query`` in ``f``.

    Matches are produced in ascending-offset order. ``matched_bytes`` is always
    read from the original file data (not the case-folded copy).
    """
    needle = query.needle
    n = len(needle)
    if n == 0:
        return
    if query.mode == "text" and not query.case_sensitive:
        # mmap has no .translate, so fold a full bytes copy of the file. This
        # copies the whole file for case-insensitive search (documented cost).
        haystack: Union[bytes, mmap.mmap] = bytes(f.data).translate(_ASCII_FOLD)
        needle = needle.translate(_ASCII_FOLD)
    else:
        # Case-sensitive / hex: search the backing buffer directly. Both
        # mmap.mmap and bytes support .find(sub, start) with no copy.
        haystack = f.data
    step = 1 if overlap else n
    start = 0
    while True:
        idx = haystack.find(needle, start)
        if idx < 0:
            return
        yield idx, bytes(f.data[idx:idx + n])
        start = idx + step


def search_files(
    files: Sequence[HexFile],
    query: SearchQuery,
    *,
    max_results: Optional[int] = None,
    overlap: bool = False,
    model: Optional[HexModel] = None,
) -> List[SearchMatch]:
    """Search ``files`` for ``query.needle`` and return ordered matches.

    Results are ordered deterministically by ``(file_index, offset)``. Matches
    are non-overlapping by default; pass ``overlap=True`` to also report
    overlapping occurrences (e.g. ``AA AA`` at offsets 0 and 1 in ``AA AA AA``).
    ``max_results`` caps the total number returned. When ``model`` is given,
    each match's ``row_index``/``column`` is filled via :meth:`HexModel.locate`.

    Iteration order already yields matches sorted by ``(file_index, offset)``,
    so an early ``max_results`` cut keeps the deterministic prefix.
    """
    if query.file_index is not None:
        if not (0 <= query.file_index < len(files)):
            raise SearchError(
                f"file index {query.file_index} out of range 0..{len(files) - 1}"
            )
        indices: Sequence[int] = (query.file_index,)
    else:
        indices = range(len(files))

    matches: List[SearchMatch] = []
    for fi in indices:
        f = files[fi]
        for offset, matched in _find_in_file(f, query, overlap):
            row_index = column = None
            if model is not None:
                located = model.locate(offset)
                if located is not None:
                    row_index, column = located
            matches.append(
                SearchMatch(
                    file_index=fi,
                    path=f.path,
                    offset=offset,
                    length=len(matched),
                    matched=matched,
                    row_index=row_index,
                    column=column,
                )
            )
            if max_results is not None and len(matches) >= max_results:
                return matches
    return matches


# --------------------------------------------------------------------------- #
# Search navigation (index-based; deterministic; optional wraparound)
# --------------------------------------------------------------------------- #
# These operate on a result list already ordered by (file_index, offset) as
# returned by search_files(). They return an *index* into that list (or None),
# which is exactly what a frontend tracking a "current match" needs.


def _match_key(m: SearchMatch) -> Tuple[int, int]:
    return (m.file_index, m.offset)


def first_match_index(matches: Sequence[SearchMatch]) -> Optional[int]:
    """Index of the first match, or None if there are none."""
    return 0 if matches else None


def next_match_index(
    matches: Sequence[SearchMatch], current: int, *, wrap: bool = True
) -> Optional[int]:
    """Index after ``current``; wraps to 0 past the end when ``wrap``."""
    n = len(matches)
    if n == 0:
        return None
    if current + 1 < n:
        return current + 1
    return 0 if wrap else None


def prev_match_index(
    matches: Sequence[SearchMatch], current: int, *, wrap: bool = True
) -> Optional[int]:
    """Index before ``current``; wraps to the last match when ``wrap``."""
    n = len(matches)
    if n == 0:
        return None
    if current - 1 >= 0:
        return current - 1
    return n - 1 if wrap else None


def match_index_after(
    matches: Sequence[SearchMatch],
    file_index: int,
    offset: int,
    *,
    inclusive: bool = True,
    wrap: bool = True,
) -> Optional[int]:
    """First match at/after ``(file_index, offset)`` in result order.

    With ``inclusive`` a match exactly at the key counts. When nothing is at or
    after the key and ``wrap`` is set, returns the first match (index 0).
    """
    if not matches:
        return None
    key = (file_index, offset)
    for i, m in enumerate(matches):
        mk = _match_key(m)
        if (mk >= key) if inclusive else (mk > key):
            return i
    return 0 if wrap else None


def match_index_before(
    matches: Sequence[SearchMatch],
    file_index: int,
    offset: int,
    *,
    inclusive: bool = True,
    wrap: bool = True,
) -> Optional[int]:
    """Last match at/before ``(file_index, offset)`` in result order.

    With ``inclusive`` a match exactly at the key counts. When nothing is at or
    before the key and ``wrap`` is set, returns the last match.
    """
    if not matches:
        return None
    key = (file_index, offset)
    for i in range(len(matches) - 1, -1, -1):
        mk = _match_key(matches[i])
        if (mk <= key) if inclusive else (mk < key):
            return i
    return len(matches) - 1 if wrap else None
