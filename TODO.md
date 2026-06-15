# TODO

Repo-wide tasks and follow-ups for `multihex` (the visualization layer). Tool /
`layoutcheck` / overlay-export work lives in the sibling `bintools` repo, not
here. Items are grouped by horizon: **Current focus → Near-term → Medium-term →
Someday → Done or superseded**. Move items down as they ship, and add new
follow-ups you discover.

## Current focus

_(nothing in flight — pick the next item from Near-term)_

## Near-term

- [ ] **Persist the TUI text-search case-insensitive preference (optional).** The
      `multihex-tui` text-search panel has a "Case-insensitive (ASCII)" checkbox
      whose state is remembered for the running session only. If desired, promote
      it to a persisted startup default: add a field to `TuiSettings`, wire it
      through `load_settings`/`_dump_toml`/the settings pane (`o`) and
      `build_startup_settings` (and likely a `--search-ignore-case` startup flag).
      Persist only the *preference* — never the search string, match index, or
      results.
- [ ] **Public release publishing.** Ensure
      `https://github.com/mrphilcox/multihex` exists, push the release branch and
      tags there, and verify the package metadata links resolve before publishing
      to PyPI.
- [ ] **Wire the visual-regression suite into CI.** CI now installs the `[gui]`
      extra and runs the GUI/TUI *behavior* tests (`tests/`) headlessly under
      `QT_QPA_PLATFORM=offscreen` (so they run, not skip). The heavier
      *visual-regression* lane — `scripts/ui-tests/run_ui_tests.sh` over `tests_ui/`
      (Textual SVG snapshots + offscreen GUI PNG smoke, the `[ui-test]` extra) — is
      still **not** in `.github/workflows/ci.yml`; it remains an opt-in local lane.
      It was deferred because committed SVG/PNG baselines are sensitive to the
      installed Rich/Textual/PySide6 versions and would need maintenance across the
      five-version CI matrix. Revisit: run it on a single pinned Python version (not
      the full matrix), or gate baseline checks so version drift warns rather than
      fails.
- [ ] **Expand mutation-testing coverage as the test suite matures.** The
      `mutmut` lane (`scripts/mutation/run_mutation.sh`; targets in `[tool.mutmut]`) audits
      the deterministic core today. As tests grow, triage survivors and extend the
      target set if other modules become deterministic enough to mutate usefully.
- [ ] **Consider a non-blocking CI job for mutation testing later.** Mutation
      testing is manual today (not a CI gate, by design). A future CI job could run
      it informationally (report-only, never failing the build) once the survivor
      set is stable enough not to create noise.

## Near-term (cont.)

- [ ] **Triage the stress-suite findings.** `scripts/stress/` (opt-in; see
      CONTRIBUTING) surfaced robustness gaps. None are crashes on normal input;
      each is a hostile/scale edge. Decide per item whether to fix or document as
      a known limit:
  - **Uncaught write `OSError` (ENOSPC/EROFS).** `cli.py`'s stdout/stderr write
    path catches `BrokenPipeError` but not other `OSError`s; a write to a full
    destination (`> /dev/full`) prints a traceback (rc 120). Consider treating any
    write `OSError` like the broken-pipe case (clean message, no traceback).
  - **`KeyboardInterrupt` traceback on Ctrl-C mid-dump.** A SIGINT during a large
    dump prints a `KeyboardInterrupt` traceback (rc 130/-2). Consider catching it
    in `main()` for a clean interrupt.
  - **FIFO/non-regular input hangs.** `core._open_buffer` does `open(path,'rb')`;
    a FIFO with no writer blocks indefinitely. Consider an `S_ISREG` check (or
    `O_NONBLOCK` probe) with a clear error for non-regular files.
  - **truncate-after-mmap → SIGBUS.** A file shrunk beneath a live `ACCESS_READ`
    mmap crashes the process on access. This is an inherent mmap hazard; likely
    **document** as a known limitation rather than guard.
  - **Full-file-scan search RSS.** `.find()` faults every scanned page, so an
    absent-pattern search over an N-GiB file faults ~N GiB into RSS. Consider
    `madvise(MADV_SEQUENTIAL/DONTNEED)` for large scans, or document the ceiling.
  - **`RecursionError` from a deeply nested overlay JSON.** `OverlayState.load`
    catches only `OSError`/`JSONDecodeError`; a pathologically nested document
    escapes as a traceback. Consider also catching `RecursionError` (or
    `ValueError`/`Exception`) and reporting it as a load error diagnostic.
  - **No upper bound on `--width`/`--length`; `--length` ignores file size.** Huge
    values cost memory/time proportional to the value, not the file (the default
    render loop builds every row in `range(model.row_count)`). Consider a sanity
    cap or a streaming render. `--limit-rows` mitigates `--length` today.
