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

## Done

_(move completed items here)_
