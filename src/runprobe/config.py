"""Strict loader for surfaces.json.

Fail closed. Every problem here is an error with a path, never a warning, and
never a silently ignored key. An unknown key is far more likely to be a typo in a
surface the operator meant to probe than it is to be harmless.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# Surface type registry. Empty in Phase 0 by design: no adapters exist yet, so
# every configured type is rejected with "unknown surface type: X". Phase 1 adds
# filesystem and git_remote, Phase 2 adds http_cache.
SURFACE_TYPES: dict[str, str] = {}

TOP_LEVEL_KEYS = frozenset({"surfaces", "declared"})
SURFACE_KEYS = frozenset({"name", "type", "params"})


class ConfigError(Exception):
    """Raised for any invalid config. Callers turn this into a non-zero exit."""


@dataclass(frozen=True)
class SurfaceConfig:
    """One configured surface. `params` is passed through to the adapter."""

    name: str
    type: str
    params: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Config:
    """A validated surfaces.json.

    `declared` holds channels the operator has explicitly authorized, each as
    "surface_name:carrier_name". A recovered nonce on a declared channel is
    reported AUTHORIZED instead of FAIL.
    """

    surfaces: list[SurfaceConfig]
    declared: list[str] = field(default_factory=list)
    source: Path | None = None

    def is_declared(self, surface: str, carrier: str) -> bool:
        return f"{surface}:{carrier}" in self.declared


def _reject_unknown_keys(obj: dict[str, Any], allowed: frozenset[str], path: str) -> None:
    for key in obj:
        if key not in allowed:
            location = f"{path}.{key}" if path else key
            allowed_list = ", ".join(sorted(allowed))
            raise ConfigError(
                f"unknown key: {key!r} at {location} (allowed keys here: {allowed_list})"
            )


def _require_type(value: Any, expected: type, path: str, expected_name: str) -> None:
    if not isinstance(value, expected):
        raise ConfigError(f"{path} must be {expected_name}, got {type(value).__name__}")


def parse(data: Any, source: Path | None = None) -> Config:
    """Validate an already decoded JSON document and return a Config.

    Validation order matters. Structural checks run across every surface before
    any surface type is resolved, so that a config with both a typo and an
    unbuilt adapter reports the typo, which is the fixable problem.
    """
    if not isinstance(data, dict):
        raise ConfigError(f"config root must be an object, got {type(data).__name__}")

    _reject_unknown_keys(data, TOP_LEVEL_KEYS, "")

    if "surfaces" not in data:
        raise ConfigError("missing required key: 'surfaces' at config root")

    raw_surfaces = data["surfaces"]
    _require_type(raw_surfaces, list, "surfaces", "a list")
    if not raw_surfaces:
        raise ConfigError("surfaces must not be empty: declare at least one surface to probe")

    surfaces: list[SurfaceConfig] = []
    seen: dict[str, int] = {}

    for index, raw in enumerate(raw_surfaces):
        path = f"surfaces[{index}]"
        _require_type(raw, dict, path, "an object")
        _reject_unknown_keys(raw, SURFACE_KEYS, path)

        if "name" not in raw:
            raise ConfigError(f"missing required key: 'name' at {path}")
        _require_type(raw["name"], str, f"{path}.name", "a string")
        if not raw["name"]:
            raise ConfigError(f"{path}.name must not be empty")

        if "type" not in raw:
            raise ConfigError(f"missing required key: 'type' at {path}")
        _require_type(raw["type"], str, f"{path}.type", "a string")

        params = raw.get("params", {})
        _require_type(params, dict, f"{path}.params", "an object")

        name = raw["name"]
        if name in seen:
            raise ConfigError(
                f"duplicate surface name: {name!r} at {path}, "
                f"already defined at surfaces[{seen[name]}]"
            )
        seen[name] = index

        surfaces.append(SurfaceConfig(name=name, type=raw["type"], params=dict(params)))

    declared = _parse_declared(data.get("declared", []), {s.name for s in surfaces})

    for index, surface in enumerate(surfaces):
        if surface.type not in SURFACE_TYPES:
            known = ", ".join(sorted(SURFACE_TYPES)) or "none registered in this build"
            raise ConfigError(
                f"unknown surface type: {surface.type} at surfaces[{index}].type "
                f"(known types: {known})"
            )

    return Config(surfaces=surfaces, declared=declared, source=source)


def _parse_declared(raw: Any, surface_names: set[str]) -> list[str]:
    _require_type(raw, list, "declared", "a list")
    declared: list[str] = []
    for index, entry in enumerate(raw):
        path = f"declared[{index}]"
        _require_type(entry, str, path, "a string")
        if entry.count(":") != 1:
            raise ConfigError(
                f"{path} must be exactly 'surface_name:carrier_name', got {entry!r}"
            )
        surface_name, carrier = entry.split(":", 1)
        if not surface_name or not carrier:
            raise ConfigError(
                f"{path} must be exactly 'surface_name:carrier_name', got {entry!r}"
            )
        if surface_name not in surface_names:
            known = ", ".join(sorted(surface_names))
            raise ConfigError(
                f"{path} names an undefined surface: {surface_name!r} (defined surfaces: {known})"
            )
        declared.append(entry)
    return declared


def load(path: str | Path) -> Config:
    """Read and validate a surfaces.json file."""
    config_path = Path(path)
    try:
        text = config_path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise ConfigError(f"config file not found: {config_path}") from exc
    except IsADirectoryError as exc:
        raise ConfigError(f"config path is a directory, not a file: {config_path}") from exc
    except OSError as exc:
        raise ConfigError(f"could not read config file {config_path}: {exc}") from exc

    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ConfigError(f"config file {config_path} is not valid JSON: {exc}") from exc

    return parse(data, source=config_path)