* [ ] **Document stress-suite verdict semantics.**
  The stress suite intentionally distinguishes between correctness
  failures, discovered defects, and characterization measurements.
  Document these verdict categories in `scripts/stress/README.md`,
  `CONTRIBUTING.md`, and future stress-test reports so contributors
  interpret results consistently.

  * **PASS** — The expected behavior occurred and the test contract was met.
    Examples: bounded memory use, correct exit status, successful handling of
    edge-case inputs.

  * **FAIL** — The expected behavior did not occur. The test contract was
    violated and should be investigated immediately.

  * **FINDING** — The test successfully exposed a robustness issue, defect,
    limitation, or undesirable behavior. The stress test itself succeeded
    because it reproduced the condition it was designed to explore. Findings
    should be triaged into:

    * fix now
    * document as a known limitation
    * defer to a future release

  * **CHAR** — Characterization result. Records current behavior,
    performance, memory usage, scaling, or other observations without judging
    them as correct or incorrect. These measurements provide a baseline for
    future comparisons and regression detection.

  * Future work:

    * Add a short explanation of verdict categories to the stress-suite
      summary output.
    * Consider linking findings directly to TODO items or issue tracker
      entries.
    * Preserve characterization results that provide useful historical
      baselines for future optimization work.

## Medium-term

- [ ] **Layout-overlay follow-ups (v2+).** Overlay *consumption* now ships (see
      Done). Deferred extensions: overlay **editing**; **config/session
      persistence** of overlay paths (currently never saved, by design — an
      overlay is file/session-specific); **richer per-`status` highlight coloring**
      (v1 uses one neutral highlight); and **multiple independent overlays** for
      multi-file views (currently one `--overlay` = one shared layer).
- [ ] **Signed integer support in layout-overlay-v1.** The v1 type vocabulary is
      unsigned/raw only (`u8`, `u16le/be`, `u32le/be`, `u64le/be`, `bytes`,
      `ascii`, `utf8`); signed fields must be exported conservatively today (e.g.
      `bytes` with a decoded value). A future revision could add `i8`, `i16le/be`,
      `i32le/be`, `i64le/be`. **This is a shared-schema change** — the format and
      validator are vendored from `bintools` (the producer), so coordinate any
      change there; decide whether it is a backward-compatible v1 extension or a
      v2 bump.
- [ ] **GUI Phase 2 — usability (remaining).** Single-key shortcuts and TUI
      parity now ship (see Done: the shared shortcut registry), the visual
      polish pass added system-theme-following light/dark accents, the platform
      fixed-pitch font, a segmented status bar with persistent search/overlay
      segments, scrollable report dialogs, menu key hints, and a runtime
      bytes-per-row control in Options, and the side-by-side layout with
      tri-state markers and horizontal scrolling now ship too (see Done). Still
      open: revisit that `MainWindow.load_paths` re-applies the startup `--ref`
      on every File ▸ Open rather than the last Compare-menu choice; remember
      window size/position and recent files; a toolbar; user-configurable fonts
      and an explicit theme picker (beyond following the system palette);
      `--color`/`--byte-classes` startup flags for TUI flag parity.

- [ ] **Performance Testing**
  - Current coverage is intentionally minimal and serves primarily as a harness smoke test.
  - The performance test framework and runner exist:
      - `scripts/performance/run_all.sh`
      - `tests_perf/`
  - Future work:
    - Add meaningful performance regression tests that catch catastrophic
     slowdowns without becoming machine-sensitive benchmarks.

Candidate areas:

- Core hex row rendering over deterministic 256 KiB-1 MiB inputs.
- Search performance on deterministic data with known match density.
- Overlay lookup/navigation with many overlay ranges.
- Side-by-side diff rendering on moderately sized inputs.
- Memory consumption sanity checks for large files.

Guidelines:

