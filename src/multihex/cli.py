"""multihex.cli - side-by-side fixed-offset hex inspection of multiple binary files.

Display the same offset range across several binary files so you can compare the
byte values that live at identical offsets. This is an exact display tool, not an
inference tool: it shows what bytes are present, not what they mean.

It can also search the loaded files for an exact byte sequence (text or hex) and
report where it occurs; search is exact and reports observed matches only.

Examples:
    multihex file1.bin file2.bin file3.bin
    multihex --offset 0x40 --length 0x80 *.bin
    multihex --width 16 --ascii *.bin
    multihex --search-text RIFF file1.bin file2.bin
    multihex --search-hex "52 49 46 46" --search-context 2 file1.bin
"""

import argparse
import json
import os
import sys

from multihex.core import (
    ByteClass,
    HexModel,
    Marker,
    SearchError,
    SearchMatch,
    classify_byte,
    format_ascii_char,
    format_byte,
    format_marker,
    load_files,
    make_hex_query,
    make_text_query,
    marker_prefix_width,
    parse_int,
    render_row_text,
    search_files,
)
from multihex.overlay import OverlayState

RED = "\033[31m"
GREEN = "\033[32m"
CYAN = "\033[36m"
DIM = "\033[2m"
# Layout-overlay highlight: a background so it reads as an annotation layer and
# stays distinct from the foreground diff/byte-class colors. Lowest priority
# after missing and diff (see _render_file_segment).
OVERLAY = "\033[44m"
RESET = "\033[0m"

# Byte-class -> ANSI foreground for --byte-classes (display-only). OTHER and
# MISSING get no byte-class color: OTHER stays normal, and missing cells keep
# their existing dim styling. Diffs always take priority over these (see
# render_text_row), so differences never become harder to see.
_BYTE_CLASS_COLOR = {
    ByteClass.ZERO: DIM,
    ByteClass.WHITESPACE: CYAN,
    ByteClass.PRINTABLE_ASCII: GREEN,
}


def _silence_stdout_after_broken_pipe():
    """Prevent Python from reporting a second broken pipe during shutdown."""
    try:
        sys.stdout.close()
    except BrokenPipeError:
        pass
    sys.stdout = open(os.devnull, "w")


def write_stdout(text):
    """Write CLI stdout and treat closed downstream pipes as normal termination."""
    try:
        sys.stdout.write(text)
        sys.stdout.write("\n")
        sys.stdout.flush()
    except BrokenPipeError:
        _silence_stdout_after_broken_pipe()
        raise SystemExit(0)


def parse_around(text):
    """Parse OFF:N for --around."""
    if ":" not in text:
        raise argparse.ArgumentTypeError("--around expects OFF:N (e.g. 0x40:32)")
    off_s, n_s = text.split(":", 1)
    try:
        return (int(off_s, 0), int(n_s, 0))
    except ValueError as exc:
        raise argparse.ArgumentTypeError(str(exc))


