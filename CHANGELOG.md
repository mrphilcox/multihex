# Changelog

All notable changes to this project are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres
to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- **TUI configuration** (`multihex-tui` only): persistent display preferences
  loaded from `~/.config/multihex/tui.toml` (or
  `$XDG_CONFIG_HOME/multihex/tui.toml`). Precedence is built-in defaults → config
  file → CLI args → interactive changes. New flags `--config PATH` and
  `--no-config` (mutually exclusive); a new in-app settings pane (`o`) views,
  changes, and saves settings (`s` save, `S` save-as). Saved files are complete
  snapshots with a `config_version = 1` schema version (independent of the app
  version) and `multihex_version`. Only preferences are persisted — never session
  state (reference, offset, scroll, search, file list). The **batch CLI is
  unchanged and config-free** (no `--config`, reads no config file, identical
  text/JSON output). Config logic lives in the new TUI-only `multihex.tui_config`
  module (reads via stdlib `tomllib` on 3.11+, `tomli` on 3.9–3.10; writes via a
  tiny local serializer); the package now exposes `__version__ = "0.1.0"`.
- **Side-by-side layout** (`--layout stacked|side-by-side`): a second
  human-readable display that lays each file's hex (and ASCII gutter) out
  horizontally across the offset row instead of stacking one file per line, so
  files can be compared left-to-right at the same offset. `stacked` remains the
  default. Available in both frontends; the TUI cycles layouts live with `v` and
  adds horizontal scrolling (`←`/`→`) for the wider rows. Layout is visual-only:
  it never affects offsets, bytes, comparison markers, `--ref`, `--only-diff`,
  search, or `--json`. `render_row_text()` gains a `layout` keyword so the CLI's
  search-context rows honor it.
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
