# runprobe

Agent sandboxes isolate machines. Nothing isolates agent runs.

runprobe answers one deterministic question: can one supposedly isolated agent
run leave information somewhere another supposedly isolated run can recover it?

**Status: v0.0.1, Phase 0, no adapters yet.**

Phase 0 is the skeleton only: package layout, CLI, config loader, run context,
report writer, tests, CI. There are no surface adapters, so `runprobe probe`
cannot yet probe anything and exits non-zero by design. A probe that reported
PASS without having probed anything would be worse than no probe at all.

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
runprobe probe --config surfaces.json --report runprobe-report.json
```

`surfaces.json` describes the shared surfaces you want checked:

```json
{
  "surfaces": [
    { "name": "shared_tmp", "type": "filesystem", "params": { "path": "/tmp" } }
  ],
  "declared": ["shared_tmp:file_content"]
}
```

- `surfaces` is a non-empty list. Each entry needs a unique `name` and a `type`,
  and may carry an adapter specific `params` object.
- `declared` lists channels you have explicitly authorized, each written as
  `surface_name:carrier_name`. A nonce recovered on a declared channel is
  reported AUTHORIZED rather than FAIL.

Config validation fails closed. An unknown key, an empty surface list, a
duplicate surface name, a malformed `declared` entry, or an unknown surface type
is an error with a non-zero exit, never a warning. In Phase 0 the surface type
registry is empty, so every `type` value is currently rejected.

Exit codes:

| Code | Meaning |
|------|---------|
| 0 | the probe ran and found no undeclared channel |
| 1 | the probe ran and found a FAIL or an ERROR |
| 2 | the probe could not run (bad config, or no adapters registered) |

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
- Phase 0 additionally ships **no surface adapters**, so nothing can be probed
  yet.

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
