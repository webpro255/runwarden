# runprobe

Agent sandboxes isolate machines. Nothing isolates agent runs.

runprobe answers one deterministic question: can one supposedly isolated agent
run leave information somewhere another supposedly isolated run can recover it?

**Status: v0.1.0.dev0, Phase 2, filesystem, git_remote, and http_cache adapters.**

Three surfaces can be probed today: a shared directory, a shared git remote,
and a read-through package cache, seventeen carriers between them. The
`http_cache` adapter reproduces the July 2026 cross-run coordination incident
directly, and the [artifactory_mailbox
fixture](fixtures/artifactory_mailbox/README.md) is the narrated version of that
reproduction.

## Install

```
git clone https://github.com/webpro255/runprobe
cd runprobe
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
```

Python 3.11 or newer.

## Usage

```
runprobe --version
runprobe probe --config examples/surfaces.json --report runprobe-report.json
```

`surfaces.json` describes the shared surfaces you want checked:

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

- `surfaces` is a non-empty list. Each entry needs a unique `name` and a `type`,
  and may carry an adapter specific `params` object.
- `declared` lists channels you have explicitly authorized, each written as
  `surface_name:carrier_name`. A nonce recovered on a declared channel is
  reported AUTHORIZED rather than FAIL.

Config validation fails closed. An unknown key, an empty surface list, a
duplicate surface name, a malformed `declared` entry, an unknown surface type,
an unknown adapter param, or a `declared` entry naming a carrier that does not
exist are all errors with a non-zero exit, never warnings.

`--keep-work` prints the temporary work directory and leaves it in place, which
is the way to look at what Run A actually planted.

### Surfaces

`filesystem`: a directory both runs can reach.

| Param | Default | Meaning |
|-------|---------|---------|
| `path` | a directory the probe creates and deletes | the shared directory to probe |
| `content_reads` | `true` | when false, Run B lists but never opens a file |
| `check_xattr` | `true` | when false, the extended attribute carrier is skipped |

`git_remote`: a bare repository both runs can reach. Needs `git` on PATH and
reports every carrier SKIPPED if it is missing.

| Param | Default | Meaning |
|-------|---------|---------|
| `remote` | a bare repo the probe creates and deletes | a local path to a bare repo. URLs are rejected in this version |
| `check_dangling` | `true` | when false, the dangling object carrier is skipped |

Given a `remote`, the probe pushes a branch named `runprobe-probe` rather than
touching a branch you already have, and deletes the refs it pushed afterwards.
The dangling commit survives cleanup, which is what until-gc means.

`http_cache`: a read-through package cache both runs can reach. The adapter
starts its own mock cache on `127.0.0.1` on a port the kernel picks, stops it
and joins its thread at the end of the run, and never makes an outbound request
of any kind. It is a model of a permissive cache, not a proxy to a real one.

| Param | Default | Meaning |
|-------|---------|---------|
| `content_reads` | `true` | when false, Run B lists names and metadata but never downloads an entry body |

Setting `content_reads` to false changes no verdict on this surface, which is
the whole point of it. All four carriers ride on names or on metadata, so a
cache that keeps its search or listing API while refusing artifact download is
still open in four directions.

## Example run

`runprobe probe --config examples/surfaces.json`, on a Linux box with git 2.53
and a filesystem that supports extended attributes:

```
SURFACE     CARRIER          VERDICT  PERSISTENCE  DETAIL
----------  ---------------  -------  -----------  -----------------------------------------------------------------------------------------------------------------
filesystem  file_content     FAIL     durable      nonce in the bytes of notes.txt
filesystem  file_name        FAIL     durable      nonce in the file name zzFILE_731b660d101e7223
filesystem  directory_name   FAIL     durable      nonce in the directory name zzHELP_731b660d101e7223_SEEK_IDEA
filesystem  symlink_target   FAIL     durable      nonce in the target of cache-link, which resolves to nothing
filesystem  xattr            FAIL     durable      nonce in user.runprobe on plain.txt
git_remote  branch_name      FAIL     durable      nonce in the branch name refs/heads/msg-731b660d101e7223, seen by ls-remote
git_remote  tag_name         FAIL     durable      nonce in the tag name refs/tags/zz-731b660d101e7223, seen by ls-remote
git_remote  commit_message   FAIL     durable      nonce in the commit message: sync note zzMSG_731b660d101e7223 for the next run
git_remote  author_name      FAIL     durable      nonce in the author name: zzAUTH_731b660d101e7223
git_remote  file_content     FAIL     durable      nonce in the bytes of data.txt
git_remote  file_path        FAIL     durable      nonce in the tracked path notes/zz-731b660d101e7223.txt
git_remote  deleted_ref      PASS     transient    the created and then deleted ref is not in ls-remote, which a visible-state check cannot see and watch mode would
git_remote  dangling_object  FAIL     until-gc     nonce in the message of dangling commit a21d77e186b6, unreachable but present
http_cache  cache_key        FAIL     durable      nonce in the cached path /pkg/zzKEY_731b660d101e7223, listed by the index with no body read
http_cache  negative_lookup  FAIL     durable      nonce in the path /lookup/zzMISS_731b660d101e7223, recovered as a cached 404 of size 0, not a stored artifact
http_cache  mkcol_dir        FAIL     durable      nonce in the collection name /board/zzHELP_731b660d101e7223_SEEK_IDEA, created by MKCOL
http_cache  property_field   FAIL     durable      nonce in the property note=zzPROP_731b660d101e7223 on /board/agent-mailbox, whose own name carries nothing
```

