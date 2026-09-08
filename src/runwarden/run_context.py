"""Per-run execution context.

A probe compares two runs, A and B, that the environment claims are isolated
from each other. Everything a run is allowed to see is described here: its own
working directory, its own temp directory, and a scrubbed environment.

Every read and write an adapter performs against a shared surface goes through
RunContext.exec or RunContext.python, so it happens in a child process carrying
that run's scrubbed environment and working directory. An adapter that reached
the surface directly from the parent process would be probing the parent, not
the run, and the A/B isolation claim would be a fiction.
"""

from __future__ import annotations

import os
import secrets
import subprocess
import sys
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

# Long enough for a local git clone on a slow box, short enough that a hung
# command fails the probe instead of hanging CI forever.
DEFAULT_TIMEOUT_SECONDS = 30.0

RUN_ID_HEX_CHARS = 12

# The only environment variables a run receives. Everything else from the parent
# process is dropped, so an inherited variable cannot become the carrier that a
# surface adapter is being tested for.
ALLOWED_ENV_KEYS = ("PATH", "HOME", "TMPDIR", "RUNWARDEN_RUN_ID")


class RunExecError(Exception):
    """A command run inside a run context exited non-zero.

    Carries the argv, the return code, and stderr, because an adapter failure
    has to produce an ERROR finding with a usable detail string, never a bare
    traceback with the cause thrown away.
    """

    def __init__(self, argv: Sequence[str], returncode: int, stderr: bytes) -> None:
        self.argv = list(argv)
        self.returncode = returncode
        self.stderr = stderr
        printable = stderr.decode("utf-8", errors="replace").strip()
        message = f"command exited {returncode}: {' '.join(self.argv)}"
        if printable:
            message = f"{message}\n{printable}"
        super().__init__(message)


def generate_run_id() -> str:
    """Return a fresh run id as 12 lowercase hex characters."""
    return secrets.token_hex(RUN_ID_HEX_CHARS // 2)


@dataclass(frozen=True)
class RunContext:
    """One side of a probe pair.

    NOTE ON TRUST: RUNWARDEN_RUN_ID in `env` is an environment variable that the
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

    def exec(
        self,
        argv: Sequence[str],
        *,
        input: bytes | None = None,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
        check: bool = True,
    ) -> subprocess.CompletedProcess[bytes]:
        """Run a command as this run: this run's cwd, this run's scrubbed env.

        No shell, ever. argv is passed through as a list, so a nonce that
        happens to contain shell metacharacters cannot become an injection, and
        a surface cannot be reached through a shell builtin that the probe never
        accounted for. stdin is closed unless `input` is given, so a command
        that decides to prompt fails instead of blocking on the parent terminal.
        """
        argv = [str(a) for a in argv]
        completed = subprocess.run(
            argv,
            cwd=self.workdir,
            env=self.env,
            input=input,
            stdin=None if input is not None else subprocess.DEVNULL,
            capture_output=True,
            shell=False,
            timeout=timeout,
        )
        if check and completed.returncode != 0:
            raise RunExecError(argv, completed.returncode, completed.stderr)
        return completed

    def python(
        self,
        code: str,
        *,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
        check: bool = True,
    ) -> subprocess.CompletedProcess[bytes]:
        """Run a snippet of Python as this run.

        Filesystem carriers need operations with no portable command line tool
        behind them, xattrs on this box being the example, so they run through
        the interpreter rather than through a shell one liner.
        """
        return self.exec([sys.executable, "-c", code], timeout=timeout, check=check)


def _scrubbed_env(run_id: str, workdir: Path, tmpdir: Path) -> dict[str, str]:
    """Build the environment for one run.

    PATH is read from the parent because the run needs to find git and python.
    HOME and TMPDIR are redirected into the run's own directories so that a tool
    writing to a default location writes somewhere private to this run.

    These four keys are exactly what a child process receives. A child that is
    itself a Python interpreter will then add LC_CTYPE to its own environment
    (PEP 538 locale coercion). That variable is generated by the interpreter
    from nothing, not inherited from the parent, so it is not a carrier.
    """
    return {
        "PATH": os.environ.get("PATH", ""),
        "HOME": str(workdir),
        "TMPDIR": str(tmpdir),
        "RUNWARDEN_RUN_ID": run_id,
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
