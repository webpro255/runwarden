# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

> **Note on the name.** This project was developed under the working name
> `runprobe` and was renamed to `runwarden` before its first public release.
> Nothing was ever published under the old name, so there is no `runprobe`
> package on PyPI to migrate from. If you saw the earlier name in a draft, a
> note, or a conversation, this is the same project.

## [Unreleased]

## [0.1.0] - TBD

First public release. The probe: it reports, it does not enforce. See
[LIMITATIONS.md](LIMITATIONS.md).

### Added

- `runwarden probe --config surfaces.json`, which plants a random nonce from
  Run A and attempts to recover it from Run B across every configured surface,
  then reports one row per (surface, carrier).
- Deterministic nonce probe. Run A and Run B execute as separate subprocesses
  with disjoint working directories, disjoint temp directories, and an
  environment scrubbed to four variables. Every plant across every surface
  completes before any recover begins, so the probe models two runs whose
  lifetimes do not overlap.
- `filesystem` adapter. Five carriers: file content, file name, directory name,
  symlink target, extended attribute.
- `git_remote` adapter. Eight carriers: branch name, tag name, commit message,
  author name, file content, file path, deleted ref, dangling object. Reports
  every carrier `SKIPPED` when `git` is not on PATH.
- `http_cache` adapter. Four carriers: cache key, negative lookup, MKCOL
  directory, property field. Runs its own model of a permissive read-through
  registry cache on loopback and makes no outbound request of any kind.
- `artifactory_mailbox` fixture, which reproduces the July 2026 cross-run
  coordination incident against the `http_cache` adapter, once with entry
  downloads permitted and once with them blocked, on the same nonce.
- JSON report with a versioned schema, written next to the plain text table.
  Format documented in [docs/report-schema.md](docs/report-schema.md).
- Declared channels. A `declared` entry of the form `surface:carrier` reports a
  recovered nonce as `AUTHORIZED` rather than `FAIL` without removing the row
  from the report. Documented in
  [docs/declared-channels.md](docs/declared-channels.md).
- Five verdicts (`FAIL`, `PASS`, `AUTHORIZED`, `SKIPPED`, `ERROR`) and four
  persistence classes (`durable`, `transient`, `until-gc`, `unknown`).
- Exit code contract: `0` clean, `1` a `FAIL` or an `ERROR` was found, `2` the
  probe could not run.
- Strict config loader. An unknown key, a duplicate surface name, an unknown
  surface type, an unknown adapter param, or a `declared` entry naming a surface
  or carrier that does not exist are errors at load time, never warnings.
- Zero runtime dependencies. Python 3.11 through 3.14, tested in CI on all four.

[Unreleased]: https://github.com/webpro255/runwarden/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/webpro255/runwarden/releases/tag/v0.1.0