- Performance tests remain opt-in.
- Prefer loose "catastrophic regression" thresholds over microbenchmarks.
- Avoid GUI/TUI event-loop timing where possible.
- Use deterministic generated data.
- Keep individual tests reasonably fast.
- Print timing and input size information.
- Avoid thresholds that vary significantly across developer machines.

## Someday

- [ ] **GUI Phase 4 — navigation.** Bookmarks (named), jump-to-bookmark, offset
      history (back/forward), synchronized navigation between views, minimap.
- [ ] **GUI Phase 5 — selection & copying.** Mouse/keyboard byte selection; copy
      as hex / text / offset ranges / rows / diff regions.
- [ ] **GUI Phase 6 — visualization.** Highlight changed/inserted/deleted ranges,
      customizable colors, per-file visibility toggle, collapsible identical
      regions, difference heatmap.
- [ ] **GUI Phase 7 — editing.** In-place hex/ASCII editing, undo/redo, save / save
      as, modified-region tracking. *Note: every frontend is read-only today;
      editing would be a deliberate scope expansion, not a polish item.*
- [ ] **GUI Phase 8 — large-file support.** Validate multi-GB performance,
      background metadata loading, progress indicators, search cancellation.
- [ ] **Standalone C-struct → layout-overlay extractor.** A helper utility that
      generates `layout-overlay` JSON from real C struct definitions (nested
      structs/unions/arrays/typedefs, `#include` chains, ABI packing/alignment) so
      overlays reflect *compiled* layout, not source assumptions. Prefer
      compiler-assisted approaches (libclang / DWARF / pahole / record-layout
      dumps) over a hand-rolled C parser. It should live **alongside** the viewer,
      not inside it — and likely belongs in `bintools` (the overlay producer)
      rather than multihex. Sketch: `cstruct-layout header.h --struct my_struct
      --overlay-out my_struct.overlay.json`.
- [ ] **Shared frontend architecture.** Search-result bookmarks; a shared
      navigation/session-state model and common rendering abstractions across TUI
      and GUI; a frontend-independent configuration system.
- [ ] **Analysis integration.** Highlight offsets reported by external `bintools`
      tools, import/export annotations, structure/confidence overlays, integration
      with `bindiffmap` and future analysis tools, diff summaries/statistics.
      (Keep the boundary: multihex *visualizes* evidence; it does not parse or
      infer formats.)
- [ ] **Distribution.** Cross-platform packaging, standalone app bundles, release
      automation.

## Done or superseded

- [x] **Single file viewing does not show markers by default.** The CLI, TUI, and
      GUI now resolve an unspecified marker mode to `none` for exactly one input
      file, while an explicit `--markers` choice still wins. Covered by the
      existing CLI/TUI/GUI marker startup tests.
- [x] **Compact TUI/GUI hex blocks (drop the inter-block blank line).** Both
      interactive frontends reserved one unconditional blank line between every
      logical hex block (`_lines_per_block` returned `content + marker + 1`, and
      `HexView._render_block` appended a trailing `"\n"`), so the TUI and GUI were
      less dense than the batch CLI, which never had a separator. The `+ 1` and
      the trailing append are gone, so blocks are now adjacent in all three
      frontends; the marker line still contributes height only when markers are
      on, and the offset still rides the first content line. Purely presentational
      -- comparison semantics, offsets, markers, overlays, color, and JSON are
      untouched, and the CLI goldens are byte-for-byte unchanged. Covered by
      updated `_lines_per_block` assertions plus new "no blank line between
      blocks" tests in `tests/test_tui_layout.py`, `tests/test_gui_layout.py`,
      `tests/test_gui_widget.py`, and `tests/test_cli_layout.py`. Follow-up: the
      TUI SVG snapshots in `tests_ui/__snapshots__/` must be regenerated with
      `scripts/ui-tests/update_snapshots.sh` (needs the `[ui-test]` extra).
- [x] **Size the offset gutter for large offsets.** The gutter was fixed at 8
      hex digits (`OFFSET_LABEL_WIDTH` == 10), so offsets at or above
      `0x100000000` (9+ digits) overgrew the first line's label while
      continuation and marker rows stayed padded to 10 -- the CLI/TUI gutter
      misaligned and the GUI label overlapped the fixed byte columns. The width
      now derives from the largest rendered offset via shared core helpers
      (`offset_hex_digits` / `offset_gutter_width` / `HexModel.max_offset`), with
      the old 8-digit width kept as the minimum so small-file output and goldens
      are byte-for-byte unchanged. All three frontends size the gutter once from
      `model.max_offset` (a stable, non-jittering width); `render_row_text` gained
      a `gutter_width` argument. JSON is unaffected (offsets stay integers), and
      standalone status/search/diagnostic lines were already correct. Covered by
      `tests/test_offset_gutter.py` plus a GUI geometry test.
