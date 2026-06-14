# Example layout overlays

These `*.overlay.json` files are small, **partial, educational** examples of the
`bintools.layout-overlay` v1 schema (see [`docs/layout-overlay-v1.md`](../../docs/layout-overlay-v1.md)).
They exist to demonstrate how multihex layout annotations are written and to give
the integration tests something real to validate.

They are **not** complete or formal format parsers. Each one annotates only the
first handful of header fields of its format and deliberately stops there. Do not
treat them as authoritative descriptions of gzip, tar, ELF, etc.

Because they are partial and not tied to any specific binary, they are validated
**structurally only** (no `--binary`), which must succeed:

```sh
python3 -m multihex.layout_overlay_v1 examples/layouts/gzip-header.overlay.json
```

`scripts/integration/run_examples.sh` runs this check over every file here.

## Contents

- `gzip-header.overlay.json` — first fields of a gzip member header.
- `tar-ustar-header.overlay.json` — leading fields of a POSIX `ustar` header.

## TODO

- `elf64-header.overlay.json` — partial ELF64 file header.
- `pe-header.overlay.json` — partial PE/COFF header.

Keep additions small and partial; full format descriptions are out of scope.
