"""Surface adapters and the contract every adapter implements.

A surface is one shared resource that two supposedly isolated runs can both
reach. A carrier is one channel through that surface capable of holding data.
The distinction matters: a filesystem that blocks content reads but permits
listing has closed one carrier and left four open, and a report that collapsed
them into a single row per surface would call that surface clean.

Adapters register themselves into config.SURFACE_TYPES through the `register`
decorator. The dependency runs one way only: adapters import config, config
never imports adapters, and cli imports this package so that registration has
happened before any config is parsed.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Any, ClassVar

from .. import config as config_module
from ..config import ConfigError
from ..report import PERSISTENCE_CLASSES
from ..run_context import RunContext

__all__ = [
    "Carrier",
    "Recovered",
    "Surface",
    "register",
    "validate_param_keys",
]


@dataclass(frozen=True)
class Carrier:
    """One channel through a surface that could hold a nonce."""

    name: str
    persistence: str
    description: str

    def __post_init__(self) -> None:
        if self.persistence not in PERSISTENCE_CLASSES:
            raise ValueError(
                f"persistence must be one of {', '.join(PERSISTENCE_CLASSES)}, "
                f"got {self.persistence!r}"
            )


@dataclass(frozen=True)
class Recovered:
    """What Run B found, or did not find, on one carrier.

    `supported` is the difference between "tested and the nonce did not come
    back" and "could not test this here". The first is a PASS and the second is
    a SKIPPED, and reporting the second as the first would be the probe lying
    about coverage.
    """

    carrier: str
    found: bool
    detail: str
    supported: bool = True


class Surface(ABC):
    """The adapter contract.

    Lifecycle, in order: validate_params at config load, then construct, setup,
    plant with Run A, recover with Run B, cleanup. All plants across all
    surfaces complete before any recover begins, so the probe models two runs
    whose lifetimes do not overlap.
    """

    type_name: ClassVar[str]

    def __init__(self, name: str, params: dict[str, Any], work: Path) -> None:
        self.name = name
        self.params = dict(params)
        self.work = Path(work)

    @classmethod
    def validate_params(cls, params: dict[str, Any], path: str = "params") -> None:
        """Reject unknown or badly typed params. Raise ConfigError, never warn.

        A classmethod because it runs at config load, before anything is
        constructed: a typo in params should cost exit code 2 and no side
        effects at all, not a half built surface.
        """
        validate_param_keys(params, {}, path)

    @classmethod
    @abstractmethod
    def carriers(cls) -> list[Carrier]:
        """Every carrier this adapter tests, whether or not it is supported here.

        A classmethod so that `declared` entries naming a carrier can be checked
        at config load. The list is fixed per adapter type; whether a given
        carrier is testable in this environment is answered later, by recover.
        """

    def setup(self) -> None:
        """Create or attach to the shared resource. Default: nothing to do.

        Optional on purpose rather than abstract: an adapter for a surface that
        already exists has nothing to create, and forcing it to write an empty
        override would be noise.
        """
        return None

    @abstractmethod
    def plant(self, nonce: str, run: RunContext) -> None:
        """Run A writes the nonce through every write path this surface permits."""

    @abstractmethod
    def recover(self, run: RunContext) -> list[Recovered]:
        """Run B reads back through every read path, one Recovered per carrier."""

    def cleanup(self) -> None:
        """Release anything setup created. Default: nothing to do."""
        return None


def register(cls: type[Surface]) -> type[Surface]:
    """Insert an adapter class into the surface type registry."""
    type_name = getattr(cls, "type_name", None)
    if not type_name:
        raise ValueError(f"{cls.__name__} must set type_name before it can be registered")
    # Looked up through the module rather than through a direct import of the
    # dict, so that a test can swap the registry and have both register and
    # config.parse see the same swapped one.
    registry = config_module.SURFACE_TYPES
    existing = registry.get(type_name)
    if existing is not None and existing is not cls:
        raise ValueError(
            f"surface type {type_name!r} is already registered to {existing.__name__}"
        )
    registry[type_name] = cls
    return cls


def validate_param_keys(
    params: dict[str, Any], allowed: dict[str, type | tuple[type, ...]], path: str
) -> None:
    """Reject unknown keys and wrong types, in the message shape config.py uses."""
    for key, value in params.items():
        location = f"{path}.{key}"
        if key not in allowed:
            allowed_list = ", ".join(sorted(allowed)) or "no params are accepted here"
            raise ConfigError(
                f"unknown key: {key!r} at {location} (allowed keys here: {allowed_list})"
            )
        expected = allowed[key]
        # bool is a subclass of int, so an isinstance check for int would accept
        # true. Nothing here wants an int, but the trap is worth closing early.
        if expected is not bool and isinstance(value, bool):
            raise ConfigError(f"{location} must be {_type_name(expected)}, got bool")
        if not isinstance(value, expected):
            raise ConfigError(
                f"{location} must be {_type_name(expected)}, got {type(value).__name__}"
            )


_TYPE_NAMES = {str: "a string", bool: "true or false", int: "an integer"}


def _type_name(expected: type | tuple[type, ...]) -> str:
    if isinstance(expected, tuple):
        return " or ".join(_TYPE_NAMES.get(t, t.__name__) for t in expected)
    return _TYPE_NAMES.get(expected, expected.__name__)


# Imported for their side effect: each module registers its adapter class into
# config.SURFACE_TYPES. Placed at the bottom because they import names defined
# above. cli.py imports this package, so registration happens before any config
# is parsed.
from . import filesystem  # noqa: E402,F401
