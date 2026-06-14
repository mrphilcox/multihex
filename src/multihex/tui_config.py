# Copyright (c) 2026 Philip Cox
# SPDX-License-Identifier: Apache-2.0

"""multihex.tui_config - TUI-only persistent preferences (config file I/O).

This module is used **only** by the interactive ``multihex-tui`` frontend; the
batch ``multihex`` CLI never imports it and never reads a config file, so its
output stays explicit and scriptable. It owns config-path discovery, loading +
validation, and atomic saving of a small, fixed TOML document.

Scope is *preferences and startup defaults only* -- never session state (no
reference file, offset, scroll, search string/match, file list, or bookmarks).

Precedence is applied by the frontend, not here:
    built-in defaults -> config file -> CLI args -> interactive changes

Reading uses the stdlib ``tomllib`` on Python 3.11+, falling back to the
third-party ``tomli`` on 3.9/3.10 (declared only in the TUI/dev extras). Writing
uses a tiny local serializer for this fixed two-table shape, so no TOML *writer*
dependency is needed. This module imports nothing from ``multihex.core`` and uses
no Textual/Rich types.
"""

from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from multihex import __version__ as MULTIHEX_VERSION

try:  # Python 3.11+
    import tomllib as _toml
except ModuleNotFoundError:  # pragma: no cover - exercised on 3.9/3.10 only
    import tomli as _toml  # type: ignore[no-redef]


# Schema version of the config *format* (independent of the application version,
# per design). Bump only when the on-disk shape changes incompatibly.
SUPPORTED_CONFIG_VERSION = 1

# Allowed values for the string-valued settings (mirrors the CLI choices).
_LAYOUTS = ("stacked", "side-by-side")
_COLORS = ("auto", "always", "never")
_NAMES = ("basename", "path")
_MARKERS = ("single", "repeat", "none")


@dataclass
class TuiSettings:
    """Persisted TUI display preferences / startup defaults.

    Defaults here are the built-in defaults (lowest precedence). Strings are used
    for the enumerated settings to match the existing CLI ``choices=`` style.
    """

    layout: str = "stacked"
    ascii: bool = True
    byte_classes: bool = False
    color: str = "auto"
    names: str = "basename"
    markers: str = "single"
    width: int = 16
    only_diff: bool = False


# --------------------------------------------------------------------------- #
# Path discovery
# --------------------------------------------------------------------------- #
def default_config_path() -> Path:
    """Return the default config path, honoring ``XDG_CONFIG_HOME``.

    ``$XDG_CONFIG_HOME/multihex/tui.toml`` when that variable is set (and
    non-empty), otherwise ``~/.config/multihex/tui.toml``.
    """
    xdg = os.environ.get("XDG_CONFIG_HOME")
    base = Path(xdg) if xdg else Path.home() / ".config"
    return base / "multihex" / "tui.toml"


# --------------------------------------------------------------------------- #
# Loading + validation
# --------------------------------------------------------------------------- #
def _is_bool(value: Any) -> bool:
    return isinstance(value, bool)