def build_parser():
    p = argparse.ArgumentParser(
        prog="multihex",
        description="Compare byte values across multiple binary files at fixed offsets.",
    )
    p.add_argument("files", nargs="+", help="one or more binary files")
    p.add_argument("--offset", type=parse_int, default=0,
                   help="start offset (default 0). Accepts 0x40, 64, 0b1000000.")
    p.add_argument("--length", type=parse_int, default=None,
                   help="bytes to display (default: shortest remaining length common to all files)")
    p.add_argument("--width", type=parse_int, default=16,
                   help="bytes per row (default 16)")
    p.add_argument("--ascii", dest="ascii", action="store_true", default=True,
                   help="show ASCII gutter (default on)")
    p.add_argument("--no-ascii", dest="ascii", action="store_false",
                   help="suppress ASCII gutter")
    p.add_argument("--names", choices=["basename", "path"], default="basename",
                   help="label files by basename (default) or full path")
    p.add_argument("--limit-rows", type=parse_int, default=None, metavar="N",
                   help="stop after N rows")
    p.add_argument("--color", choices=["auto", "always", "never"], default="auto",
                   help="colorize output (default auto = when stdout is a tty)")
    p.add_argument("--ref", type=parse_int, default=None, metavar="INDEX",
                   help="use this 0-based file index as the comparison reference. "
                        "Markers: == all files match the reference byte, "
                        "!= at least one file differs, -- one or more bytes missing. "
                        "Also highlights cells that differ from the reference in color.")
    p.add_argument("--only-diff", action="store_true",
                   help="show only rows containing at least one differing or missing byte")
    p.add_argument("--byte-classes", dest="byte_classes", action="store_true",
                   help="highlight byte classes in the hex cells (zero, ASCII "
                        "whitespace, printable ASCII). Visual-only; needs color "
                        "enabled and has no effect on --json. Default off.")
    p.add_argument("--layout", choices=["stacked", "side-by-side"], default="stacked",
                   help="human-readable layout: stacked (default, one file per "
                        "line) or side-by-side (files laid out horizontally). "
                        "Visual-only; no effect on --json.")
    p.add_argument("--markers", choices=["single", "repeat", "none"], default="single",
                   help="marker text display: single (default, one marker strip "
                        "per row), repeat (repeat the strip under each file "
                        "segment in side-by-side layout; same as single when "
                        "stacked), or none (hide marker text). Display-only; does "
                        "not affect comparison, --only-diff, search, or --json.")
    p.add_argument("--around", type=parse_around, default=None, metavar="OFF:N",
                   help="show a window of N bytes centered on OFF (overrides --offset/--length)")
    p.add_argument("--overlay", metavar="PATH", default=None,
                   help="load a bintools.layout-overlay v1 JSON file (a read-only "
                        "annotation layer) and highlight its byte ranges. The "
                        "overlay is validated; diagnostics print to stderr and an "
                        "overlay with errors is not applied. Visual-only; needs "
                        "color enabled and has no effect on --json.")
    p.add_argument("--json", dest="as_json", action="store_true",
                   help="emit machine-readable JSON rows")

    # -- search (exact byte/text match; reports observed matches only) ------- #
    search = p.add_argument_group("search")
    mode = search.add_mutually_exclusive_group()
    mode.add_argument("--search-text", metavar="TEXT", default=None,
                      help="search for literal UTF-8 text (e.g. RIFF, Content-Type)")
    mode.add_argument("--search-hex", metavar="HEX", default=None,
                      help="search for a hex byte pattern (e.g. 'DE AD BE EF', deadbeef)")
    search.add_argument("--search-ignore-case", action="store_true",
                        help="case-insensitive text search (ASCII letters only)")
    search.add_argument("--search-file", metavar="INDEX_OR_NAME", default=None,
                        help="restrict the search to one file (0-based index or a name)")
    search.add_argument("--search-context", type=parse_int, default=None, metavar="N",
                        help="render N comparison rows of context around each match")
    search.add_argument("--search-max-results", type=parse_int, default=None, metavar="N",
                        help="stop after N matches")
    search.add_argument("--search-overlap", action="store_true",
                        help="also report overlapping matches (default: non-overlapping)")
    return p


def resolve_color(mode, as_json):
    if as_json:
        return False
    if mode == "always":
        return True
    if mode == "never":
        return False
    return sys.stdout.isatty() and os.environ.get("NO_COLOR") is None


def _render_file_segment(row, fi, name, name_w, base_row, show_ascii, use_color,
                         byte_classes, overlay=None):
    """Build one file's colored segment (the part after the leading indent).

    A segment is ``name + "  " + hex cells + optional "  |gutter|"`` -- the same
    body used on a stacked per-file line and as one horizontal cell of a
    side-by-side row. Coloring is the batch tool's own scheme: each present cell
    is reddened when it differs from the base/reference byte in that column;
    missing cells are dimmed; non-diff cells inside a layout-overlay range get an
    overlay background, otherwise an optional byte-class color. Priority:
    missing > diff > overlay > byte-class.
    """
    hex_cells = []
    gutter = []
    for c, b in enumerate(row.cells[fi]):
        if b is None:
            cell = format_byte(b)  # "--"
            if use_color:
                cell = DIM + cell + RESET
            hex_cells.append(cell)
        else:
            txt = format_byte(b)
            ref_b = base_row[c] if base_row is not None else None
            if use_color and ref_b is not None and b != ref_b:
                txt = RED + txt + RESET
            elif use_color and overlay is not None and overlay.covers(row.offset + c):
                txt = OVERLAY + txt + RESET
            elif use_color and byte_classes:
                color = _BYTE_CLASS_COLOR.get(classify_byte(b))
                if color:
                    txt = color + txt + RESET
            hex_cells.append(txt)
        # missing -> space, printable -> char, else '.' (all via core helper)
        gutter.append(format_ascii_char(b))
    segment = name.ljust(name_w) + "  " + " ".join(hex_cells)
    if show_ascii:
        segment += "  |" + "".join(gutter) + "|"
    return segment


