# TODO

Repo-wide tasks and follow-ups for `multihex` (the visualization layer). Tool /
`layoutcheck` / overlay-export work lives in the sibling `bintools` repo, not
here. Items are grouped by horizon: **Current focus → Near-term → Medium-term →
Someday → Done or superseded**. Move items down as they ship, and add new
follow-ups you discover.

## Current focus

- [ ] **Add Home and End key support in the TUI.** The interactive Textual
      frontend should handle `Home` and `End` consistently with terminal
      navigation expectations: `Home` should move the current viewport/cursor to
      the beginning of the compared byte range, and `End` should move it to the
      final address that can be displayed for the loaded files. Preserve the
      fixed-offset comparison model while doing this; the keys should only
      change navigation state and must not trigger byte alignment, resync, or any
      inferred matching behavior. Add focused tests or characterization coverage
      for the navigation helpers/TUI action paths so empty files, uneven file
      lengths, explicit `--offset`/`--length` ranges, and search result state
      remain well-defined. (The GUI already supports Home/End.)

## Near-term

- [ ] **Persist the TUI text-search case-insensitive preference (optional).** The
      `multihex-tui` text-search panel has a "Case-insensitive (ASCII)" checkbox
      whose state is remembered for the running session only. If desired, promote
      it to a persisted startup default: add a field to `TuiSettings`, wire it
      through `load_settings`/`_dump_toml`/the settings pane (`o`) and
      `build_startup_settings` (and likely a `--search-ignore-case` startup flag).
      Persist only the *preference* — never the search string, match index, or
      results.
- [ ] **Repository housekeeping — set the canonical URL and add a remote.** The
      repo currently has no git remote, so placeholder
      `https://github.com/your-org/multihex` URLs are in use. Once the real URL is
      known, replace the placeholder in `pyproject.toml` → `[project.urls]`
      (`Homepage`, `Repository`, `Changelog`) and `CHANGELOG.md` (the
      `[Unreleased]`/`[0.1.0]` link references), then `git remote add origin <url>`
      and push.

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
- [ ] **GUI Phase 2 — usability.** Horizontal scrolling / wide-row overflow (the
      view uses `ScrollBarAlwaysOff`, so a wide `--width` is silently clipped — see
      the `TODO(GUI usability)` in `src/multihex/gui.py`); revisit that
      `MainWindow.load_paths` re-applies the startup `--ref` on every File ▸ Open
      rather than the last Compare-menu choice; remember window size/position and
      recent files; keyboard shortcuts and a toolbar; a status bar showing current
      offset/file info; configurable fonts; dark/light themes; sync shortcuts with
      the TUI where practical.
- [ ] **GUI Phase 3 — search.** Bring the core search engine to the GUI: hex and
      ASCII/text search (case-insensitive option), next/previous navigation, match
      highlighting, search across all files, and a results summary panel. Reuse
      `core` search; the GUI renders and navigates only.

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
