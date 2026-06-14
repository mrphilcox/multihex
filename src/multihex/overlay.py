"""multihex.overlay - load and consume bintools.layout-overlay v1 files.

A layout overlay is a *resolved list of byte ranges* for one concrete binary --
a read-only annotation/highlight layer, not a reusable file-format grammar.
multihex is a **consumer**: it loads an overlay JSON, validates it with the
``multihex.layout_overlay_v1`` validator (the single source of truth for
severities and the ``ok``-means-loadable contract), surfaces the validator's
diagnostics, and highlights the overlay's ranges in the hex view. It never
authors, infers, or edits overlays.

:class:`OverlayState` is the single seam the CLI / TUI / GUI use. The frontends
never touch raw JSON dicts: they ask the state object whether an overlay is
loaded/applicable, which ranges cover an offset, the full diagnostics, a summary
string, and the read-only "view current overlay" details. Highlighting applies
only when the overlay is *applicable* (no ``error``-severity diagnostic anywhere).

Stdlib only (the validator is stdlib only too).
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any, List, Optional, Sequence, Tuple

from multihex.layout_overlay_v1 import (
    SCHEMA_NAME,
    SCHEMA_VERSION,
    STATUS_VALUES,
    Diagnostic,
    Result,
    validate_file_aware,
    validate_structural,
)


def _is_int(v: Any) -> bool:
    # bool is a subclass of int in Python; reject it explicitly.
    return isinstance(v, int) and not isinstance(v, bool)


def _file_label(f: Any) -> str:
    """Short label for a file in diagnostics (basename, falling back to repr)."""
    path = getattr(f, "path", None)
    if isinstance(path, str) and path:
        return os.path.basename(path)
    return "<binary>"


@dataclass(frozen=True)
class OverlayRange:
    """One resolved byte range from an overlay's ``ranges`` array.

    ``index`` is the original position in the array; it is part of the
    deterministic ordering used when several ranges cover the same offset.
    """

    offset: int
    length: int
    label: Optional[str] = None
    path: Optional[str] = None
    kind: Optional[str] = None
    type: Optional[str] = None
    decoded: Any = None
    status: str = "unchecked"
    index: int = 0

    @property
    def end(self) -> int:
        return self.offset + self.length

    def covers(self, offset: int) -> bool:
        """True if ``offset`` falls inside the range.

        A zero-length range covers no byte (``offset <= N < offset`` is always
        false), so it never highlights anything.
        """
        return self.offset <= offset < self.end

    def _sort_key(self) -> Tuple[int, int, str, int]:
        return (self.offset, self.length, self.path or "", self.index)


class OverlayState:
    """Loaded-and-validated layout overlay, or a failed-to-load placeholder.

    Construct with :meth:`load`. The frontends keep ``None`` for "no overlay"
    and an :class:`OverlayState` once one has been loaded (even when it is not
    applicable, so its diagnostics stay viewable). Highlighting is gated on
    :attr:`applicable`.
    """

    def __init__(
        self,
        *,
        path: str,
        doc: Optional[Any] = None,
        load_error: Optional[str] = None,
        structural: Optional[Result] = None,
        file_results: Optional[List[Tuple[str, Result]]] = None,
        ranges: Optional[List[OverlayRange]] = None,
    ) -> None:
        self.path = path
        self.doc = doc
        self.load_error = load_error
        self.structural = structural if structural is not None else Result()
        # (file label, file-aware Result) per loaded binary, in argv order.
        self.file_results: List[Tuple[str, Result]] = list(file_results or [])
        self.ranges: List[OverlayRange] = list(ranges or [])

        self.name: Optional[str] = None
        self.source_file: Optional[str] = None
        self.source_size: Optional[int] = None
        self.source_sha256: Optional[str] = None
        if isinstance(doc, dict):
            name = doc.get("name")
            self.name = name if isinstance(name, str) else None
            sf = doc.get("source_file")
            self.source_file = sf if isinstance(sf, str) else None
            ss = doc.get("source_size")
            self.source_size = ss if _is_int(ss) else None
            sh = doc.get("source_sha256")
            self.source_sha256 = sh if isinstance(sh, str) else None

    # -- construction ------------------------------------------------------- #
    @classmethod
    def load(cls, path: str, files: Sequence[Any] = ()) -> "OverlayState":
        """Read ``path``, validate it structurally and against each binary.

        A read/parse failure yields a non-loaded state carrying the error (so the
        caller can report it) rather than raising. File-aware validation runs
        only when the schema block already identifies this as our format, so a
        wrong-format file reports its structural error without spurious
        file-relative noise (mirroring ``layout_overlay_v1.validate``).
        """
        try:
            with open(path, "r", encoding="utf-8") as fh:
                doc = json.load(fh)
        except (OSError, json.JSONDecodeError) as exc:
            return cls(path=path, load_error=str(exc))

        structural = validate_structural(doc)
        file_results: List[Tuple[str, Result]] = []
        schema_ok = (
            isinstance(doc, dict)
            and isinstance(doc.get("schema"), dict)
            and doc["schema"].get("name") == SCHEMA_NAME
        )
        if schema_ok:
            for f in files:
                # Pass the backing buffer directly (mmap or bytes); the validator
                # only needs a bytes-like object and avoids copying large files.
                file_results.append((_file_label(f), validate_file_aware(doc, f.data)))

        return cls(
            path=path,
            doc=doc,
            structural=structural,
            file_results=file_results,
            ranges=cls._parse_ranges(doc),
        )

    @staticmethod
    def _parse_ranges(doc: Any) -> List[OverlayRange]:
        """Parse well-formed ranges (valid int offset/length) into OverlayRange.

        Malformed ranges are skipped here; the validator has already flagged them
        as errors, so the overlay will be non-applicable and nothing highlights.
        Keeping only well-formed ranges means range lookup can never crash on a
        bad offset/length.
        """
        out: List[OverlayRange] = []
        ranges = doc.get("ranges") if isinstance(doc, dict) else None
        if not isinstance(ranges, list):
            return out
        for i, rng in enumerate(ranges):
            if not isinstance(rng, dict):
                continue
            offset = rng.get("offset")
            length = rng.get("length")
            if not (_is_int(offset) and _is_int(length) and offset >= 0 and length >= 0):
                continue
            status = rng.get("status")
            out.append(
                OverlayRange(
                    offset=offset,
                    length=length,
                    label=rng.get("label") if isinstance(rng.get("label"), str) else None,
                    path=rng.get("path") if isinstance(rng.get("path"), str) else None,
                    kind=rng.get("kind") if isinstance(rng.get("kind"), str) else None,
                    type=rng.get("type") if isinstance(rng.get("type"), str) else None,
                    decoded=rng.get("decoded"),
                    status=status if status in STATUS_VALUES else "unchecked",
                    index=i,
                )
            )
        return out

    # -- state queries ------------------------------------------------------ #
    @property
    def loaded(self) -> bool:
        """True when the JSON was read and parsed (regardless of validation)."""
        return self.load_error is None and self.doc is not None

    @property
    def _all_results(self) -> List[Result]:
        return [self.structural, *(r for _, r in self.file_results)]

    def error_count(self) -> int:
        return sum(len(r.errors) for r in self._all_results)

    def warning_count(self) -> int:
        return sum(len(r.warnings) for r in self._all_results)

    @property
    def applicable(self) -> bool:
        """True when the overlay loaded and has no ``error``-severity diagnostic.

        This is the validator's ``ok`` contract aggregated across the structural
        check and every per-file check. Highlighting happens only when applicable.
        """
        return self.loaded and self.error_count() == 0

    @property
    def range_count(self) -> int:
        return len(self.ranges)

    # -- range lookup ------------------------------------------------------- #
    def ranges_at(self, offset: int) -> List[OverlayRange]:
        """Every range covering ``offset``, in deterministic order.

        Returns ``[]`` when the overlay is not applicable. Order is
        ``(offset, length, path, original index)`` so overlapping ranges at one
        offset always come back the same way. Out-of-bounds and zero-length
        ranges are handled by :meth:`OverlayRange.covers` and never crash.
        """
        if not self.applicable:
            return []
        hits = [r for r in self.ranges if r.covers(offset)]
        hits.sort(key=lambda r: r._sort_key())
        return hits

    def covers(self, offset: int) -> bool:
        """Cheap "is this offset highlighted?" check for the renderers."""
        if not self.applicable:
            return False
        return any(r.covers(offset) for r in self.ranges)

    # -- diagnostics / display --------------------------------------------- #
    def all_diagnostics(self) -> List[Diagnostic]:
        """Flat list of every diagnostic (structural first, then per file)."""
        out: List[Diagnostic] = list(self.structural.diagnostics)
        for _, res in self.file_results:
            out.extend(res.diagnostics)
        return out

    def diagnostic_lines(self) -> List[str]:
        """One labelled line per diagnostic, for stderr / dialogs / panels."""
        lines: List[str] = []
        for d in self.structural.diagnostics:
            loc = f" [{d.path}]" if d.path else ""
            lines.append(f"[structural] {d.severity}: {d.code}{loc}: {d.message}")
        for label, res in self.file_results:
            for d in res.diagnostics:
                loc = f" [{d.path}]" if d.path else ""
                lines.append(f"[{label}] {d.severity}: {d.code}{loc}: {d.message}")
        return lines

    def summary(self) -> str:
        """One-line status, e.g. ``Loaded layout overlay 'gzip' - 6 ranges, 1 warning``."""
        if not self.loaded:
            return f"Could not load layout overlay {self.path}: {self.load_error}"
        name = f" {self.name!r}" if self.name else ""
        ec = self.error_count()
        wc = self.warning_count()
        if not self.applicable:
            return (
                f"Layout overlay{name} not applied - "
                f"{ec} {_plural(ec, 'error')} (see details)"
            )
        detail = f"{self.range_count} {_plural(self.range_count, 'range')}"
        if wc:
            detail += f", {wc} {_plural(wc, 'warning')}"
        return f"Loaded layout overlay{name} - {detail}"

    def details_text(self, cursor_offset: Optional[int] = None) -> str:
        """Multi-line, read-only "view current overlay" report.

        Shows the overlay path, schema, name, source_* fields, range count,
        applied/not-applied status, all diagnostics, the full range list, and --
        when ``cursor_offset`` is given -- the ranges covering that offset.
        """
        if not self.loaded:
            return f"Layout overlay\n  path: {self.path}\n  error: {self.load_error}"

        lines: List[str] = [
            "Layout overlay",
            f"  path: {self.path}",
            f"  schema: {SCHEMA_NAME} v{SCHEMA_VERSION}",
        ]
        if self.name:
            lines.append(f"  name: {self.name}")
        if self.source_file is not None:
            lines.append(f"  source_file: {self.source_file}")
        if self.source_size is not None:
            lines.append(f"  source_size: {self.source_size}")
        if self.source_sha256 is not None:
            lines.append(f"  source_sha256: {self.source_sha256}")
        lines.append(f"  ranges: {self.range_count}")
        lines.append(
            "  status: applied"
            if self.applicable
            else "  status: NOT applied (errors present)"
        )
        lines.append(
            f"  diagnostics: {self.error_count()} "
            f"{_plural(self.error_count(), 'error')}, "
            f"{self.warning_count()} {_plural(self.warning_count(), 'warning')}"
        )

        diag_lines = self.diagnostic_lines()
        if diag_lines:
            lines.append("")
            lines.append("Diagnostics:")
            lines.extend(f"  {line}" for line in diag_lines)

        if self.ranges:
            lines.append("")
            lines.append("Ranges:")
            lines.extend(f"  {self._range_line(r)}" for r in self.ranges)

        if cursor_offset is not None:
            here = self.ranges_at(cursor_offset)
            lines.append("")
            lines.append(f"Ranges under cursor (0x{cursor_offset:08x}):")
            if here:
                lines.extend(f"  {self._range_line(r)}" for r in here)
            else:
                lines.append("  (none)")

        return "\n".join(lines)

    @staticmethod
    def _range_line(r: OverlayRange) -> str:
        name = r.path or r.label or "(range)"
        parts = [f"0x{r.offset:08x}+{r.length}", name]
        if r.type:
            parts.append(f"type={r.type}")
        if r.decoded is not None:
            parts.append(f"decoded={r.decoded!r}")
        parts.append(f"status={r.status}")
        return "  ".join(parts)


def _plural(n: int, word: str) -> str:
    return word if n == 1 else word + "s"
