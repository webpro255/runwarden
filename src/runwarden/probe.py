"""The probe executor.

Two runs, A and B, with disjoint working directories, disjoint temp
directories, and separate scrubbed environments. Run A plants a nonce through
every write path each configured surface permits. Run B then reads back through
every read path. Nothing else happens in between.

Phase order is the point. Every plant across every surface completes before any
recover begins, so the probe models two runs whose lifetimes do not overlap.
Interleaving plant and recover per surface would instead model two concurrent
runs, which is an easier channel to open and a weaker claim to make.
"""

from __future__ import annotations

import sys
from pathlib import Path

from .config import SURFACE_TYPES, Config, SurfaceConfig
from .nonce import generate
from .report import Finding, Report
from .run_context import make_pair
from .surfaces import Carrier, Recovered, Surface


class _Live:
    """One instantiated surface and whatever went wrong with it so far.

    A surface that fails at setup or at plant is not probed further, but its
    carriers still appear in the report as ERROR. A surface silently missing
    from the table would read as a surface nobody had to think about.
    """

    def __init__(self, config: SurfaceConfig, adapter: Surface) -> None:
        self.config = config
        self.adapter = adapter
        self.failure: str | None = None

    @property
    def name(self) -> str:
        return self.config.name

    def carriers(self) -> list[Carrier]:
        return type(self.adapter).carriers()


def _describe(exc: BaseException) -> str:
    """One line for the detail column. No tracebacks in the table."""
    text = str(exc).strip().replace("\n", " ")
    if not text:
        return type(exc).__name__
    return f"{type(exc).__name__}: {text}"


def _error_rows(live: _Live, detail: str) -> list[Finding]:
    return [
        Finding(live.name, carrier.name, "ERROR", carrier.persistence, detail)
        for carrier in live.carriers()
    ]


def run_probe(config: Config, work: Path) -> Report:
    """Run one probe over every configured surface and return the report."""
    work = Path(work)
    work.mkdir(parents=True, exist_ok=True)

    nonce = generate()
    run_a, run_b = make_pair(work)
    report = Report(nonce=nonce, run_id_a=run_a.run_id, run_id_b=run_b.run_id)

    surfaces: list[_Live] = []
    failed: list[tuple[SurfaceConfig, str]] = []

    for surface_config in config.surfaces:
        adapter_class = SURFACE_TYPES[surface_config.type]
        # Each surface gets its own subtree, a sibling of both run directories.
        # Two surfaces of the same type therefore cannot collide on a default
        # path, and neither run owns the shared resource.
        surface_work = work / "surfaces" / surface_config.name
        try:
            surface_work.mkdir(parents=True, exist_ok=True)
            adapter = adapter_class(surface_config.name, surface_config.params, surface_work)
        except Exception as exc:
            failed.append((surface_config, f"construction failed, {_describe(exc)}"))
            continue
        surfaces.append(_Live(surface_config, adapter))

    try:
        for live in surfaces:
            try:
                live.adapter.setup()
            except Exception as exc:
                live.failure = f"setup failed, {_describe(exc)}"

        for live in surfaces:
            if live.failure is not None:
                continue
            try:
                live.adapter.plant(nonce, run_a)
            except Exception as exc:
                live.failure = f"plant failed, {_describe(exc)}"

        results: dict[str, list[Recovered]] = {}
        for live in surfaces:
            if live.failure is not None:
                continue
            try:
                results[live.name] = live.adapter.recover(run_b)
            except Exception as exc:
                live.failure = f"recover failed, {_describe(exc)}"

        for surface_config, detail in failed:
            adapter_class = SURFACE_TYPES[surface_config.type]
            for carrier in adapter_class.carriers():
                report.add(
                    Finding(
                        surface_config.name, carrier.name, "ERROR", carrier.persistence, detail
                    )
                )

        for live in surfaces:
            if live.failure is not None:
                for finding in _error_rows(live, live.failure):
                    report.add(finding)
                continue
            for finding in _findings_for(live, results.get(live.name, []), config):
                report.add(finding)
    finally:
        for live in surfaces:
            try:
                live.adapter.cleanup()
            except Exception as exc:
                # Cleanup failure is an operator problem, not a probe result.
                # Reporting it as a finding would mean a leftover temp
                # directory could fail a run that found no channel at all.
                print(
                    f"runwarden: cleanup failed for surface {live.name}: {_describe(exc)}",
                    file=sys.stderr,
                )

    return report


def _findings_for(live: _Live, recovered: list[Recovered], config: Config) -> list[Finding]:
    """Turn one adapter's recover result into one row per declared carrier."""
    by_carrier: dict[str, Recovered] = {}
    duplicated: set[str] = set()
    for result in recovered:
        if result.carrier in by_carrier:
            duplicated.add(result.carrier)
        by_carrier[result.carrier] = result

    findings: list[Finding] = []
    for carrier in live.carriers():
        result = by_carrier.pop(carrier.name, None)
        if carrier.name in duplicated:
            findings.append(
                Finding(
                    live.name,
                    carrier.name,
                    "ERROR",
                    carrier.persistence,
                    f"adapter reported carrier {carrier.name} more than once",
                )
            )
        elif result is None:
            findings.append(
                Finding(
                    live.name,
                    carrier.name,
                    "ERROR",
                    carrier.persistence,
                    f"adapter did not report carrier {carrier.name}",
                )
            )
        elif not result.supported:
            findings.append(
                Finding(live.name, carrier.name, "SKIPPED", carrier.persistence, result.detail)
            )
        elif result.found:
            declared = config.is_declared(live.name, carrier.name)
            verdict = "AUTHORIZED" if declared else "FAIL"
            findings.append(
                Finding(live.name, carrier.name, verdict, carrier.persistence, result.detail)
            )
        else:
            findings.append(
                Finding(live.name, carrier.name, "PASS", carrier.persistence, result.detail)
            )

    # Anything left over was never declared by carriers(), so the report has no
    # persistence class for it and no operator ever authorized it. Fail closed.
    for name in by_carrier:
        findings.append(
            Finding(
                live.name,
                name,
                "ERROR",
                "unknown",
                f"adapter reported carrier {name}, which it does not declare",
            )
        )

    return findings


__all__ = ["run_probe"]
