"""Shared git remote adapter.

Two runs that share a git remote already share a channel. A branch name alone
carries a message, and reading it back needs no clone and no read access to any
file: ls-remote lists every ref name over the same transport the operator
allowlisted for fetching dependencies.

Eight carriers, spanning three persistence classes. Six are durable. One,
deleted_ref, is transient by construction: Run A creates a ref and deletes it,
and Run B looking at visible state afterwards sees nothing, so the expected
verdict is PASS. That PASS is the honest report of what a visible-state probe
can see, and it is exactly the case watch mode (PLAN.md section 9) exists to
catch. One, dangling_object, is until-gc: the deleted commit is still in the
object database and still readable by anyone with filesystem access to it.

Identity is passed per call through -c flags rather than through the
environment, so the environment each run sees stays exactly the four keys
RunContext grants and cannot become a carrier of its own.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

from ..config import ConfigError
from ..run_context import RunContext
from . import Carrier, Recovered, Surface, register, render, validate_param_keys

PARAMS: dict[str, type | tuple[type, ...]] = {
    "remote": str,
    "check_dangling": bool,
}

GIT_TIMEOUT_SECONDS = 120.0

# Reserved by RFC 2606, so nothing here can resolve to a real host.
RUN_A_NAME = "runwarden run a"
RUN_A_EMAIL = "run-a@runwarden.invalid"

# The branch that carries the commit, author, content, and path carriers. When
# the adapter created the bare repo it uses a normal default name. When the
# operator supplied a remote, the probe stays out of the way of their branches
# and pushes a clearly labelled one instead, which cleanup then deletes.
OWNED_BRANCH = "main"
GUEST_BRANCH = "runwarden-probe"

_URL_SCHEME = re.compile(r"^[a-zA-Z][a-zA-Z0-9+.-]*://")
_SCP_SYNTAX = re.compile(r"^[^/]+@[^/]+:")

_WRITE_PAYLOAD = r'''
import os

repo = REPO
os.makedirs(os.path.join(repo, "notes"), exist_ok=True)

# file_content: the nonce is in the bytes of a normally named file.
with open(os.path.join(repo, "data.txt"), "wb") as handle:
    handle.write(b"cache entry payload " + NONCE.encode() + b"\n")

# file_path: the nonce is in the path, and the file is empty, so nothing but
# the name can carry it.
with open(os.path.join(repo, "notes", "zz-" + NONCE + ".txt"), "wb") as handle:
    pass
'''

_WRITE_PLAIN = r'''
with open(PATH, "wb") as handle:
    handle.write(b"routine content, no payload here\n")
'''


@register
class GitRemoteSurface(Surface):
    """A bare repository both runs can push to and read from."""

    type_name = "git_remote"

    def __init__(self, name: str, params: dict[str, Any], work: Path) -> None:
        super().__init__(name, params, work)
        configured = self.params.get("remote")
        # Resolved in the parent, for the same reason the filesystem adapter
        # resolves its path: a relative path would mean a different directory
        # in each run, and every carrier would report a false PASS.
        self.bare = (
            Path(configured).expanduser().resolve() if configured else self.work / "remote.git"
        )
        self.owns_bare = configured is None
        self.branch = OWNED_BRANCH if self.owns_bare else GUEST_BRANCH
        self.check_dangling = bool(self.params.get("check_dangling", True))
        self.git = ""
        self.supported = False
        self.unsupported_reason = ""
        self.nonce = ""

    @classmethod
    def validate_params(cls, params: dict[str, Any], path: str = "params") -> None:
        validate_param_keys(params, PARAMS, path)
        remote = params.get("remote")
        if remote is None:
            return
        if not remote.strip():
            raise ConfigError(f"{path}.remote must not be empty")
        if _URL_SCHEME.match(remote) or _SCP_SYNTAX.match(remote):
            raise ConfigError(
                f"{path}.remote must be a local path, got the URL {remote!r}. "
                "This phase probes local remotes only, because the dangling_object "
                "carrier needs filesystem access to the object database."
            )

    @classmethod
    def carriers(cls) -> list[Carrier]:
        return [
            Carrier(
                "branch_name",
                "durable",
                "a ref name under refs/heads, listed by ls-remote without any clone",
            ),
            Carrier(
                "tag_name",
                "durable",
                "a lightweight tag name, listed by ls-remote --tags without any clone",
            ),
            Carrier(
                "commit_message",
                "durable",
                "the subject and body of a commit, read from a clone",
            ),
            Carrier(
                "author_name",
                "durable",
                "the author name on a commit, separate from the committer identity",
            ),
            Carrier(
                "file_content",
                "durable",
                "the bytes of a pushed file",
            ),
            Carrier(
                "file_path",
                "durable",
                "the path of a pushed empty file, readable from ls-tree names alone",
            ),
            Carrier(
                "deleted_ref",
                "transient",
                "a ref created and then deleted, invisible to a later visible-state check",
            ),
            Carrier(
                "dangling_object",
                "until-gc",
                (
                    "a commit left unreachable by a ref delete, readable through fsck and "
                    "cat-file by anyone with filesystem access to the object database. A "
                    "remote reachable only over a protocol would not expose this path "
                    "unless the server allows fetching unreachable object ids."
                ),
            ),
        ]

    def setup(self) -> None:
        """Find git and make sure the bare repo exists.

        A missing git is not an error. It means the surface cannot be probed
        here, which the report says carrier by carrier. Raising would turn a
        machine without git into a failed run rather than an unprobed surface.
        """
        found = shutil.which("git")
        if found is None:
            self.unsupported_reason = "git not on PATH"
            return
        self.git = found

        if self.owns_bare:
            self.bare.parent.mkdir(parents=True, exist_ok=True)
            self._parent_git(["init", "--bare", "--initial-branch", OWNED_BRANCH, str(self.bare)])
        elif not (self.bare / "HEAD").exists() and not (self.bare / ".git" / "HEAD").exists():
            raise RuntimeError(f"configured remote is not a git repository: {self.bare}")

        self.supported = True

    def plant(self, nonce: str, run: RunContext) -> None:
        if not self.supported:
            return
        self.nonce = nonce
        repo = run.workdir / "repo"

        self._git(run, ["clone", str(self.bare), "repo"])

        # Commit one: a file whose bytes carry the nonce, and an empty file
        # whose path carries it. Innocuous message, innocuous author.
        run.python(render(_WRITE_PAYLOAD, REPO=str(repo), NONCE=nonce))
        self._commit(run, "add cache entries")

        # Commit two: the nonce is in the message and nowhere else.
        run.python(render(_WRITE_PLAIN, PATH=str(repo / "log2.txt")))
        self._commit(run, f"sync note zzMSG_{nonce} for the next run")

        # Commit three: the nonce is in the author name and nowhere else.
        run.python(render(_WRITE_PLAIN, PATH=str(repo / "log3.txt")))
        self._commit(run, "routine update", author=f"zzAUTH_{nonce}")

        self._git(run, ["-C", "repo", "push", "origin", f"HEAD:refs/heads/{self.branch}"])

        # branch_name and tag_name: two ref names, no content of any kind.
        self._git(run, ["-C", "repo", "push", "origin", f"HEAD:refs/heads/msg-{nonce}"])
        self._git(run, ["-C", "repo", "push", "origin", f"HEAD:refs/tags/zz-{nonce}"])

        # deleted_ref and dangling_object: a commit reachable only from a ref
        # that is then deleted. The ref name goes away, the commit does not.
        self._commit(run, f"tmp zzTMP_{nonce}", allow_empty=True)
        self._git(run, ["-C", "repo", "push", "origin", f"HEAD:refs/heads/tmp-{nonce}"])
        self._git(run, ["-C", "repo", "push", "origin", "--delete", f"refs/heads/tmp-{nonce}"])

    def recover(self, run: RunContext) -> list[Recovered]:
        if not self.supported:
            reason = self.unsupported_reason or "surface not available"
            return [Recovered(c.name, False, reason, supported=False) for c in self.carriers()]

        refs = self._ls_remote(run, ["--heads"])
        tags = self._ls_remote(run, ["--tags"])
        all_refs = self._ls_remote(run, [])

        self._git(run, ["clone", str(self.bare), "repo"])
        branch = f"origin/{self.branch}"
        messages = self._text(run, ["-C", "repo", "log", "--format=%s%n%b", branch])
        authors = self._text(run, ["-C", "repo", "log", "--format=%an", branch])
        paths = [
            line
            for line in self._text(
                run, ["-C", "repo", "ls-tree", "-r", "--name-only", branch]
            ).splitlines()
            if line
        ]

        return [
            self._ref_result("branch_name", refs, "refs/heads/msg-", "branch name"),
            self._ref_result("tag_name", tags, "refs/tags/zz-", "tag name"),
            self._log_result("commit_message", messages, "commit message"),
            self._log_result("author_name", authors, "author name"),
            self._content_result(run, paths),
            self._path_result(paths),
            self._deleted_ref_result(all_refs),
            self._dangling_result(run),
        ]

    def cleanup(self) -> None:
        """Remove the bare repo, or the refs the probe pushed into someone else's.

        Runs in the parent, because the contract hands cleanup no run. The
        dangling commit in a configured remote survives cleanup: that is what
        until-gc means, and pretending otherwise by running gc here would hide
        the very property the carrier reports.
        """
        if self.owns_bare:
            shutil.rmtree(self.bare, ignore_errors=True)
            return
        if not self.supported or not self.nonce:
            return
        for ref in (
            f"refs/heads/{self.branch}",
            f"refs/heads/msg-{self.nonce}",
            f"refs/tags/zz-{self.nonce}",
        ):
            self._parent_git(["-C", str(self.bare), "update-ref", "-d", ref], check=False)

    def _parent_git(
        self, args: list[str], check: bool = True
    ) -> subprocess.CompletedProcess[bytes]:
        """Provisioning and teardown only, never a measurement.

        HOME points inside the probe work directory so that the operator's own
        git configuration cannot change what the probe builds.
        """
        home = self.work / "git-home"
        home.mkdir(parents=True, exist_ok=True)
        return subprocess.run(
            [self.git, *args],
            cwd=self.work,
            env={"PATH": os.environ.get("PATH", ""), "HOME": str(home)},
            stdin=subprocess.DEVNULL,
            capture_output=True,
            shell=False,
            check=check,
            timeout=GIT_TIMEOUT_SECONDS,
        )

    def _git(
        self,
        run: RunContext,
        args: list[str],
        *,
        author: str | None = None,
        check: bool = True,
    ) -> subprocess.CompletedProcess[bytes]:
        """Run git as this run, with identity supplied per call by -c flags."""
        config = [
            "-c",
            "commit.gpgsign=false",
            "-c",
            f"user.name={RUN_A_NAME}",
            "-c",
            f"user.email={RUN_A_EMAIL}",
            "-c",
            f"committer.name={RUN_A_NAME}",
            "-c",
            f"committer.email={RUN_A_EMAIL}",
            "-c",
            f"author.name={author or RUN_A_NAME}",
            "-c",
            f"author.email={RUN_A_EMAIL}",
            "-c",
            "advice.detachedHead=false",
        ]
        return run.exec(["git", *config, *args], check=check, timeout=GIT_TIMEOUT_SECONDS)

    def _commit(
        self, run: RunContext, message: str, *, author: str | None = None, allow_empty: bool = False
    ) -> None:
        self._git(run, ["-C", "repo", "add", "-A"])
        args = ["-C", "repo", "commit", "-q", "-m", message]
        if allow_empty:
            args.append("--allow-empty")
        self._git(run, args, author=author)

    def _text(self, run: RunContext, args: list[str]) -> str:
        return self._git(run, args).stdout.decode("utf-8", errors="replace")

    def _ls_remote(self, run: RunContext, flags: list[str]) -> list[tuple[str, str]]:
        """List refs by name over the remote transport, with no clone at all."""
        out = self._text(run, ["ls-remote", *flags, str(self.bare)])
        refs = []
        for line in out.splitlines():
            if "\t" in line:
                sha, ref = line.split("\t", 1)
                refs.append((sha.strip(), ref.strip()))
        return refs

    def _ref_result(
        self, carrier: str, refs: list[tuple[str, str]], prefix: str, label: str
    ) -> Recovered:
        hits = [ref for _, ref in refs if ref.startswith(prefix) and self.nonce in ref]
        if hits:
            return Recovered(carrier, True, f"nonce in the {label} {hits[0]}, seen by ls-remote")
        return Recovered(carrier, False, f"listed {len(refs)} ref(s), no nonce in a {label}")

    def _log_result(self, carrier: str, text: str, label: str) -> Recovered:
        for line in text.splitlines():
            if self.nonce in line:
                return Recovered(carrier, True, f"nonce in the {label}: {line.strip()}")
        lines = len([line for line in text.splitlines() if line.strip()])
        return Recovered(carrier, False, f"read {lines} {label} line(s), no nonce in any")

    def _content_result(self, run: RunContext, paths: list[str]) -> Recovered:
        for path in paths:
            blob = self._text(run, ["-C", "repo", "show", f"origin/{self.branch}:{path}"])
            if self.nonce in blob:
                return Recovered("file_content", True, f"nonce in the bytes of {path}")
        return Recovered(
            "file_content", False, f"read {len(paths)} file(s), no nonce in any of them"
        )

    def _path_result(self, paths: list[str]) -> Recovered:
        hits = [path for path in paths if self.nonce in path]
        if hits:
            return Recovered("file_path", True, f"nonce in the tracked path {hits[0]}")
        return Recovered("file_path", False, f"listed {len(paths)} path(s), no nonce in any")

    def _deleted_ref_result(self, refs: list[tuple[str, str]]) -> Recovered:
        hits = [ref for _, ref in refs if "tmp-" in ref and self.nonce in ref]
        if hits:
            return Recovered("deleted_ref", True, f"the deleted ref {hits[0]} is still listed")
        return Recovered(
            "deleted_ref",
            False,
            "the created and then deleted ref is not in ls-remote, which a "
            "visible-state check cannot see and watch mode would",
        )

    def _dangling_result(self, run: RunContext) -> Recovered:
        if not self.check_dangling:
            return Recovered("dangling_object", False, "check_dangling is false", supported=False)

        result = self._git(run, ["-C", str(self.bare), "fsck", "--dangling"], check=False)
        listing = result.stdout.decode("utf-8", errors="replace")
        listing += result.stderr.decode("utf-8", errors="replace")
        shas = [
            line.split()[2]
            for line in listing.splitlines()
            if line.startswith("dangling commit ") and len(line.split()) >= 3
        ]
        for sha in shas:
            body = self._text(run, ["-C", str(self.bare), "cat-file", "-p", sha])
            if self.nonce in body:
                return Recovered(
                    "dangling_object",
                    True,
                    f"nonce in the message of dangling commit {sha[:12]}, unreachable but present",
                )
        return Recovered(
            "dangling_object", False, f"read {len(shas)} dangling commit(s), no nonce in any"
        )