def _is_pos_int(value: Any) -> bool:
    # bool is a subclass of int; reject it so ``width = true`` is invalid.
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def load_settings(
    path: Path, base: Optional[TuiSettings] = None
) -> Tuple[TuiSettings, List[str]]:
    """Load ``path`` over ``base`` defaults, returning ``(settings, warnings)``.

    A missing file is normal: returns a copy of ``base`` with no warnings. Any
    problem (unreadable, unparseable, missing/too-new ``config_version``) makes
    the whole config be ignored, returning a copy of ``base`` plus a warning. For
    a supported version, each known key is validated individually; an invalid
    value is dropped (keeping the lower-precedence ``base`` value) with a warning,
    and unknown keys are ignored with a warning. Warnings are never fatal.
    """
    base = base or TuiSettings()
    settings = replace(base)
    warnings: List[str] = []

    if not path.exists():
        return settings, warnings

    try:
        with open(path, "rb") as fh:
            data: Dict[str, Any] = _toml.load(fh)
    except OSError as exc:
        return settings, [f"could not read config {path}: {exc}"]
    except _toml.TOMLDecodeError as exc:
        return settings, [f"could not parse config {path}: {exc}"]

    version = data.get("config_version")
    if version is None:
        return settings, [
            f"config {path} has no config_version; ignoring it and using defaults"
        ]
    if (
        not isinstance(version, int)
        or isinstance(version, bool)
        or version > SUPPORTED_CONFIG_VERSION
    ):
        return settings, [
            f"config {path} has unsupported config_version {version!r} "
            f"(this build supports {SUPPORTED_CONFIG_VERSION}); ignoring it"
        ]

    # Top-level keys we knowingly accept (besides the two tables below).
    _known_top = {"config_version", "multihex_version", "display", "view"}
    for key in data:
        if key not in _known_top:
            warnings.append(f"ignoring unknown config key {key!r}")

    display = data.get("display", {})
    view = data.get("view", {})
    if not isinstance(display, dict):
        warnings.append("ignoring [display]: not a table")
        display = {}
    if not isinstance(view, dict):
        warnings.append("ignoring [view]: not a table")
        view = {}

    # (table, key, attribute, validator, allowed-for-message)
    fields = [
        (display, "layout", "layout", lambda v: v in _LAYOUTS, _LAYOUTS),
        (display, "ascii", "ascii", _is_bool, None),
        (display, "byte_classes", "byte_classes", _is_bool, None),
        (display, "color", "color", lambda v: v in _COLORS, _COLORS),
        (display, "names", "names", lambda v: v in _NAMES, _NAMES),
        (display, "markers", "markers", lambda v: v in _MARKERS, _MARKERS),
        (view, "width", "width", _is_pos_int, None),
        (view, "only_diff", "only_diff", _is_bool, None),
    ]
    for table, key, attr, valid, allowed in fields:
        if key not in table:
            continue
        value = table[key]
        if valid(value):
            setattr(settings, attr, value)
        else:
            hint = f" (expected one of {allowed})" if allowed else ""
            warnings.append(
                f"ignoring invalid value for {key} = {value!r}{hint}; "
                f"using {getattr(base, attr)!r}"
            )

    # Warn about unknown keys inside the known tables, too.
    for table, valid_keys in (
        (display, {"layout", "ascii", "byte_classes", "color", "names", "markers"}),
        (view, {"width", "only_diff"}),
    ):
        for key in table:
            if key not in valid_keys:
                warnings.append(f"ignoring unknown config key {key!r}")

    return settings, warnings


# --------------------------------------------------------------------------- #
# Saving
# --------------------------------------------------------------------------- #
def _toml_bool(value: bool) -> str:
    return "true" if value else "false"


def _toml_str(value: str) -> str:
    # The persisted strings are simple identifiers / paths-free enums; a basic
    # escape of backslashes and quotes keeps the output valid regardless.
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def _dump_toml(settings: TuiSettings) -> str:
    """Serialize ``settings`` to the complete, fixed TOML document shape."""
    return (
        f"config_version = {SUPPORTED_CONFIG_VERSION}\n"
        f"multihex_version = {_toml_str(MULTIHEX_VERSION)}\n"
        "\n"
        "[display]\n"
        f"layout = {_toml_str(settings.layout)}\n"
        f"ascii = {_toml_bool(settings.ascii)}\n"
        f"byte_classes = {_toml_bool(settings.byte_classes)}\n"
        f"color = {_toml_str(settings.color)}\n"
        f"names = {_toml_str(settings.names)}\n"
        f"markers = {_toml_str(settings.markers)}\n"
        "\n"
        "[view]\n"
        f"width = {settings.width}\n"
        f"only_diff = {_toml_bool(settings.only_diff)}\n"
    )


def save_settings(settings: TuiSettings, path: Path) -> None:
    """Atomically write a **complete** config (all settings) to ``path``.

    Creates parent directories as needed. Writes to a temporary file in the same
    directory and ``os.replace``s it into place so a failed/partial write never
    clobbers an existing config. Exceptions (e.g. ``OSError``) propagate to the
    caller, which is responsible for surfacing them.
    """
    path = Path(path)
    parent = path.parent
    os.makedirs(parent, exist_ok=True)
    text = _dump_toml(settings)

    fd, tmp_name = tempfile.mkstemp(dir=parent, prefix=".tui-", suffix=".toml.tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
        os.replace(tmp_name, path)
    except BaseException:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise
