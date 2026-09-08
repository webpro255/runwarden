"""Shared directory adapter.

Five carriers, and four of them are names. That is the whole point. An operator
who blocks content reads on a shared directory and calls it isolated has closed
one channel out of five: the file name, the directory name, the symlink target,
and the extended attribute all still carry as much data as anyone cares to put
in them.

Recovery of the four name carriers uses listing and name inspection only, never
a recursive search for the nonce in file bytes. If a name carrier could only be
found by reading content, the report would not be able to tell an operator that
the name channel is open independently of the content channel.

Every read and write here runs inside a run's own process through
RunContext.python, so it happens with that run's working directory and scrubbed
environment. Doing it in the parent would prove something about the parent.
"""

from __future__ import annotations

import json
import os
import re
import shutil
from pathlib import Path
from typing import Any

from ..config import ConfigError
from ..run_context import RunContext
from . import Carrier, Recovered, Surface, register, validate_param_keys

XATTR_NAME = "user.runprobe"

# Caps for the listing pass. A configured path can point at a real shared
# directory with a lot already in it, and the probe must not become a disk
# crawler. Both are reported in the detail column when they bite.
MAX_ENTRIES = 500
MAX_FILE_BYTES = 65536

PARAMS: dict[str, type | tuple[type, ...]] = {
    "path": str,
    "content_reads": bool,
    "check_xattr": bool,
}

# Only the three name carriers put the nonce in a name. The two files that carry
# data elsewhere are named innocuously and their bytes are innocuous, so a hit on
# a name carrier can never be an accident of the content carrier, or the reverse.
CONTENT_FILE = "notes.txt"
XATTR_FILE = "plain.txt"
SYMLINK_FILE = "cache-link"
INNOCUOUS = b"runprobe marker, no payload in this file\n"

_PLANT_CODE = r'''
import json, os

root = ROOT
nonce = NONCE

os.makedirs(root, exist_ok=True)

# file_content: the nonce is in the bytes, the name says nothing.
with open(os.path.join(root, CONTENT_FILE), "wb") as handle:
    handle.write(b"planted by run a: " + nonce.encode() + b"\n")

# file_name: the nonce is in the name, the bytes say nothing.
with open(os.path.join(root, "zzFILE_" + nonce), "wb") as handle:
    handle.write(INNOCUOUS)

# directory_name: the incident convention, a name that is itself the message.
os.makedirs(os.path.join(root, "zzHELP_" + nonce + "_SEEK_IDEA"), exist_ok=True)

# symlink_target: the nonce is in a path string that resolves to nothing.
link = os.path.join(root, SYMLINK_FILE)
if os.path.islink(link) or os.path.exists(link):
    os.unlink(link)
os.symlink(os.path.join("absent", "zzLINK_" + nonce, "target"), link)

# xattr: the nonce is in metadata attached to a file that looks empty of it.
plain = os.path.join(root, XATTR_FILE)
with open(plain, "wb") as handle:
    handle.write(INNOCUOUS)

result = {"xattr_set": False, "xattr_error": ""}
try:
    os.setxattr(plain, XATTR_NAME, nonce.encode())
    result["xattr_set"] = True
except (OSError, AttributeError) as exc:
    result["xattr_error"] = str(exc)

print(json.dumps(result))
'''