- [x] **Bound default search memory.** `core.search_files` materialized every
      match, so a frequent needle (an all-`0x00` file searched for `00`) could
      grow an unbounded match list. Frontends now call the new
      `core.search_files_bounded`, which applies a global default cap
      (`DEFAULT_SEARCH_MAX_RESULTS` = 10000) via a cap+1 probe and returns a
      `SearchResults` carrying a `truncated` flag. CLI reports truncation on
      stderr and adds `--search-unlimited` for an explicit uncapped search;
      TUI/GUI annotate the search status line. `search_files` itself is unchanged
      for backward compatibility. Search has no JSON surface, so `--json` is
      unaffected.
- [x] **GUI side-by-side layout (+ tri-state markers, horizontal scrolling).**
      Brought the PySide6 GUI to layout parity with the CLI/TUI. The custom
      painter (`HexCompareView._paint_block`) gained a `side-by-side` branch that
      mirrors `core.render_row_text`'s column geometry exactly (cross-checked in
      `tests/test_gui_layout.py`), reusing a single per-file segment painter for
      both layouts; `v` cycles the layout from the shared registry (no longer
      `gui=False`). Markers became tri-state (single / repeat / none) like the
      TUI — a Markers radio submenu, `m` cycle, an Options combo, a widened
      `--markers`, and a new `--layout` startup flag. Horizontal scrolling is now
      "any overflow": the horizontal scrollbar appears as needed and `←`/`→`
      (also un-gated from the registry) scroll a row wider than the viewport in
      either layout, so a large `--width` in `stacked` scrolls instead of
      clipping (closes the old `TODO(GUI usability)` / `ScrollBarAlwaysOff`). The
      status bar gained `layout` and the marker mode. Display-only throughout:
      no change to offsets, bytes, markers, `--only-diff`, `--ref`, search, or
      JSON, and `core.py` is untouched. Tests: new `tests/test_gui_layout.py`
      (cycling, display-only invariants, geometry-vs-core, highlight-priority
      independence, horizontal scroll), updated `test_shortcuts.py` /
      `test_gui_widget.py` / `test_gui_viewstate.py`, and a `tests_ui/`
      side-by-side render smoke; the help-popup SVG snapshot was regenerated for
      the now layout-agnostic `scroll_horizontal` help text. A companion commit
      extends the TUI's `←`/`→` scroll to engage in stacked overflow too.
