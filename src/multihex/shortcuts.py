# Copyright (c) 2026 Philip Cox
# SPDX-License-Identifier: Apache-2.0

"""multihex.shortcuts - the single source of truth for frontend keyboard shortcuts.

Both interactive frontends (the Textual ``multihex-tui`` and the PySide6
``multihex-gui``) draw their keymap and on-screen help from the one ``SHORTCUTS``
table here, so the two cannot drift. The TUI's help popup is rendered by
:func:`tui_help_text`; the GUI's help dialog by :func:`gui_help_text`; the GUI's
single-key dispatch is built from :func:`gui_text_map` / :func:`gui_key_names`.
``tests/test_shortcuts.py`` enforces that the live TUI ``BINDINGS`` and the GUI
``_action_slots`` stay in agreement with this table.

This module is **stdlib-only on purpose** (no ``multihex.core``, Textual, or
PySide6 imports) so it loads in every context -- including when neither GUI
toolkit is installed. Each frontend resolves the abstract key descriptors into
its own toolkit symbols:

* ``tui_keys`` are Textual key tokens ("j", "down", "pagedown", "question_mark").
* ``gui_keys`` are abstract descriptors the GUI resolves itself:
  ``"t:<char>"`` matches ``QKeyEvent.text()`` (printable keys, case-sensitive);
  ``"k:<Name>"`` matches ``QKeyEvent.key()`` via ``Qt.Key.Key_<Name>`` (named
  special keys whose ``.text()`` is empty, e.g. Down/PageUp/Home/End).
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Shortcut:
    """One keyboard action, shared across the interactive frontends.

    ``action_id`` is the stable join key used everywhere (help generation, the
    GUI dispatch table, the BINDINGS cross-check). ``display_keys`` and
    ``help_text`` are the only source of on-screen help text. ``tui`` / ``gui``
    mark applicability; an excluded frontend carries a ``note`` explaining why.
    """

    action_id: str
    display_keys: str            # help column, e.g. "j / down", "N / p", "h / ?"
    help_text: str               # help description (TUI wording)
    tui_keys: tuple              # Textual key tokens
    gui_keys: tuple              # GUI descriptors ("t:<char>" / "k:<Name>")
    tui: bool = True
    gui: bool = True
    note: str = ""               # documented reason when a frontend is excluded
    gui_help: str = ""           # optional GUI-specific help wording (else help_text)


# Ordered exactly as the TUI help popup reads, with Home/End added after the
# paging keys. Every action applies to both interactive frontends: the GUI gained
# the side-by-side layout (``v``) and horizontal scrolling (``left``/``right``)
# the TUI already had, so no entry is frontend-exclusive anymore.
SHORTCUTS: tuple = (
    Shortcut("quit", "q", "quit", ("q",), ("t:q",)),
    Shortcut("next_row", "j / down", "next row", ("j", "down"), ("t:j", "k:Down")),
    Shortcut("prev_row", "k / up", "previous row", ("k", "up"), ("t:k", "k:Up")),
    Shortcut("next_page", "PageDown", "next page", ("pagedown",), ("k:PageDown",)),
    Shortcut("prev_page", "PageUp", "previous page", ("pageup",), ("k:PageUp",)),
    Shortcut("home", "Home", "jump to start of range", ("home",), ("k:Home",)),
    Shortcut("end", "End", "jump to end (last page)", ("end",), ("k:End",)),
    Shortcut("jump", "g", "jump to offset", ("g",), ("t:g",)),
    Shortcut("choose_ref", "r", "choose reference file", ("r",), ("t:r",)),
    Shortcut("toggle_ascii", "a", "toggle ASCII gutter", ("a",), ("t:a",)),
    Shortcut("toggle_diff", "d", "toggle only-diff rows", ("d",), ("t:d",)),
    Shortcut("toggle_color", "c", "toggle color", ("c",), ("t:c",)),
    Shortcut(
        "toggle_byte_classes", "t", "toggle byte-class highlighting",
        ("t",), ("t:t",),
    ),
    Shortcut(
        "cycle_layout", "v", "cycle layout (stacked / side-by-side)",
        ("v",), ("t:v",),
    ),
    Shortcut(
        "cycle_markers", "m", "cycle markers (single / repeat / none)",
        ("m",), ("t:m",),
    ),
    Shortcut(
        "load_overlay", "l", "load/change layout overlay (blank path clears)",
        ("l",), ("t:l",), gui_help="load/change layout overlay",
    ),
    Shortcut(
        "view_overlay", "L", "view current layout overlay (c clears)",
        ("L",), ("t:L",), gui_help="view current layout overlay",
    ),
    Shortcut(
        "scroll_horizontal", "left / right", "scroll horizontally",
        ("left", "right"), ("k:Left", "k:Right"),
    ),
    Shortcut("open_settings", "o", "open settings / options pane", ("o",), ("t:o",)),
    Shortcut(
        "search_text", "/", "text search (case-insensitive toggle)",
        ("slash",), ("t:/",),
    ),
    Shortcut(
        "search_hex", "x", "hex search (matches bytes, not ASCII)",
        ("x",), ("t:x",),
    ),
    Shortcut("next_match", "n", "next match", ("n",), ("t:n",)),
    Shortcut("prev_match", "N / p", "previous match", ("N", "p"), ("t:N", "t:p")),
    Shortcut("help", "h / ?", "this help", ("h", "question_mark"), ("t:h", "t:?")),
)


def tui_shortcuts() -> tuple:
    """Shortcuts that apply to the Textual TUI, in display order."""
    return tuple(s for s in SHORTCUTS if s.tui)


def gui_shortcuts() -> tuple:
    """Shortcuts that apply to the PySide6 GUI, in display order."""
    return tuple(s for s in SHORTCUTS if s.gui)


def _help_body(shortcuts: tuple, wording) -> str:
    return "\n".join(
        f"  {s.display_keys:<13} {wording(s)}" for s in shortcuts
    )


def tui_help_text(
    title: str = "multihex-tui - keys",
    footer: str = "(any key to close)",
) -> str:
    """Render the TUI help popup body from the registry.

    Reproduces the historical column layout (a 13-wide left-justified key column)
    so the rendered help is stable; the registry is now the only place it lives.
    """
    body = _help_body(tui_shortcuts(), lambda s: s.help_text)
    return f"{title}\n\n{body}\n\n  {footer}"


def gui_help_text(title: str = "multihex-gui - keys") -> str:
    """Render the GUI help dialog body from the registry.

    Uses each shortcut's ``gui_help`` override where set (e.g. GUI overlay
    wording), and includes only ``gui``-applicable entries. No "any key to close"
    footer -- the GUI help is a dismissible dialog.
    """
    body = _help_body(gui_shortcuts(), lambda s: s.gui_help or s.help_text)
    return f"{title}\n\n{body}"


def gui_text_map() -> dict:
    """Map a printable key character to its action id (GUI ``"t:<char>"`` keys)."""
    out: dict = {}
    for s in gui_shortcuts():
        for key in s.gui_keys:
            if key.startswith("t:"):
                ch = key[2:]
                if ch in out:
                    raise ValueError(f"duplicate GUI text key {ch!r}")
                out[ch] = s.action_id
    return out


def gui_key_names() -> dict:
    """Map a Qt key *name* (e.g. ``"Down"``) to its action id (GUI ``"k:<Name>"``)."""
    out: dict = {}
    for s in gui_shortcuts():
        for key in s.gui_keys:
            if key.startswith("k:"):
                name = key[2:]
                if name in out:
                    raise ValueError(f"duplicate GUI key name {name!r}")
                out[name] = s.action_id
    return out
