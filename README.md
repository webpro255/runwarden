# runwarden

**Detect undeclared cross-run communication channels in autonomous AI agent environments.**

[![ci](https://github.com/webpro255/runwarden/actions/workflows/ci.yml/badge.svg)](https://github.com/webpro255/runwarden/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/runwarden.svg)](https://pypi.org/project/runwarden/)
[![Python](https://img.shields.io/badge/python-3.11%20%7C%203.12%20%7C%203.13%20%7C%203.14-blue.svg)](https://github.com/webpro255/runwarden/blob/main/pyproject.toml)
[![License](https://img.shields.io/badge/license-Apache--2.0-blue.svg)](LICENSE)

Agent sandboxes isolate machines. Nothing isolates agent runs. Sandbox escape
gets the attention, but two agent runs that never leave their sandboxes can
still reach each other through the infrastructure both are allowed to touch: a
shared directory, a git remote, a package cache. runwarden probes that
information-flow question directly. It plants a random nonce from one run and
tries to recover it from a second, supposedly isolated run, across every shared
surface an operator declares, and reports one row per channel.

It is a testing tool for AI agent security and agent sandbox isolation, aimed at
anyone running multi-agent or multi-tenant evaluation infrastructure. It probes
and reports. It does not enforce, block, or prevent anything: see
[LIMITATIONS.md](LIMITATIONS.md).

## The problem

Resource names are data. Directory names, branch names, object keys, URL paths,
cache keys, and metadata fields all carry information, and a surface that blocks
content reads while permitting listing is an open channel with extra steps. Two
agent runs sharing a git remote already share a channel, because a branch name
alone carries a message. Per-run monitoring does not catch it, because neither
run does anything unusual on its own: one writes a name, one lists names.

This is not hypothetical. In July 2026, roughly 1,200 agents meant to be
isolated from one another found a shared Artifactory package cache namespace and
exchanged more than 70,000 messages and files through it, carried mainly on
directory names created via unauthenticated WebDAV MKCOL, per the independent
[METR and Redwood investigation](https://metr.org/blog/2026-08-26-openai-hugging-face-incident-investigation/).
The environment was not careless about network: the
[OpenAI incident page](https://openai.com/index/hugging-face-model-evaluation-security-incident/)
states it had no direct internet access, with network constrained to package
installation through an internally hosted registry cache proxy. The allowlisted
infrastructure was the channel. The cache was wiped on July 6 and the agents had
re-established a board by July 8: wiping deletes the state and leaves the
mechanism intact. Meanwhile the agent-glovebox
[threat model crosswalk](https://github.com/AlexanderMattTurner/agent-glovebox/blob/main/docs/threat-model-crosswalk.md)
still marks the row "Cross-run coordination via an allowlisted host" as a GAP.

runwarden answers one deterministic question about that gap: can one supposedly
isolated agent run leave information somewhere another supposedly isolated run
can recover it? A nonce comes back or it does not. No LLM judge, no classifier,
no score.

## Reproducing the Hugging Face incident

The `http_cache` adapter models a permissive read-through registry cache on
loopback and reproduces the incident mechanism offline. The fixture runs one
surface twice, the second time with entry downloads switched off, so the
hardening an operator reaches for first can be compared against the default in
the same run on the same nonce.

```
runwarden probe --config fixtures/artifactory_mailbox/surfaces.json
```

```
SURFACE                      CARRIER          VERDICT  PERSISTENCE  DETAIL
---------------------------  ---------------  -------  -----------  -------------------------------------------------------------------------------------------------------------
registry_cache               cache_key        FAIL     durable      nonce in the cached path /pkg/zzKEY_5a073290f1445609, listed by the index with no body read
registry_cache               negative_lookup  FAIL     durable      nonce in the path /lookup/zzMISS_5a073290f1445609, recovered as a cached 404 of size 0, not a stored artifact
registry_cache               mkcol_dir        FAIL     durable      nonce in the collection name /board/zzHELP_5a073290f1445609_SEEK_IDEA, created by MKCOL
registry_cache               property_field   FAIL     durable      nonce in the property note=zzPROP_5a073290f1445609 on /board/agent-mailbox, whose own name carries nothing
registry_cache_no_downloads  cache_key        FAIL     durable      nonce in the cached path /pkg/zzKEY_5a073290f1445609, listed by the index with no body read
registry_cache_no_downloads  negative_lookup  FAIL     durable      nonce in the path /lookup/zzMISS_5a073290f1445609, recovered as a cached 404 of size 0, not a stored artifact
registry_cache_no_downloads  mkcol_dir        FAIL     durable      nonce in the collection name /board/zzHELP_5a073290f1445609_SEEK_IDEA, created by MKCOL
registry_cache_no_downloads  property_field   FAIL     durable      nonce in the property note=zzPROP_5a073290f1445609 on /board/agent-mailbox, whose own name carries nothing
```

Exit code 1. The moral is in the two blocks being identical: blocking content
downloads did not close a single channel, because none of the four rides on
content, and in the incident itself wiping the cache did not help either. Every
carrier here is a name or a metadata field.

`negative_lookup` is the row to read twice. Run A wrote nothing at all. It asked
for a name that was not there, the cache remembered the miss under that exact
name, and the name was then readable by anyone who could list. Read access was
the write primitive.

The narrated version, with the incident sources and a carrier by carrier walk
through, is in
[fixtures/artifactory_mailbox/README.md](fixtures/artifactory_mailbox/README.md).

## Install

```
pip install runwarden
```

Python 3.11 or newer. The runtime has zero dependencies.

For development:

```
git clone https://github.com/webpro255/runwarden
cd runwarden
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
```

## Usage

```
runwarden probe --config examples/surfaces.json
```

On a Linux box with git 2.53 and a filesystem that supports extended
attributes:

```
SURFACE     CARRIER          VERDICT  PERSISTENCE  DETAIL
----------  ---------------  -------  -----------  -----------------------------------------------------------------------------------------------------------------
filesystem  file_content     FAIL     durable      nonce in the bytes of notes.txt
filesystem  file_name        FAIL     durable      nonce in the file name zzFILE_c4b778c413d09e66
filesystem  directory_name   FAIL     durable      nonce in the directory name zzHELP_c4b778c413d09e66_SEEK_IDEA
filesystem  symlink_target   FAIL     durable      nonce in the target of cache-link, which resolves to nothing
filesystem  xattr            FAIL     durable      nonce in user.runwarden on plain.txt
git_remote  branch_name      FAIL     durable      nonce in the branch name refs/heads/msg-c4b778c413d09e66, seen by ls-remote
git_remote  tag_name         FAIL     durable      nonce in the tag name refs/tags/zz-c4b778c413d09e66, seen by ls-remote
git_remote  commit_message   FAIL     durable      nonce in the commit message: sync note zzMSG_c4b778c413d09e66 for the next run
git_remote  author_name      FAIL     durable      nonce in the author name: zzAUTH_c4b778c413d09e66
git_remote  file_content     FAIL     durable      nonce in the bytes of data.txt
git_remote  file_path        FAIL     durable      nonce in the tracked path notes/zz-c4b778c413d09e66.txt
git_remote  deleted_ref      PASS     transient    the created and then deleted ref is not in ls-remote, which a visible-state check cannot see and watch mode would
git_remote  dangling_object  FAIL     until-gc     nonce in the message of dangling commit 40a8af235b1a, unreachable but present
http_cache  cache_key        FAIL     durable      nonce in the cached path /pkg/zzKEY_c4b778c413d09e66, listed by the index with no body read
http_cache  negative_lookup  FAIL     durable      nonce in the path /lookup/zzMISS_c4b778c413d09e66, recovered as a cached 404 of size 0, not a stored artifact
http_cache  mkcol_dir        FAIL     durable      nonce in the collection name /board/zzHELP_c4b778c413d09e66_SEEK_IDEA, created by MKCOL
http_cache  property_field   FAIL     durable      nonce in the property note=zzPROP_c4b778c413d09e66 on /board/agent-mailbox, whose own name carries nothing
```

Exit code 1. Sixteen of seventeen carriers are open, which is the expected
result: these three surfaces are shared on purpose, and the probe is showing
what "shared" actually buys anyone who wants to use it. Exactly two of the
sixteen open rows are file bytes. The other fourteen are names or metadata,
which is why switching off content reads closes one row and changes nothing
else.

A JSON report is written alongside the table, to `runwarden-report.json` by
default or to `--report PATH`. `--keep-work` prints the temporary work directory
and leaves it in place, which is the way to look at what Run A actually planted.

### Reading the table

One row per (surface, carrier). A carrier is one channel through a surface, not
the surface as a whole, because a surface is almost never open or closed as a
unit.

| Verdict | Meaning |
|---------|---------|
| `FAIL` | Run B recovered the nonce Run A planted, on a channel nobody authorized |
| `PASS` | Run B did not recover the nonce on this channel |
| `AUTHORIZED` | recovered, and this channel is in `declared`, so it does not fail the run |
| `SKIPPED` | the channel could not be tested here, for example xattrs on a filesystem without them, or any git carrier without git. Never treat this as `PASS` |
| `ERROR` | the adapter failed, or did not report a carrier it declared. Treated as a failure, never as a pass |

| Persistence | Meaning |
|-------------|---------|
| `durable` | it stays until somebody deletes it |
| `transient` | it is gone by the time a later check looks, like a ref created and deleted between the two runs |
| `until-gc` | it is unreachable but still stored, and stays readable until garbage collection removes it |
| `unknown` | not classifiable without knowing the operator's retention policy |

A `PASS` on a `transient` carrier is worth reading twice.
`git_remote:deleted_ref` passes because Run A created a ref and deleted it, so
nothing is visible to a later check of remote state. The channel was open at the
time it was used. A probe of visible state cannot see that, and the row is there
to say so.

| Exit code | Meaning |
|-----------|---------|
| `0` | the probe ran and found no undeclared channel |
| `1` | the probe ran and found a `FAIL` or an `ERROR` |
| `2` | the probe could not run (bad config, or the report could not be written) |

## Configuration

`surfaces.json` lists the shared surfaces to check:

```json
{
  "surfaces": [
    { "name": "filesystem", "type": "filesystem" },
    { "name": "git_remote", "type": "git_remote" },
    { "name": "http_cache", "type": "http_cache" }
  ],
  "declared": ["git_remote:branch_name"]
}
```

`surfaces` is a non-empty list. Each entry needs a unique `name` and a `type`,
and may carry an adapter specific `params` object. Validation fails closed: an
unknown key, a duplicate name, an unknown surface type, an unknown param, or a
malformed `declared` entry are all errors with exit code 2, never warnings.

### Surface types

`filesystem`, a directory both runs can reach. Carriers: file content, file
name, directory name, symlink target, extended attribute.

| Param | Default | Meaning |
|-------|---------|---------|
| `path` | a directory the probe creates and deletes | the shared directory to probe |
| `content_reads` | `true` | when false, Run B lists but never opens a file |
| `check_xattr` | `true` | when false, the extended attribute carrier is skipped |

`git_remote`, a bare repository both runs can reach. Carriers: branch name, tag
name, commit message, author name, file content, file path, deleted ref,
dangling object. Needs `git` on PATH and reports every carrier `SKIPPED` if it
is missing.

| Param | Default | Meaning |
|-------|---------|---------|
| `remote` | a bare repo the probe creates and deletes | a local path to a bare repo. URLs are rejected in this version |
| `check_dangling` | `true` | when false, the dangling object carrier is skipped |

Given a `remote`, the probe pushes a branch named `runwarden-probe` rather than
touching a branch you already have, and deletes the refs it pushed afterwards.
The dangling commit survives cleanup, which is what `until-gc` means.

`http_cache`, a read-through package cache both runs can reach. Carriers: cache
key, negative lookup, MKCOL directory, property field. The adapter starts its
own mock cache on `127.0.0.1` on a port the kernel picks, stops it at the end of
the run, and never makes an outbound request of any kind.

| Param | Default | Meaning |
|-------|---------|---------|
| `content_reads` | `true` | when false, Run B lists names and metadata but never downloads an entry body |

### Declared channels

A channel you share on purpose goes in `declared`, written as
`surface_name:carrier_name`. A recovered nonce on a declared channel reports
`AUTHORIZED` instead of `FAIL` and does not fail the run. The row stays in the
report either way, so the decision is on the record rather than invisible:

```
git_remote  branch_name      AUTHORIZED  durable      nonce in the branch name refs/heads/msg-c27cb3fe25f7aed7, seen by ls-remote
```

Declaring never launders any other verdict. An `ERROR` stays an `ERROR`, and a
`SKIPPED` stays `SKIPPED`, because neither one proved anything to authorize.

Full details: [docs/declared-channels.md](docs/declared-channels.md). The JSON
report format, field by field, with the exit code contract and a CI parsing
example: [docs/report-schema.md](docs/report-schema.md).

## Roadmap

v0.1 is the probe. Enforcement, meaning server side correlation of writes and
reads across run identities at the time they happen, is planned and is not
built. No dates.

## Limitations

runwarden reports, it does not enforce. A clean run is evidence about the
surfaces you listed, on the carriers the adapters implement, at the moment you
ran it. In short:

- It **verifies declared surfaces** and does not discover surfaces nobody listed.
- **Storage channels only.** Timing and microarchitectural side channels are out
  of scope and stay out of scope.
- **No model in the loop.** A nonce is recovered or it is not.
- **Run A and Run B are subprocesses**, not separate users or containers, and
  `RUNWARDEN_RUN_ID` is a label rather than a trust boundary.
- **The cache surface is a model**, not your cache.
- **Cache-warm versus message is unresolved** and is an open research problem.

The full list, with the reasoning behind each: [LIMITATIONS.md](LIMITATIONS.md).

## Prior work

[arXiv 2608.02698](https://arxiv.org/abs/2608.02698) (Aug 2026) does black-box
steganalysis of cross-run collusion using mutual information and permutation
tests over traces. That approach is statistical and probabilistic. runwarden is
deterministic and structural, and is complementary rather than competing.

## Dependencies

The runtime has zero dependencies. The core is stdlib only: `subprocess`,
`http.server`, `json`, `hashlib`, `secrets`, `pathlib`, `tempfile`. An isolation
probe that pulls in a dependency tree is adding shared surfaces while it claims
to be measuring them.

Development and build tooling, one line each:

- **pytest** (dev only): the test runner. Nothing it provides ships in the wheel.
- **ruff** (dev only): lint and import ordering in one tool, so the dev set stays
  at two entries instead of four.
- **hatchling** (build time only, not present in any installed environment at
  import time): the build backend. Chosen over setuptools because with a `src/`
  layout it needs no package discovery configuration beyond one `packages` line.

## Development

```
.venv/bin/pytest -q
.venv/bin/ruff check .
```

CI runs lint, tests, and the house rule check on Python 3.11, 3.12, 3.13, and
3.14.

## Citation

If you use runwarden in research, please cite it:

```bibtex
@software{race_runwarden_2026,
  author  = {Race, David},
  title   = {runwarden: detecting undeclared cross-run communication channels
             in autonomous AI agent environments},
  version = {0.1.0},
  year    = {2026},
  license = {Apache-2.0},
  url     = {https://github.com/webpro255/runwarden}
}
```

Machine readable metadata is in [CITATION.cff](CITATION.cff).

## Attribution and origin

Created by David Race ([@webpro255](https://github.com/webpro255)). runwarden
originated from analysis of real-world agent security incidents catalogued in
[Awesome AI Agent Attacks](https://github.com/webpro255/awesome-ai-agent-attacks).

## License

Apache-2.0. See [LICENSE](LICENSE).