- [x] **GUI visual polish pass (modern native Qt).** Reworked the PySide6 GUI's
      presentation without touching comparison/search semantics or the core:
      platform fixed-pitch font sized off the UI font (monospace only for data
      and text reports); an 8px content margin, 640x400 minimum size, and file
      names in the window title; light/dark accent tables selected from the
      widget palette so the view follows the system theme; the layout-overlay
      highlight is now a background fill (it previously shared its teal
      foreground with the WHITESPACE byte class) and SAME/MISSING markers render
      dim so DIFF pops (matching the TUI's emphasis); a segmented status bar
      (position, ref, toggles incl. color/classes, persistent overlay segment
      with warning/error tint, sizes) plus a persistent search segment that
      mirrors the TUI's dedicated search line and survives scrolling; scrollable
      monospace report dialogs replace the QMessageBox help/overlay-details;
      a validated hex-search dialog (OK disabled on bad patterns), wider search
      dialogs with placeholders, and a jump prompt showing the valid range;
      menus reordered (Search before Compare/Overlay), a Compare ▸ Choose
      reference item, and registry single-key hints shown in menu items; and an
      Options bytes-per-row spinner (TUI settings parity, no persistence).
      Pure helpers (`format_status_parts`, `format_search_status`,
      `format_overlay_status`) keep the status logic Qt-free-testable. New
      smoke renders: `gui_dark.png`, `gui_overlay_dialog.png`. No new deps.
- [x] **Attach the offset to its row's data (no standalone offset line).** Every
      block previously printed the offset on its own line with the bytes below it;
      across CLI, TUI, and GUI the offset now rides the first content line as a
      fixed-width left gutter (`core.offset_label()` / `OFFSET_LABEL_WIDTH`), and
      the block's remaining lines indent under it. This applies to both `stacked`
      and `side-by-side` layouts and saves one line per block. Rendering/layout
      only — no change to comparison, offsets, markers, byte grouping, overlay,
      search, color, or JSON. No terminal/viewport width detection was added (the
      offset gutter is a small fixed prefix; existing TUI horizontal scroll, GUI
      clipping, and terminal soft-wrap handle wide rows as before). The GUI still
      renders stacked only; its side-by-side renderer remains a separate Phase 2
      item (see "GUI Phase 2 — usability"). Goldens and TUI SVG snapshots were
      regenerated and visually verified.
- [x] **Real performance lane (replaces the smoke scaffold).** Expanded
      `tests_perf/` from a single harness smoke test into a two-tier suite over
      the perf-critical paths (render loop, exact search, overlay range lookup,
      JSON row building). Tier 1 is deterministic operation-count gates - the
      only hard assertions, so they cannot flake: `build_row` reads each in-bounds
      byte exactly once (never a missing byte), planted-needle corpora yield exact
      match counts, and a single overlay `covers`/`ranges_at` lookup invokes
      `OverlayRange.covers` at most `nranges` times (locking O(nranges), catching
      an O(nranges**2) regression). Instrumentation is entirely test-side (a
      counting buffer; a `monkeypatch` of `OverlayRange.covers`); `core.py` and
      `overlay.py` are untouched and stdlib-only. Tier 2 is advisory timing
      envelopes: each op is run at N/2N/4N (best-of-N minimum) and the doubling
      ratios are printed; they assert only under `PERF_STRICT=1`, against a
      generous self-normalising ceiling. `scripts/performance/run_all.sh` now also
      drives the real CLI under `scripts/stress/measure.py` for subprocess
      wall-clock + peak-RSS characterizations (`--json` whole-file memory,
      big-file case-insensitive search) - informational only, RSS-capped for host
      safety, and SKIP-clean where procfs is absent. `classify_byte` (O(1)) and
      whole-file JSON in-process memory are deliberately left out as unstable
      micro-signals; the latter is the subprocess RSS characterization instead.
      Inputs are seeded and generated at runtime (`perflib.py`,
      `make_input.py`) - no committed blobs. Still opt-in (sibling dir, excluded
      by `testpaths`; gated behind `run-full-test-suite.sh --include-performance`).
      Docs in `tests_perf/README.md` and `scripts/performance/README.md`.
- [x] **Release metadata canonical URLs.** Replaced placeholder public-project
      links in package metadata and the changelog with
      `https://github.com/mrphilcox/multihex`.
- [x] **TUI Home/End + shared shortcut registry (TUI⇄GUI parity).** The TUI now
      binds `Home`/`End` (`action_home`/`action_end`): Home jumps to the start of
      the compared range (honouring `--offset`), End is the bottom-anchored final
      page. Navigation-only — no alignment/resync/inference, and search state is
      untouched. Added `src/multihex/shortcuts.py`, the **single source of truth**
      for the TUI/GUI keymap and help text (the TUI `_HELP` popup and the GUI
      help dialog are generated from it; `tests/test_shortcuts.py` enforces that
      the live TUI `BINDINGS` and the GUI `_action_slots` cannot drift). The GUI
      gained single-key parity for every shared action via a registry-driven
      `MainWindow.keyPressEvent`/`trigger_action` dispatch (`HexCompareView` now
      bubbles keys up), plus new GUI-native equivalents: text/hex **search** (Phase
      3, below), `c` colour and `t` byte-class toggles, `r` reference picker, `o`
      options dialog, and `h`/`?` help. `v` (layout cycle) and `←`/`→` (horizontal
      scroll) stay **TUI-only** (documented in the registry) until the GUI grows a
      side-by-side renderer (Phase 2). Tests: `tests/test_shortcuts.py`,
      `tests/test_tui_home_end.py`, extended `tests/test_gui_widget.py`, and two new
      `tests_ui/` SVG snapshots (End-scrolled, help popup) + a GUI help smoke.
- [x] **GUI Phase 3 — search.** The core search engine now drives the GUI: text
      and hex search (text has the case-insensitive ASCII option; hex matches
      bytes, not ASCII), next/previous navigation (`n`/`N`/`p`), and a match
      highlight tier in the painter (current match stronger; priority below
      missing/diff, mirroring the TUI). Reuses `core` (`search_files` +
      `make_*_query` + `*_match_index`); the GUI renders/navigates only and never
      reimplements search. Stale results are dropped on file reload. Tests live in
      `tests/test_gui_widget.py` (run/next/prev/error/clear) over the core
      `tests/test_search.py`. A results *summary panel* remains a future nicety.
- [x] **Layout-overlay consumption in the viewers.** Added `src/multihex/overlay.py`
      (`OverlayState`/`OverlayRange`): the frontend-agnostic seam that loads an
      overlay JSON, validates it via the `layout_overlay_v1` validator (structural
      once + file-aware per loaded file, diagnostics labelled by file), and answers
      "is offset N covered / which ranges / diagnostics / summary / details". All
      three frontends gained `--overlay PATH` and highlight covered ranges below
      missing/diff styling (CLI blue background; TUI `on blue`; GUI a distinct cell
      color). The TUI adds `l` (load/change), `L` (view; `c` clears); the GUI adds an
      **Overlay** menu (load/change, clear, view). An overlay with any
      error-severity diagnostic is reported but not applied; warnings are summarized
      with full detail in "view current overlay". Overlay paths are **not** persisted
      to config. Robust against overlapping/zero-length/out-of-bounds ranges. Tests:
      `tests/test_overlay.py`, `tests/test_cli_overlay.py`, `tests/test_tui_overlay.py`,
      `tests/test_gui_overlay.py`.
- [x] **Integration-test scaffold.** Added `scripts/integration/`
      (`run_all.sh`, `run_smoke.sh`, `run_cli_behaviors.sh`, `run_layout_overlay.sh`,
      `run_examples.sh`, and shared `lib.sh`) plus
      `tests/integration/generators/make_overlay_samples.py`, driving the real CLI
      entry points and the `layout_overlay_v1` validator end-to-end against a
      generated, deliberately non-canonical corpus. Each case asserts both exit code
      and diagnostic code; the scripts use `mktemp -d`, honour `KEEP_WORK=1`, print
      `PASS`/`FAIL`/`SKIP`, and skip optional frontends cleanly. Not collected by
      pytest (`norecursedirs`). Also added partial example overlays under
      `examples/layouts/` (gzip, ustar). Run with `scripts/integration/run_all.sh`.
- [x] **GUI Frontend (PySide6) — Phase 1 (MVP).** Added `src/multihex/gui.py`
      (`multihex-gui` console script + the `[gui]` optional extra): a read-only Qt
      viewer reusing the core `HexModel`/markers with no new comparison logic. Custom
      `QAbstractScrollArea` that paints only visible rows; opens files from the
      command line or a file dialog; vertical scroll, PageUp/Down, Up/Down, wheel,
      Home/End, and jump-to-offset; View toggles (ASCII gutter, only-diff rows,
      marker strip, basename/path); Compare-menu reference selection; and a status
      bar mirroring the TUI's info line. PySide6 is optional and import-guarded.
      Qt-free `ViewState`/`format_status` helpers are unit-tested
      (`tests/test_gui_viewstate.py`), with smoke/offscreen tests
      (`tests/test_gui_smoke.py`, `tests/test_gui_widget.py`).
- [x] **Opt-in UI visual-regression suite.** `tests_ui/` (Textual SVG snapshots +
      offscreen GUI render smoke), run via `scripts/ui-tests/run_ui_tests.sh`
      (`QT_QPA_PLATFORM=offscreen`, `[ui-test]` extra); baselines regenerated with
      `scripts/ui-tests/update_snapshots.sh`. See `docs/ui-testing.md`.
- [x] **Document frontend architecture** — superseded by `docs/ARCHITECTURE.md`
      (now covers all three frontends) and `docs/API.md`.
- [x] **Document extension points / internal APIs** — superseded by `docs/API.md`
      and the "How to extend" section of `CONTRIBUTING.md`.
- [x] **Create TOOLS.md** — superseded. multihex's three frontends are documented
      in `README.md` and `docs/`; the per-tool `TOOLS.md` lives in the `bintools`
      repo (multihex is the visualization layer, not a CLI-tool collection).
