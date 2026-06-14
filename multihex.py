#!/usr/bin/env python3
"""multihex.py - side-by-side fixed-offset hex inspection of multiple binary files.

Display the same offset range across several binary files so you can compare the
byte values that live at identical offsets. This is an exact display tool, not an
inference tool: it shows what bytes are present, not what they mean.

Examples:
    multihex file1.bin file2.bin file3.bin
    multihex --offset 0x40 --length 0x80 *.bin
    multihex --width 16 --ascii *.bin
"""

import argparse
import json
import os
import sys

from multihex_core import (
    HexModel,
    Marker,
    format_ascii_char,
    format_byte,
    format_marker,
    load_files,
    marker_prefix_width,
    parse_int,
)

RED = "\033[31m"
GREEN = "\033[32m"
DIM = "\033[2m"
RESET = "\033[0m"


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
    p.add_argument("--around", type=parse_around, default=None, metavar="OFF:N",
                   help="show a window of N bytes centered on OFF (overrides --offset/--length)")
    p.add_argument("--json", dest="as_json", action="store_true",
                   help="emit machine-readable JSON rows")
    return p


def resolve_color(mode, as_json):
    if as_json:
        return False
    if mode == "always":
        return True
    if mode == "never":
        return False
    return sys.stdout.isatty() and os.environ.get("NO_COLOR") is None


def render_text_row(lines, row, names, name_w, base, show_ascii, use_color):
    """Render one core Row as text lines (with ANSI color when enabled).

    Coloring here is the batch tool's own scheme: each present cell is
    reddened when it differs from the base/reference file's byte in that
    column; missing cells are dimmed. (The TUI colors whole columns by
    marker instead -- the two schemes intentionally differ.)
    """
    lines.append(f"0x{row.offset:08x}")
    base_row = row.cells[base] if base < len(row.cells) else None
    for fi, name in enumerate(names):
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
                hex_cells.append(txt)
            # missing -> space, printable -> char, else '.' (all via core helper)
            gutter.append(format_ascii_char(b))
        line = "  " + name.ljust(name_w) + "  " + " ".join(hex_cells)
        if show_ascii:
            line += "  |" + "".join(gutter) + "|"
        lines.append(line)

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
    # align the marker row under the hex columns
    lines.append(" " * marker_prefix_width(name_w) + " ".join(rendered))


def build_json_row(row, names):
    files = []
    for fi, name in enumerate(names):
        b_list = list(row.cells[fi])
        ascii_s = "".join(format_ascii_char(b) for b in b_list)
        files.append({"name": name, "bytes": b_list, "ascii": ascii_s})
    markers = [format_marker(m) for m in row.markers]
    return {"offset": row.offset, "markers": markers, "files": files}


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

    if args.ref is not None and not (0 <= args.ref < len(args.files)):
        sys.exit(f"multihex: --ref {args.ref} out of range (have {len(args.files)} files)")
    base = args.ref if args.ref is not None else 0

    use_color = resolve_color(args.color, args.as_json)

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
                            base, args.ascii, use_color)

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
        print(json.dumps(out, indent=2))
    elif not text_lines:
        print("multihex: nothing to display for this range", file=sys.stderr)
    else:
        print("\n".join(text_lines))


if __name__ == "__main__":
    main()