def render_text_row(lines, row, names, name_w, base, show_ascii, use_color,
                    byte_classes=False, layout="stacked", markers="single",
                    overlay=None):
    """Render one core Row as text lines (with ANSI color when enabled).

    Coloring here is the batch tool's own scheme: each present cell is
    reddened when it differs from the base/reference file's byte in that
    column; missing cells are dimmed. (The TUI colors whole columns by
    marker instead -- the two schemes intentionally differ.)

    When ``byte_classes`` is set (and color is on), present cells that are *not*
    a diff get a byte-class foreground color. Missing and diff styling always
    win, so differences stay obvious. The ASCII gutter is left uncolored, as it
    is throughout the batch tool.

    ``layout`` is display-only. ``"stacked"`` (default) puts each file on its own
    line; ``"side-by-side"`` joins the per-file segments horizontally.

    ``markers`` is display-only too and controls only the marker *text*:
    ``"single"`` (default) shows one strip per row, ``"repeat"`` repeats the
    strip under each file segment in side-by-side layout (same as ``"single"``
    when stacked), and ``"none"`` hides the marker text. It never changes marker
    computation, ``--only-diff``, search, or JSON.
    """
    lines.append(f"0x{row.offset:08x}")
    base_row = row.cells[base] if base < len(row.cells) else None
    segments = [
        _render_file_segment(row, fi, name, name_w, base_row, show_ascii,
                             use_color, byte_classes, overlay)
        for fi, name in enumerate(names)
    ]

    rendered = []
    for m in row.markers:
        tok = format_marker(m)
        if not use_color:
            rendered.append(tok)
        elif m is Marker.SAME:
            rendered.append(GREEN + tok + RESET)
        elif m is Marker.DIFF:
            rendered.append(RED + tok + RESET)
        else:
            rendered.append(DIM + tok + RESET)
    strip = " ".join(rendered)

    if layout == "side-by-side":
        if markers == "single":
            # The marker strip is its own left prefix column, not attached to
            # the first file. Width matches the hex part, so it reads as a
            # column of column-level results.
            lines.append("  " + strip + "  " + "   ".join(segments))
        else:
            lines.append("  " + "   ".join(segments))
            if markers == "repeat":
                ncols = len(row.cells[0]) if row.cells else 0
                gap = " " * (name_w + 2)
                # Pad each strip to the (uniform) visible segment width so the
                # repeated strips line up under each segment's hex columns.
                tail = " " * (ncols + 4 if show_ascii else 0)
                marker_segs = [gap + strip + tail for _ in names]
                lines.append(("  " + "   ".join(marker_segs)).rstrip())
    else:
        lines.extend("  " + segment for segment in segments)
        if markers != "none":
            # align the marker row under the hex columns
            lines.append(" " * marker_prefix_width(name_w) + strip)


def load_overlay(path, files):
    """Load + validate a layout overlay, report to stderr, return it if applicable.

    Diagnostics (and a one-line summary) always go to stderr so stdout stays
    clean. An overlay with any error-severity diagnostic is reported but not
    returned, so it is never applied as a highlight layer.
    """
    overlay = OverlayState.load(path, files)
    print(f"multihex: {overlay.summary()}", file=sys.stderr)
    for line in overlay.diagnostic_lines():
        print(f"multihex:   {line}", file=sys.stderr)
    return overlay if overlay.applicable else None


def build_json_row(row, names):
    files = []
    for fi, name in enumerate(names):
        b_list = list(row.cells[fi])
        ascii_s = "".join(format_ascii_char(b) for b in b_list)
        files.append({"name": name, "bytes": b_list, "ascii": ascii_s})
    markers = [format_marker(m) for m in row.markers]
    return {"offset": row.offset, "markers": markers, "files": files}


def _resolve_search_file(spec, files, names):
    """Resolve --search-file (0-based index or a name) to a file index."""
    try:
        idx = parse_int(spec)
    except ValueError:
        idx = None
    if idx is not None and 0 <= idx < len(files):
        return idx
    for i, f in enumerate(files):
        if spec in (names[i], f.path, os.path.basename(f.path)):
            return i
    sys.exit(f"multihex: --search-file {spec!r} did not match any file")


def _format_match_line(match: SearchMatch, names):
    """One script-friendly line describing a match (see module examples)."""
    hexbytes = " ".join(format_byte(b) for b in match.matched)
    ascii_s = "".join(format_ascii_char(b) for b in match.matched)
    return (
        f"file={match.file_index} path={names[match.file_index]} "
        f"offset=0x{match.offset:08x} len={match.length} "
        f'match={hexbytes} ascii="{ascii_s}"'
    )


