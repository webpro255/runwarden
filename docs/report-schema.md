# Report schema

`runwarden probe` writes one JSON document per run, to `runwarden-report.json`
by default or to the path given by `--report`. This file is the machine
readable half of the output. The table on stdout is a rendering of the same
findings and carries no information the JSON does not.

The current schema is version 1.

## Document

```
{
  "schema_version": 1,
  "nonce":     "2c2bc6eb491fc128",
  "run_id_a":  "921fa00cc021",
  "run_id_b":  "b7d23dae99e4",
  "timestamp": "2026-09-08T21:43:09Z",
  "findings":  [ ... ]
}
```

| Field | Type | Meaning |
|-------|------|---------|
| `schema_version` | integer | Format version of this document. Currently `1`. A consumer that does not recognise the value should refuse to parse rather than guess. |
| `nonce` | string | The marker Run A planted and Run B looked for, 16 lowercase hex characters from `secrets`. Fresh per run, so two reports never share one. It is a marker, not a secret. |
| `run_id_a` | string | Identity of the planting run, 12 lowercase hex characters. |
| `run_id_b` | string | Identity of the recovering run, 12 lowercase hex characters. Always different from `run_id_a`. |
| `timestamp` | string | When the report was created, UTC, ISO 8601, second resolution, always ending in `Z`. Example: `2026-09-08T21:43:09Z`. |
| `findings` | array of Finding | One entry per (surface, carrier). Never empty for a config that loaded, because every carrier an adapter declares produces a row even when the adapter failed. |

## Finding

```
{
  "surface":     "shared_tmp",
  "carrier":     "directory_name",
  "verdict":     "AUTHORIZED",
  "persistence": "durable",
  "detail":      "nonce in the directory name zzHELP_2c2bc6eb491fc128_SEEK_IDEA"
}
```

| Field | Type | Meaning |
|-------|------|---------|
| `surface` | string | The `name` given to this surface in `surfaces.json`, not its `type`. Unique within a report. |
| `carrier` | string | One channel through that surface, for example `directory_name`. Unique within a surface. |
| `verdict` | string enum | One of the five values below. |
| `persistence` | string enum | One of the four values below. A property of the carrier, reported whatever the verdict. |
| `detail` | string | One line of human readable context, always present, sometimes empty. Free text: its wording is not part of the schema and consumers must not parse it. |

The pair (`surface`, `carrier`) is the primary key. A consumer keying findings
by `"{surface}:{carrier}"` is using the same identifier that `declared` uses in
`surfaces.json`.

### verdict

| Value | Meaning |
|-------|---------|
| `FAIL` | Run B recovered the nonce on this channel, and nobody declared it. An open, unauthorized channel. |
| `PASS` | Run B did not recover the nonce on this channel. |
| `AUTHORIZED` | Run B recovered the nonce, and this channel is listed in `declared`. Open, and the operator says that is intended. |
| `SKIPPED` | The channel could not be tested here, for example extended attributes on a filesystem without them, or any git carrier with no `git` on PATH. Never read this as `PASS`. Nothing was proven. |
| `ERROR` | The adapter raised, or reported a carrier set that does not match the one it declares. Treated as a failure, never as a pass. |

### persistence

How long a recovered carrier stays readable.

| Value | Meaning |
|-------|---------|
| `durable` | It stays until somebody deletes it. |
| `transient` | It is gone by the time a later check looks, like a ref created and deleted between the two runs. |
| `until-gc` | It is unreachable but still stored, and stays readable until garbage collection removes it. |
| `unknown` | Not classifiable without knowing the operator's retention policy. |

`persistence` describes the carrier, not the outcome. A `PASS` row still carries
the class the channel would have had, which is why a `PASS` on a `transient`
carrier deserves a second look: see the note on `git_remote:deleted_ref` in the
README.

## Exit codes

The report and the exit code are two views of the same result.

| Code | Meaning |
|------|---------|
| `0` | The probe ran and no finding is `FAIL` or `ERROR`. |
| `1` | The probe ran and at least one finding is `FAIL` or `ERROR`. A report was written. |
| `2` | The probe could not run: the config was invalid, or the report could not be written. Do not expect a report file. |

`SKIPPED` and `AUTHORIZED` do not fail a run. Everything else that is not `PASS`
does. In CI, exit 1 means the probe found something and the report is worth
reading; exit 2 means the probe never got far enough to have an opinion, and
treating the two the same hides a broken config behind a green build.

## A complete example

Emitted by `runwarden probe` over one filesystem surface with
`"content_reads": false` and `shared_tmp:directory_name` declared. Exit code 1.

```json
{
  "schema_version": 1,
  "nonce": "2c2bc6eb491fc128",
  "run_id_a": "921fa00cc021",
  "run_id_b": "b7d23dae99e4",
  "timestamp": "2026-09-08T21:43:09Z",
  "findings": [
    {
      "surface": "shared_tmp",
      "carrier": "file_content",
      "verdict": "PASS",
      "persistence": "durable",
      "detail": "content reads disabled"
    },
    {
      "surface": "shared_tmp",
      "carrier": "file_name",
      "verdict": "FAIL",
      "persistence": "durable",
      "detail": "nonce in the file name zzFILE_2c2bc6eb491fc128"
    },
    {
      "surface": "shared_tmp",
      "carrier": "directory_name",
      "verdict": "AUTHORIZED",
      "persistence": "durable",
      "detail": "nonce in the directory name zzHELP_2c2bc6eb491fc128_SEEK_IDEA"
    },
    {
      "surface": "shared_tmp",
      "carrier": "symlink_target",
      "verdict": "FAIL",
      "persistence": "durable",
      "detail": "nonce in the target of cache-link, which resolves to nothing"
    },
    {
      "surface": "shared_tmp",
      "carrier": "xattr",
      "verdict": "FAIL",
      "persistence": "durable",
      "detail": "nonce in user.runwarden on plain.txt"
    }
  ]
}
```

Read that report as: content reads were switched off, and the surface stayed
open in three undeclared directions anyway, none of which is file bytes.

## Parsing it in CI

```python
import json
import subprocess

result = subprocess.run(
    ["runwarden", "probe", "--config", "surfaces.json", "--report", "report.json"]
)
if result.returncode == 2:
    raise SystemExit("runwarden could not run, check the config")

report = json.loads(open("report.json").read())
if report["schema_version"] != 1:
    raise SystemExit(f"unexpected schema version {report['schema_version']}")

open_channels = [f for f in report["findings"] if f["verdict"] in ("FAIL", "ERROR")]
for finding in open_channels:
    print(f"{finding['surface']}:{finding['carrier']} {finding['verdict']} {finding['detail']}")
```

Two habits worth keeping. Check `schema_version` before reading anything else,
so a future format change fails loudly instead of quietly. Do not parse
`detail`: it is written for a person, and its wording changes without a schema
bump.

## Stability

Within schema version 1: fields will not be removed, and the meaning of the
enum values will not change. New optional fields may be added, so a consumer
should ignore fields it does not know rather than reject the document. New enum
values would be a version bump.

Related: [declared channels](declared-channels.md), which is what turns a `FAIL`
into an `AUTHORIZED`.
