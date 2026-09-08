"""Probe report: findings, JSON output, and the plain text table.

One row per (surface, carrier). A nonce either came back or it did not, so a
finding carries no score, no confidence, and no model judgement.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any

# FAIL: the nonce planted by Run A was recovered by Run B on an undeclared channel.
# PASS: the nonce was not recovered.
# AUTHORIZED: recovered, but the operator declared this channel in surfaces.json.
# SKIPPED: the surface could not be probed (a required tool is missing, for example).
# ERROR: the adapter itself failed. Treated as a failure, never as a pass.
VERDICTS = ("FAIL", "PASS", "AUTHORIZED", "SKIPPED", "ERROR")

# How long a recovered carrier survives. "unknown" is honest, not a placeholder:
# some carriers cannot be classified without knowing the operator's retention.
PERSISTENCE_CLASSES = ("transient", "durable", "until-gc", "unknown")

FAILING_VERDICTS = frozenset({"FAIL", "ERROR"})

REPORT_SCHEMA_VERSION = 1


@dataclass(frozen=True)
class Finding:
    """One (surface, carrier) result."""

    surface: str
    carrier: str
    verdict: str
    persistence: str
    detail: str = ""

    def __post_init__(self) -> None:
        if self.verdict not in VERDICTS:
            raise ValueError(
                f"verdict must be one of {', '.join(VERDICTS)}, got {self.verdict!r}"
            )
        if self.persistence not in PERSISTENCE_CLASSES:
            raise ValueError(
                f"persistence must be one of {', '.join(PERSISTENCE_CLASSES)}, "
                f"got {self.persistence!r}"
            )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Finding:
        return cls(
            surface=data["surface"],
            carrier=data["carrier"],
            verdict=data["verdict"],
            persistence=data["persistence"],
            detail=data.get("detail", ""),
        )


def utc_timestamp() -> str:
    """Return the current time as a UTC ISO 8601 string with a trailing Z."""
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


@dataclass
class Report:
    """The result of one probe run."""

    nonce: str
    run_id_a: str
    run_id_b: str
    timestamp: str = field(default_factory=utc_timestamp)
    findings: list[Finding] = field(default_factory=list)
    schema_version: int = REPORT_SCHEMA_VERSION

    def add(self, finding: Finding) -> None:
        self.findings.append(finding)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "nonce": self.nonce,
            "run_id_a": self.run_id_a,
            "run_id_b": self.run_id_b,
            "timestamp": self.timestamp,
            "findings": [f.to_dict() for f in self.findings],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Report:
        return cls(
            nonce=data["nonce"],
            run_id_a=data["run_id_a"],
            run_id_b=data["run_id_b"],
            timestamp=data["timestamp"],
            findings=[Finding.from_dict(f) for f in data.get("findings", [])],
            schema_version=data.get("schema_version", REPORT_SCHEMA_VERSION),
        )

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, sort_keys=False)

    @classmethod
    def from_json(cls, text: str) -> Report:
        return cls.from_dict(json.loads(text))

    def to_table(self) -> str:
        """Render findings as fixed-width plain text. ASCII only, no box drawing."""
        headers = ("SURFACE", "CARRIER", "VERDICT", "PERSISTENCE", "DETAIL")
        rows = [
            (f.surface, f.carrier, f.verdict, f.persistence, f.detail) for f in self.findings
        ]

        widths = [len(h) for h in headers]
        for row in rows:
            for i, cell in enumerate(row):
                widths[i] = max(widths[i], len(cell))

        def render(cells: tuple[str, ...]) -> str:
            padded = [cell.ljust(widths[i]) for i, cell in enumerate(cells)]
            return "  ".join(padded).rstrip()

        lines = [render(headers), render(tuple("-" * w for w in widths))]
        lines.extend(render(row) for row in rows)
        return "\n".join(lines)

    def exit_code(self) -> int:
        """Return 1 if any finding is FAIL or ERROR, else 0."""
        return 1 if any(f.verdict in FAILING_VERDICTS for f in self.findings) else 0