def run_search(args, files, names, name_w):
    """Run search and print results (+ optional context); never returns a dump.

    Search short-circuits the normal comparison output: when a --search-* flag
    is given this is the only thing the tool prints, so the standard rendering
    (and its goldens) are unaffected when no search flag is present.
    """
    file_index = None
    if args.search_file is not None:
        file_index = _resolve_search_file(args.search_file, files, names)

    try:
        if args.search_text is not None:
            query = make_text_query(
                args.search_text,
                case_sensitive=not args.search_ignore_case,
                file_index=file_index,
            )
        else:
            query = make_hex_query(args.search_hex, file_index=file_index)
    except SearchError as exc:
        sys.exit(f"multihex: {exc}")

    if args.search_context is not None and args.search_context < 0:
        sys.exit("multihex: --search-context must be >= 0")

    # A full-file model (length=None -> derived from the largest file) so matches
    # anywhere in a file get a row/column and renderable context, independent of
    # any display --offset/--length window.
    model = HexModel(files, start_offset=0, width=args.width, length=None)

    try:
        matches = search_files(
            files,
            query,
            max_results=args.search_max_results,
            overlap=args.search_overlap,
            model=model,
        )
    except SearchError as exc:
        sys.exit(f"multihex: {exc}")

    if not matches:
        print(f"multihex: no matches for {query.pattern!r}", file=sys.stderr)
        return

    context = args.search_context
    out = []
    for mi, match in enumerate(matches):
        out.append(_format_match_line(match, names))
        if context:
            row_index = match.row_index
            if row_index is None:
                row_index = model.index_for_offset(match.offset)
            lo = max(0, row_index - context)
            hi = min(model.row_count - 1, row_index + context)
            for i in range(lo, hi + 1):
                out.extend(
                    render_row_text(
                        model.build_row(i),
                        files,
                        name_mode=args.names,
                        ascii_on=args.ascii,
                        name_width=name_w,
                        layout=args.layout,
                        markers=args.markers,
                    )
                )
            # blank line between context blocks for readability
            if mi != len(matches) - 1:
                out.append("")
    write_stdout("\n".join(out))


def main(argv=None):
    args = build_parser().parse_args(argv)

    if args.width < 1:
        sys.exit("multihex: --width must be >= 1")

    if args.around is not None:
        off, n = args.around
        args.offset = max(0, off - n // 2)
        args.length = n

    if args.offset < 0:
        sys.exit("multihex: --offset must be >= 0")

    try:
        sizes = [os.path.getsize(f) for f in args.files]
    except OSError as exc:
        sys.exit(f"multihex: {exc}")

    available = [max(0, s - args.offset) for s in sizes]
    if args.length is None:
        length = min(available) if available else 0
    else:
        length = args.length
    if length < 0:
        sys.exit("multihex: --length must be >= 0")

    try:
        files = load_files(args.files)
    except OSError as exc:
        sys.exit(f"multihex: {exc}")

    names = [os.path.basename(f) if args.names == "basename" else f for f in args.files]
    name_w = max((len(n) for n in names), default=0)

    # Search short-circuits the normal dump; existing output is untouched when
    # no --search-* flag is present.
    if args.search_text is not None or args.search_hex is not None:
        run_search(args, files, names, name_w)
        return

    if args.ref is not None and not (0 <= args.ref < len(args.files)):
        sys.exit(f"multihex: --ref {args.ref} out of range (have {len(args.files)} files)")
    base = args.ref if args.ref is not None else 0

    use_color = resolve_color(args.color, args.as_json)

    # Layout overlay is a display-only annotation layer: load + report it only
    # for the text dump (no effect on --json), and apply it only when loadable.
    overlay = None
    if args.overlay is not None and not args.as_json:
        overlay = load_overlay(args.overlay, files)

    # The core owns the offset grid, three-state markers, and the bounded
    # window (partial last row + all-missing rows past EOF). The frontend keeps
    # only its presentation concerns: --only-diff / --limit-rows filtering,
    # ANSI coloring, and JSON shaping.
    model = HexModel(
        files,
        start_offset=args.offset,
        width=args.width,
        ref=args.ref,
        length=length,
    )

    json_rows = []
    text_lines = []
    printed = 0

    for i in range(model.row_count):
        row = model.build_row(i)

        if args.only_diff and not row.has_diff:
            continue
        if args.limit_rows is not None and printed >= args.limit_rows:
            break
        printed += 1

        if args.as_json:
            json_rows.append(build_json_row(row, names))
        else:
            render_text_row(text_lines, row, names, name_w,
                            base, args.ascii, use_color, args.byte_classes,
                            args.layout, args.markers, overlay)

    if args.as_json:
        out = {
            "offset": args.offset,
            "length": length,
            "width": args.width,
            "ref": args.ref,
            "files": names,
            "paths": list(args.files),
            "rows": json_rows,
        }
        write_stdout(json.dumps(out, indent=2))
    elif not text_lines:
        print("multihex: nothing to display for this range", file=sys.stderr)
    else:
        write_stdout("\n".join(text_lines))


if __name__ == "__main__":
    main()
