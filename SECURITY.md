# Security policy

## Reporting a vulnerability

Report a vulnerability in runwarden itself privately, not in a public issue.

- Preferred: open a private advisory at
  https://github.com/webpro255/runwarden/security/advisories/new
- Alternative: email TODO-SECURITY-CONTACT (David: replace this placeholder with
  the address you want to receive reports on before the repo goes public).

Please include the version, the platform, the config that reproduces it, and
what you expected instead. A proof of concept helps and is not required.

Expect an acknowledgement within a week. This is a small project with one
maintainer, so a fix may take longer than an acknowledgement, and you will be
told which is happening. Credit is offered in the advisory unless you prefer
otherwise.

## Supported versions

Only the latest released version is supported. runwarden is at 0.1.0 and there
is no backport line yet.

## Scope

In scope, meaning a report is wanted:

- A probe result that is wrong in the direction that matters: a carrier that
  reports `PASS` while the channel is in fact open, or an adapter whose recover
  path can miss a nonce its plant path wrote. A false clean run is the worst
  failure this tool has.
- Anything that lets probe input escape the probe: a config value, a surface
  path, or an adapter param that reaches a shell, escapes the work directory,
  or writes outside the paths runwarden created.
- The `http_cache` mock server accepting a connection from anywhere other than
  loopback, or making any outbound request.
- Leaking the contents of a probed surface into the report, the table, or the
  logs beyond the one line of detail a finding is meant to carry.

Out of scope:

- Findings that runwarden correctly reports about your environment. A table full
  of `FAIL` rows is the tool working. Those are channels in your infrastructure,
  not vulnerabilities in runwarden.
- The limits documented in [LIMITATIONS.md](LIMITATIONS.md), which are stated
  non-claims rather than defects: undiscovered surfaces, timing channels,
  subprocess rather than container isolation, and `RUNWARDEN_RUN_ID` not being a
  trust boundary.
- Reports against the deliberately permissive behavior of the `http_cache` mock.
  It models an open cache on purpose; that is the fixture, not a bug.

## What runwarden does on your machine

Worth knowing before you run it, because it is a security tool and you should
not have to take that on trust:

- It has zero runtime dependencies. The core is stdlib only.
- It makes no outbound network request. The `http_cache` adapter binds its mock
  cache to `127.0.0.1` on a port the kernel assigns, and both probe runs reach
  it over loopback only.
- The untrusted-adjacent code paths, meaning the plant and recover logic that
  handles surface data, run in local subprocesses under your own uid, in
  temporary working directories runwarden creates and removes. They are not a
  sandbox: see the isolation section of [LIMITATIONS.md](LIMITATIONS.md).
- Given a `remote` or a `path` you supply, it writes to that surface. On a git
  remote it pushes to a branch named `runwarden-probe` and deletes the refs it
  pushed, and one dangling object survives by design, which is the `until-gc`
  carrier. Point it at a scratch remote, not a production one.
- It plants a random nonce and innocuous marker text. No secrets, no
  credentials, and no real hostnames appear in any fixture or test.