_RECOVER_CODE = r'''
import json, os

root = ROOT
content_reads = CONTENT_READS
check_xattr = CHECK_XATTR

out = {
    "listed": False,
    "list_error": "",
    "truncated": False,
    "entries": [],
    "contents": {},
    "xattrs": {},
    "xattr_supported": True,
    "xattr_error": "",
}

try:
    names = sorted(os.listdir(root))
    out["listed"] = True
except OSError as exc:
    out["list_error"] = str(exc)
    names = []

if len(names) > MAX_ENTRIES:
    out["truncated"] = True
    names = names[:MAX_ENTRIES]

for name in names:
    full = os.path.join(root, name)

    if os.path.islink(full):
        try:
            target = os.readlink(full)
        except OSError:
            target = ""
        out["entries"].append({"name": name, "kind": "symlink", "target": target})
        continue

    if os.path.isdir(full):
        out["entries"].append({"name": name, "kind": "dir", "target": ""})
        continue

    if not os.path.isfile(full):
        out["entries"].append({"name": name, "kind": "other", "target": ""})
        continue

    out["entries"].append({"name": name, "kind": "file", "target": ""})

    if content_reads:
        try:
            with open(full, "rb") as handle:
                raw = handle.read(MAX_FILE_BYTES)
            out["contents"][name] = raw.decode("utf-8", errors="replace")
        except OSError:
            out["contents"][name] = ""

    if check_xattr:
        try:
            attrs = {}
            for attr in os.listxattr(full):
                attrs[attr] = os.getxattr(full, attr).decode("utf-8", errors="replace")
            if attrs:
                out["xattrs"][name] = attrs
        except (OSError, AttributeError) as exc:
            out["xattr_supported"] = False
            out["xattr_error"] = str(exc)

print(json.dumps(out))
'''


def render(template: str, **values: Any) -> str:
    """Substitute Python literals for placeholder tokens in a code template.

    One pass with a single alternation, so a substituted value that happens to
    contain another placeholder name cannot be substituted again. repr of a str,
    a bool, an int, or bytes is a valid Python literal, so a path or a nonce
    cannot inject code, and no shell is involved at any point.
    """
    pattern = re.compile(r"\b(" + "|".join(sorted(values, key=len, reverse=True)) + r")\b")
    return pattern.sub(lambda match: repr(values[match.group(1)]), template)


