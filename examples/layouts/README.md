# Example layout overlays

These `*.overlay.json` files are **partial, educational** examples of the
`bintools.layout-overlay` v1 schema (see [`docs/layout-overlay-v1.md`](../../docs/layout-overlay-v1.md)).
They exist to demonstrate how multihex layout annotations are written and to give
the integration and unit tests something real to validate.

They are **not** complete or formal format parsers. Each one annotates the
leading header fields of its format and deliberately stops there. Do not treat
them as authoritative descriptions of ELF, PE, PNG, etc.

Because they are partial and not tied to any specific binary, they are validated
**structurally only** (no `--binary`), which must succeed:

```sh
python3 -m multihex.layout_overlay_v1 examples/layouts/gzip.overlay.json
```

`scripts/integration/run_examples.sh` runs this check over every file here, and
`tests/test_example_overlays.py` enforces the same structural-validity contract
under pytest.

## Type-mapping caveats

The v1 schema has a small, fixed scalar vocabulary, so a few examples
deliberately approximate their real fields. These are **intentional**, not bugs:

- signed integer fields are encoded with the unsigned scalar of the same width;
- odd-width or non-scalar fields (e.g. 3-byte sizes, bitfields) are annotated as
  `bytes`;
- UTF-16 text is stored as `utf8`.

The annotation still marks the correct offset, length, and meaning — only the
scalar `type` is approximated.

## Contents

### Header sketches (original partial examples)

The two oldest examples, annotating only the first handful of header fields. Kept
alongside the fuller `gzip`/`tar` overlays below.

- `gzip-header` — first fields of a gzip member header.
- `tar-ustar-header` — leading fields of a POSIX `ustar` header.

### Round-1 formats

- `elf_executable` — ELF executable file header.
- `elf_core` — ELF core-dump header.
- `pe_exe` — PE/COFF executable header.
- `png` — PNG signature and first chunk.
- `jpeg` — JPEG SOI and leading segments.
- `gif` — GIF header and logical screen descriptor.
- `gzip` — gzip member header.
- `tar` — POSIX `ustar` header.
- `qcow2` — QEMU qcow2 image header.

### Network

- `net_ethernet` — Ethernet II frame header.
- `net_ipv4` — IPv4 packet header.
- `net_ipv6` — IPv6 packet header.
- `net_tcp` — TCP segment header.
- `net_udp` — UDP datagram header.
- `net_icmp` — ICMP message header.
- `net_arp` — ARP packet.
- `net_dns` — DNS message header.
- `net_dhcp` — DHCP message header.
- `net_tls` — TLS record / handshake header.
- `net_pcap` — libpcap file header.
- `net_pcapng` — pcapng section header block.

### Disk / boot / filesystem

- `disk_mbr` — master boot record.
- `disk_gpt` — GUID partition table header.
- `disk_ext4_superblock` — ext4 superblock.
- `disk_fat32` — FAT32 boot sector / BPB.
- `disk_ntfs` — NTFS boot sector.
- `disk_vhdx` — VHDX disk image header.

### Executables / debug / kernel

- `exec_macho64` — 64-bit Mach-O header.
- `exec_macho_fat` — Mach-O universal (fat) header.
- `exec_minidump` — Windows minidump header.
- `exec_ar_deb` — `ar` archive header (Debian `.deb`).
- `exec_cpio` — cpio archive header.
- `exec_dtb` — devicetree blob (DTB/FDT) header.
- `exec_wasm` — WebAssembly module header.
- `exec_javaclass` — Java `.class` file header.
- `exec_pyc` — CPython `.pyc` header.

### Compression / media / containers

- `fmt_zip` — ZIP local file header.
- `fmt_xz` — xz stream header.
- `fmt_zstd` — Zstandard frame header.
- `fmt_lz4` — LZ4 frame header.
- `fmt_bmp` — BMP file and info header.
- `fmt_tiff` — TIFF header and first IFD.
- `fmt_wav` — WAV/RIFF header.
- `fmt_webp` — WebP/RIFF header.
- `fmt_mp4` — MP4/ISO-BMFF `ftyp` box.
- `fmt_sqlite` — SQLite database header.

### Serialization / TLV / GPU

- `data_der` — DER/ASN.1 TLV prefix.
- `data_cbor` — CBOR initial bytes.
- `data_msgpack` — MessagePack initial bytes.
- `data_bson` — BSON document header.
- `data_pgp` — OpenPGP packet header.
- `data_dwarf` — DWARF compilation-unit header.
- `data_spirv` — SPIR-V module header.

Keep additions partial; full format descriptions remain out of scope.
