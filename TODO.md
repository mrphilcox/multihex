# TODO

Repo-wide tasks and follow-ups to track.

## Open

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
      remain well-defined.
- [ ] **Set the canonical repository URL.** The repo currently has no git remote,
      so placeholder `https://github.com/your-org/multihex` URLs are in use. Once
      the real URL is known, replace the placeholder in:
  - `pyproject.toml` → `[project.urls]` (`Homepage`, `Repository`, `Changelog`)
  - `CHANGELOG.md` → the `[Unreleased]` and `[0.1.0]` link references at the bottom
- [ ] Add the git remote (`git remote add origin <url>`) and push.
- [ ] **Persist the TUI text-search case-insensitive preference (optional).** The
      `multihex-tui` text-search panel now has a "Case-insensitive (ASCII)"
      checkbox whose state is remembered for the running session only. If desired,
      promote it to a persisted startup default: add a field to `TuiSettings`,
      wire it through `load_settings`/`_dump_toml`/the settings pane (`o`) and
      `build_startup_settings` (and likely a `--search-ignore-case` startup flag).
      Persist only the *preference* — never the search string, match index, or
      results.

## Documentation

* [ ] Create TOOLS.md.
* [ ] Document frontend architecture.
* [ ] Document extension points and internal APIs.

## Core Viewer Features

* [ ] Home/End support in TUI.
* [ ] Persist search preferences.
* [ ] Search result bookmarks.
* [ ] Shared navigation model.

## GUI Frontend (PySide6)

### Phase 1 - MVP — complete (see Done; implemented in `src/multihex/gui.py`)

* [x] Add PySide6 optional dependency group.
* [x] Add `multihex-gui` entry point.
* [x] Create initial GUI frontend using existing backend.
* [x] Support opening multiple files from command line.
* [x] Support opening files from a file picker dialog.
* [x] Display side-by-side file comparison.
* [x] Support vertical scrolling.
* [x] Support jump-to-offset.
* [x] Support reference-file selection.
* [x] Support ASCII column toggle.
* [x] Support marker mode toggle.
* [x] Support only-diff mode.
* [x] Preserve existing CLI/TUI formatting semantics.
* [x] Lazy rendering of visible rows only.


### Phase 2 - Usability

* [ ] **Horizontal scrolling / wide-row overflow (GUI).** The view has no horizontal
      scrollbar (`ScrollBarAlwaysOff`), so a wide `--width` (rows wider than the
      viewport) is silently clipped on the right. Add a horizontal scrollbar or
      overflow handling. See the `TODO(GUI usability)` at the policy site in
      `src/multihex/gui.py`.
* [ ] **GUI reload reuses the startup `--ref` (minor).** `MainWindow.load_paths`
      re-applies `self._start_ref` (the CLI value) on every File ▸ Open, rather than
      the reference the user last picked from the Compare menu. Defensible (a fresh
      file set resets to the CLI default) but revisit if it surprises users.
* [ ] Remember window size and position.
* [ ] Remember recent files.
* [ ] Add keyboard shortcuts.
* [ ] Add toolbar controls.
* [ ] Add status bar showing current offset and file information.
* [ ] Add configurable fonts.
* [ ] Add dark/light theme support.
* [ ] Synchronize keyboard shortcuts with TUI where practical.

### Phase 3 - Search

* [ ] Hex search.
* [ ] ASCII/text search.
* [ ] Case-insensitive text search.
* [ ] Next/previous match navigation.
* [ ] Match highlighting.
* [ ] Search across all files.
* [ ] Search results summary panel.

### Phase 4 - Navigation

* [ ] Bookmarks.
* [ ] Named bookmarks.
* [ ] Jump-to-bookmark.
* [ ] Offset history (back/forward).
* [ ] Synchronize navigation between views.
* [ ] Minimap/overview pane.

### Phase 5 - Selection and Copying

* [ ] Mouse-based byte selection.
* [ ] Keyboard selection.
* [ ] Copy bytes as hex.
* [ ] Copy bytes as text.
* [ ] Copy offset ranges.
* [ ] Copy entire rows.
* [ ] Copy diff regions.

### Phase 6 - Visualization

* [ ] Highlight changed byte ranges.
* [ ] Highlight inserted/deleted regions.
* [ ] Customizable colors.
* [ ] Per-file visibility toggle.
* [ ] Collapsible identical regions.
* [ ] Overview heatmap of differences.

### Phase 7 - Editing

* [ ] In-place hex editing.
* [ ] In-place ASCII editing.
* [ ] Undo/redo.
* [ ] Save modified files.
* [ ] Save As.
* [ ] Modified-region tracking.

### Phase 8 - Large File Support

* [ ] Validate performance on multi-GB files.
* [ ] Background loading of metadata.
* [ ] Progress indicators for expensive operations.
* [ ] Search cancellation support.

## Future Investigation

### Shared Frontend Architecture
- [ ] Shared navigation/session state between TUI and GUI.
- [ ] Common rendering abstractions.
- [ ] Frontend-independent configuration system.

### Analysis Integration
* [ ] Search results pane shared with analysis tools.
* [ ] Highlight offsets reported by external tools.
* [ ] Import/export annotations.
* [ ] Structure overlays.
* [ ] Confidence-map overlays.
* [ ] Integration with bindiffmap.
* [ ] Integration with future binary analysis tools.
* [ ] File-format inference visualizations.
* [ ] Cross-reference and field tracking.
* [ ] Plugin architecture for analysis tools.
* [ ] Named regions and annotations.
* [ ] Binary structure overlays and annotations.
* [ ] Diff summaries and statistics.
* [ ] Embedded file format analysis integration.


### Distribution
* [ ] Cross-platform packaging and release process.
- [ ] Standalone application bundles.
- [ ] Release automation.

## Done

- [x] **GUI Frontend (PySide6) — Phase 1 (MVP).** Added `src/multihex/gui.py`
      (`multihex-gui` console script + the `[gui]` optional extra): a read-only Qt
      viewer reusing the core `HexModel`/markers with no new comparison logic. Custom
      `QAbstractScrollArea` that paints only the visible rows (no whole-range buffer);
      opens files from the command line or a file dialog; vertical scroll, PageUp/Down,
      Up/Down, wheel, Home/End, and jump-to-offset; View toggles for the ASCII gutter,
      only-diff rows, the marker strip, and basename/path names; Compare-menu
      reference-file selection including all-agree; and a status bar mirroring the TUI's
      info line. PySide6 is optional and import-guarded (clean message + non-zero exit
      when absent), matching the TUI's textual guard. Navigation/filter/status logic is
      in the Qt-free `ViewState`/`format_status` helpers and unit-tested
      (`tests/test_gui_viewstate.py`), with smoke + offscreen-widget tests
      (`tests/test_gui_smoke.py`, `tests/test_gui_widget.py`).
