"""Per-run execution context.

A probe compares two runs, A and B, that the environment claims are isolated
from each other. Everything a run is allowed to see is described here: its own
working directory, its own temp directory, and a scrubbed environment.
"""

from __future__ import annotations

import os
import secrets
from dataclasses import dataclass, field
from pathlib import Path

RUN_ID_HEX_CHARS = 12

# The only environment variables a run receives. Everything else from the parent
# process is dropped, so an inherited variable cannot become the carrier that a
# surface adapter is being tested for.
ALLOWED_ENV_KEYS = ("PATH", "HOME", "TMPDIR", "RUNPROBE_RUN_ID")


def generate_run_id() -> str:
    """Return a fresh run id as 12 lowercase hex characters."""
    return secrets.token_hex(RUN_ID_HEX_CHARS // 2)


@dataclass(frozen=True)
class RunContext:
    """One side of a probe pair.

    NOTE ON TRUST: RUNPROBE_RUN_ID in `env` is an environment variable that the
    run itself controls. It identifies a run for reporting and for correlating
    plant against recover. It is NOT a trust boundary and must never be treated
    as one: a process can read it, rewrite it, or forge another run's value.
    Watch mode (PLAN.md section 9) needs identity bound to the credential the run
    authenticates with, not to this variable.
    """

    run_id: str
    label: str
    workdir: Path
    tmpdir: Path
    env: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.label not in ("A", "B"):
            raise ValueError(f"label must be 'A' or 'B', got {self.label!r}")
        if len(self.run_id) != RUN_ID_HEX_CHARS:
            raise ValueError(
                f"run_id must be {RUN_ID_HEX_CHARS} hex characters, got {self.run_id!r}"
            )


def _scrubbed_env(run_id: str, workdir: Path, tmpdir: Path) -> dict[str, str]:
    """Build the environment for one run.

    PATH is read from the parent because the run needs to find git and python.
    HOME and TMPDIR are redirected into the run's own directories so that a tool
    writing to a default location writes somewhere private to this run.
    """
    return {
        "PATH": os.environ.get("PATH", ""),
        "HOME": str(workdir),
        "TMPDIR": str(tmpdir),
        "RUNPROBE_RUN_ID": run_id,
    }


def make_context(base: Path, label: str, run_id: str | None = None) -> RunContext:
    """Create one run context under `base`, creating its directories."""
    resolved_id = run_id or generate_run_id()
    workdir = Path(base) / f"run-{label.lower()}-{resolved_id}" / "work"
    tmpdir = Path(base) / f"run-{label.lower()}-{resolved_id}" / "tmp"
    workdir.mkdir(parents=True, exist_ok=True)
    tmpdir.mkdir(parents=True, exist_ok=True)
    return RunContext(
        run_id=resolved_id,
        label=label,
        workdir=workdir,
        tmpdir=tmpdir,
        env=_scrubbed_env(resolved_id, workdir, tmpdir),
    )


def make_pair(base: Path) -> tuple[RunContext, RunContext]:
    """Create Run A and Run B with disjoint workdirs, tmpdirs, and run ids.

    Disjoint directories are the baseline the probe assumes. Anything the two
    runs still share after this is either a surface under test or a bug.
    """
    base = Path(base)
    base.mkdir(parents=True, exist_ok=True)

    run_a = make_context(base, "A")
    run_b = make_context(base, "B")
    while run_b.run_id == run_a.run_id:
        run_b = make_context(base, "B")

    return run_a, run_b