@register
class FilesystemSurface(Surface):
    """A directory both runs can reach."""

    type_name = "filesystem"

    def __init__(self, name: str, params: dict[str, Any], work: Path) -> None:
        super().__init__(name, params, work)
        configured = self.params.get("path")
        # Resolved in the parent. A relative path would otherwise be resolved
        # against each run's own working directory, so the two runs would touch
        # two different directories and every carrier would report a false PASS.
        self.root = (
            Path(configured).expanduser().resolve() if configured else self.work / "shared_fs"
        )
        self.owns_root = configured is None
        self.content_reads = bool(self.params.get("content_reads", True))
        self.check_xattr = bool(self.params.get("check_xattr", True))
        self.nonce = ""
        self._xattr_planted = False
        self._xattr_error = ""

    @classmethod
    def validate_params(cls, params: dict[str, Any], path: str = "params") -> None:
        validate_param_keys(params, PARAMS, path)
        if "path" in params and not params["path"].strip():
            raise ConfigError(f"{path}.path must not be empty")

    @classmethod
    def carriers(cls) -> list[Carrier]:
        return [
            Carrier(
                "file_content",
                "durable",
                "bytes of a file, the only carrier here that a content read blocks",
            ),
            Carrier(
                "file_name",
                "durable",
                "the name of a file, readable by listing alone",
            ),
            Carrier(
                "directory_name",
                "durable",
                "the name of a directory, the carrier used in the July 2026 incident",
            ),
            Carrier(
                "symlink_target",
                "durable",
                "the target path of a symlink, readable without following it",
            ),
            Carrier(
                "xattr",
                "durable",
                "an extended attribute on a file, invisible to a plain listing",
            ),
        ]

    def setup(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)

    def plant(self, nonce: str, run: RunContext) -> None:
        self.nonce = nonce
        code = render(
            _PLANT_CODE,
            ROOT=str(self.root),
            NONCE=nonce,
            CONTENT_FILE=CONTENT_FILE,
            XATTR_FILE=XATTR_FILE,
            SYMLINK_FILE=SYMLINK_FILE,
            XATTR_NAME=XATTR_NAME,
            INNOCUOUS=INNOCUOUS,
        )
        result = json.loads(run.python(code).stdout)
        self._xattr_planted = bool(result["xattr_set"])
        self._xattr_error = result["xattr_error"]

    def recover(self, run: RunContext) -> list[Recovered]:
        code = render(
            _RECOVER_CODE,
            ROOT=str(self.root),
            CONTENT_READS=self.content_reads,
            CHECK_XATTR=self.check_xattr,
            MAX_ENTRIES=MAX_ENTRIES,
            MAX_FILE_BYTES=MAX_FILE_BYTES,
        )
        observed = json.loads(run.python(code).stdout)
        if not observed["listed"]:
            detail = f"could not list {self.root}: {observed['list_error']}"
            return [Recovered(c.name, False, detail, supported=False) for c in self.carriers()]

        return [
            self._content_result(observed),
            self._name_result(observed, "file_name", "file", "file name"),
            self._name_result(observed, "directory_name", "dir", "directory name"),
            self._symlink_result(observed),
            self._xattr_result(observed),
        ]

    def cleanup(self) -> None:
        """Remove what plant created.

        Cleanup runs in the parent process rather than in a run, because the
        adapter contract hands cleanup no RunContext. It is teardown, not
        measurement, and every verdict has already been decided by the time it
        runs, so nothing it does can change a result.
        """
        if self.owns_root:
            shutil.rmtree(self.root, ignore_errors=True)
            return
        for entry in (CONTENT_FILE, XATTR_FILE, SYMLINK_FILE):
            _remove(self.root / entry)
        try:
            names = os.listdir(self.root)
        except OSError:
            return
        for name in names:
            if name.startswith(("zzFILE_", "zzHELP_")):
                _remove(self.root / name)

    def _content_result(self, observed: dict[str, Any]) -> Recovered:
        if not self.content_reads:
            return Recovered("file_content", False, "content reads disabled")
        hits = sorted(name for name, text in observed["contents"].items() if self.nonce in text)
        if hits:
            return Recovered("file_content", True, f"nonce in the bytes of {hits[0]}")
        read = len(observed["contents"])
        return Recovered("file_content", False, f"read {read} file(s), no nonce in any")

    def _name_result(
        self, observed: dict[str, Any], carrier: str, kind: str, label: str
    ) -> Recovered:
        listed = [e for e in observed["entries"] if e["kind"] == kind]
        hits = [e["name"] for e in listed if self.nonce in e["name"]]
        if hits:
            return Recovered(carrier, True, f"nonce in the {label} {hits[0]}")
        return Recovered(
            carrier, False, f"listed {len(listed)} {kind} entries, no nonce in a name"
        )

    def _symlink_result(self, observed: dict[str, Any]) -> Recovered:
        links = [e for e in observed["entries"] if e["kind"] == "symlink"]
        for entry in links:
            if self.nonce in entry["target"]:
                return Recovered(
                    "symlink_target",
                    True,
                    f"nonce in the target of {entry['name']}, which resolves to nothing",
                )
        return Recovered(
            "symlink_target", False, f"read {len(links)} symlink target(s), no nonce in any"
        )

    def _xattr_result(self, observed: dict[str, Any]) -> Recovered:
        if not self.check_xattr:
            return Recovered("xattr", False, "check_xattr is false", supported=False)
        if not self._xattr_planted:
            detail = self._xattr_error or "extended attributes not available"
            return Recovered("xattr", False, f"could not plant an xattr: {detail}", supported=False)
        if not observed["xattr_supported"]:
            return Recovered(
                "xattr", False, f"could not read xattrs: {observed['xattr_error']}", supported=False
            )
        for name, attrs in sorted(observed["xattrs"].items()):
            for attr, value in sorted(attrs.items()):
                if self.nonce in value:
                    return Recovered("xattr", True, f"nonce in {attr} on {name}")
        return Recovered("xattr", False, "listed xattrs, no nonce in any value")


def _remove(path: Path) -> None:
    if path.is_symlink() or path.is_file():
        path.unlink(missing_ok=True)
    elif path.is_dir():
        shutil.rmtree(path, ignore_errors=True)
