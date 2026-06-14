# Changelog

All notable changes to this project are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres
to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- **Byte-class highlighting** (`--byte-classes`): a display-only mode that tints
  hex cells by value class — zero bytes dim, ASCII whitespace cyan, printable
  ASCII green — to help spot structure. Available in both frontends (the TUI also
  toggles it live with `t`); disabled by default. It needs color enabled and has
  no effect on offsets, comparison markers, `--only-diff`, `--ref`, search, or
  `--json`. Classification lives in the core as `classify_byte()` / `ByteClass`
  (data only; frontends own the styling), and existing missing/diff/search
  styling always takes priority.
- User and developer documentation: `README.md`, `docs/ARCHITECTURE.md`,
  `docs/API.md`, `CONTRIBUTING.md`, and this changelog.

## [0.1.0]

Initial release.

### Added
- **Fixed-offset comparison core** (`multihex.core`, stdlib-only): `HexModel`
  offset grid, three-state markers (`==` / `!=` / `--`), `mmap`-backed lazy file
  loading, and shared cell formatting.
- **Batch CLI** (`multihex`): side-by-side text output with ANSI color, windowing
  (`--offset`, `--length`, `--width`, `--around`), comparison controls (`--ref`,
  `--only-diff`, `--limit-rows`), display controls (`--ascii`/`--no-ascii`,
  `--names`, `--color`), and machine-readable `--json` output.
- **Exact search** (text and hex) in the core, surfaced in the CLI via
  `--search-text` / `--search-hex` with `--search-ignore-case`, `--search-file`,
  `--search-context`, `--search-max-results`, and `--search-overlap`.
- **Interactive TUI** (`multihex-tui`): a Textual viewer with scrolling, paging,
  jump-to-offset, live reference switching, toggles, and interactive search with
  match highlighting.
- Test suite: golden characterization tests, core/CLI parity tests, and search and
  TUI tests.

[Unreleased]: https://github.com/your-org/multihex/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/your-org/multihex/releases/tag/v0.1.0