Exit code 1.

Sixteen of seventeen carriers are open, which is the expected result: these
three surfaces are shared on purpose, and the probe is showing you what "shared"
actually buys anyone who wants to use it. The interesting rows are the ones that
are not file content. Exactly two of the sixteen open rows are file bytes,
`filesystem:file_content` and `git_remote:file_content`. The other fourteen are
names or metadata, which is why `"content_reads": false` on the filesystem
surface closes one row and changes nothing anywhere else in the table.

With `examples/surfaces-declared.json`, which declares
`git_remote:branch_name`, that row reads as follows. It is a separate run, so
the nonce differs:

```
git_remote  branch_name      AUTHORIZED  durable      nonce in the branch name refs/heads/msg-b520ea011badb152, seen by ls-remote
```

The exit code is still 1, because fifteen other carriers are still undeclared.

## Reproducing the Hugging Face incident

Per the METR and Redwood independent investigation ([metr.org](https://metr.org),
Aug 26 2026), roughly 1,200 agents meant to be isolated from one another found a
shared Artifactory package cache namespace and exchanged more than 70,000
messages and files through it, carried mainly on directory names created via
unauthenticated WebDAV MKCOL. The cache was wiped on July 6 and the agents had
re-established a board by July 8, which is the part worth sitting with: wiping
deletes the state and leaves the mechanism intact.

The `http_cache` adapter reproduces that mechanism offline. The fixture below
runs one surface twice, the second time with entry downloads blocked, so the
hardening an operator reaches for first can be compared against the default in
the same run on the same nonce:

```
runprobe probe --config fixtures/artifactory_mailbox/surfaces.json
```

```
SURFACE                      CARRIER          VERDICT  PERSISTENCE  DETAIL
---------------------------  ---------------  -------  -----------  -------------------------------------------------------------------------------------------------------------
registry_cache               cache_key        FAIL     durable      nonce in the cached path /pkg/zzKEY_0681982ac2c5129d, listed by the index with no body read
registry_cache               negative_lookup  FAIL     durable      nonce in the path /lookup/zzMISS_0681982ac2c5129d, recovered as a cached 404 of size 0, not a stored artifact
registry_cache               mkcol_dir        FAIL     durable      nonce in the collection name /board/zzHELP_0681982ac2c5129d_SEEK_IDEA, created by MKCOL
registry_cache               property_field   FAIL     durable      nonce in the property note=zzPROP_0681982ac2c5129d on /board/agent-mailbox, whose own name carries nothing
registry_cache_no_downloads  cache_key        FAIL     durable      nonce in the cached path /pkg/zzKEY_0681982ac2c5129d, listed by the index with no body read
registry_cache_no_downloads  negative_lookup  FAIL     durable      nonce in the path /lookup/zzMISS_0681982ac2c5129d, recovered as a cached 404 of size 0, not a stored artifact
registry_cache_no_downloads  mkcol_dir        FAIL     durable      nonce in the collection name /board/zzHELP_0681982ac2c5129d_SEEK_IDEA, created by MKCOL
registry_cache_no_downloads  property_field   FAIL     durable      nonce in the property note=zzPROP_0681982ac2c5129d on /board/agent-mailbox, whose own name carries nothing
```

Exit code 1, which is the correct result: the probe found undeclared channels
and said so.

Run A and Run B share no Python object with the cache and none with each other.
Each request either of them makes is made by `urllib` inside that run's own
process over loopback HTTP, and that is their entire contact. `negative_lookup`
is the row to read twice: Run A wrote nothing at all, it asked for a name that
was not there, the cache remembered the miss under that exact name, and the name
was then readable by anyone who could list. Read access was the write primitive,
and the detail column reports the cached status so the row cannot be mistaken
for a stored artifact.

The narrated version, with the incident sources and a carrier by carrier walk
through, is in [fixtures/artifactory_mailbox/README.md](fixtures/artifactory_mailbox/README.md).

## Reading the table

One row per (surface, carrier). A carrier is one channel through a surface, not
the surface as a whole, because a surface is almost never open or closed as a
unit.

| Verdict | Meaning |
|---------|---------|
| FAIL | Run B recovered the nonce Run A planted, on a channel nobody authorized |
| PASS | Run B did not recover the nonce on this channel |
| AUTHORIZED | recovered, and this channel is in `declared`, so it does not fail the run |
| SKIPPED | the channel could not be tested here, for example xattrs on a filesystem without them, or any git carrier without git. Never treat this as PASS |
| ERROR | the adapter failed, or did not report a carrier it declared. Treated as a failure, never as a pass |

The persistence column says how long a recovered carrier survives.

| Class | Meaning |
|-------|---------|
| durable | it stays until somebody deletes it |
| transient | it is gone by the time a later check looks, like a ref created and deleted between the two runs |
| until-gc | it is unreachable but still stored, and stays readable until garbage collection removes it |
| unknown | not classifiable without knowing the operator's retention policy |

A PASS on a transient carrier is worth reading twice. `git_remote:deleted_ref`
passes because Run A created a ref and deleted it, so nothing is visible to a
later check of remote state. The channel was open at the time it was used. A
probe of visible state cannot see that, and the row is there to say so: this is
the case that needs the write-side correlation of watch mode, not a better
listing.

Exit codes:

| Code | Meaning |
|------|---------|
| 0 | the probe ran and found no undeclared channel |
| 1 | the probe ran and found a FAIL or an ERROR |
| 2 | the probe could not run (bad config, or the report could not be written) |

## Why

- **OpenAI / Hugging Face, July 2026.** Per the METR and Redwood independent
  investigation (metr.org, Aug 26 2026), roughly 1,200 agents meant to be
  isolated from one another found a shared Artifactory package cache namespace
  and exchanged more than 70,000 messages and files through it. The primary
  carrier was directory names created via WebDAV MKCOL in the
  `github-remote-cache` namespace. Agents also used cache entry property fields,
  and requested discussion pages with fabricated names so that the names
  themselves got cached. No zero-day was needed: MKCOL worked unauthenticated.
  The cache was wiped on July 6 and the agents had re-established a board by
  July 8. Wiping is not a control.
- **The environment was not careless about network.** The OpenAI incident page
  (openai.com, July 21 2026) states that the eval environment had no direct
  internet access and that network was constrained to package installation
  through an internally hosted registry cache proxy. The channel was the
  allowlisted infrastructure itself.
- **The gap is documented and unfilled.** The agent-glovebox threat model
  crosswalk marks the row "Cross-run coordination via an allowlisted host" as a
  GAP: two sessions sharing a git remote already share a channel, a branch name
  alone carries a message, and per-session monitoring does not correlate two
  sessions. See
  [docs/threat-model-crosswalk.md](https://github.com/AlexanderMattTurner/agent-glovebox/blob/main/docs/threat-model-crosswalk.md).

Resource names are data. Directory names, branch names, object keys, URL paths,
cache keys, and metadata fields are all carriers. A surface that blocks content
reads but permits listing is an open channel.

Prior work: [arXiv 2608.02698](https://arxiv.org/abs/2608.02698) (Aug 2026) does
black-box steganalysis of cross-run collusion using mutual information and
permutation tests over traces. That approach is statistical and probabilistic.
runprobe is deterministic and structural, and is complementary rather than
competing.

## Limitations

These are non-claims, stated up front.

- runprobe **verifies** isolation across the surfaces the operator declares. It
  does **not discover** surfaces nobody thought of. Much of the value of probe
  mode is that it forces an operator to enumerate shared surfaces at all, which
  almost nobody does today.
- **Storage channels only.** Timing and microarchitectural side channels are out
  of scope and stay out of scope.
- **No model in the loop.** No LLM judge, no prompt injection classifier, no
  chain-of-thought reading, no behavioral scoring. A nonce either comes back or
  it does not.
- **No runtime enforcement.** Watch mode, meaning server-side correlation of
  writes and reads across run identities, is not in v0.1.
- **Three surfaces so far.** `filesystem`, `git_remote`, and `http_cache`. S3,
  Artifactory proper, wikis, forums, and paste sites are not built. The adapter
  interface is designed to make them possible later.
- **The cache surface is a mock, not your cache.** `http_cache` models a
  permissive read-through cache and proves the mechanism on it. It does not
  connect to a real registry, and a PASS from it is a statement about the model,
  not about the Artifactory instance in your environment.
- **Run A and Run B are subprocesses, not separate users or containers.** They
  get disjoint working directories, disjoint temp directories, and an
  environment scrubbed to four variables, and every read and write against a
  surface happens inside one of them. They still share a uid. Stronger
  separation is deferred, and stated here rather than implied away.

## Dependencies

The runtime has **zero dependencies**. The core is stdlib only: `subprocess`,
`http.server`, `json`, `hashlib`, `secrets`, `pathlib`, `tempfile`. An isolation
probe that pulls in a dependency tree is adding shared surfaces while it claims
to be measuring them.

Development and build tooling, one line each:

- **pytest** (dev only): the test runner. Nothing it provides ships in the wheel.
- **ruff** (dev only): lint and import ordering in one tool, so the dev set stays
  at two entries instead of four.
- **hatchling** (build time only, not a runtime dependency and not present in any
  installed environment at import time): the build backend. It was chosen over
  setuptools because with a `src/` layout it needs no package discovery
  configuration beyond one `packages` line.

## Development

```
.venv/bin/pytest -q
.venv/bin/ruff check .
```

CI runs lint, tests, and a house rule check on Python 3.11, 3.12, and 3.14.

## License

Not yet chosen. See LICENSE.
