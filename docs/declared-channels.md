# Declared channels

Not every shared path between two runs is a mistake. A team may decide that one
cross-run path is intended: a build cache that is supposed to be warm for the
next run, a git remote two agents are meant to collaborate through. runwarden
has no way to tell an intended channel from an unintended one by looking at it,
and it does not try. The operator says which is which, in the config, in
writing.

## The syntax

`surfaces.json` may carry a top level `declared` list. Each entry is exactly
`surface_name:carrier_name`, where the surface name is the `name` you gave the
surface (not its `type`) and the carrier name is one the adapter declares.

```json
{
  "surfaces": [
    { "name": "filesystem", "type": "filesystem" },
    { "name": "git_remote", "type": "git_remote" }
  ],
  "declared": ["git_remote:branch_name"]
}
```

That config says: this environment shares a git remote on purpose, branch names
crossing between runs is expected, and the probe should not fail the build over
it. Everything else stays undeclared.

## What declaring does, and what it does not do

Declaring a channel changes one thing: a recovered nonce on that channel is
reported `AUTHORIZED` instead of `FAIL`, and an `AUTHORIZED` row does not fail
the run.

It does not suppress the row. The finding is still in the table and still in the
JSON report, with its carrier, its persistence class, and the detail describing
exactly what came through. That is deliberate. An authorized channel is still a
channel, and an auditor reading the report six months later needs to see that it
was open and that somebody signed off on it, rather than see nothing at all and
have to guess whether it was closed or excused. A declaration is a recorded
decision, not an exemption from the record.

It does not launder any other verdict:

- An `ERROR` on a declared channel stays `ERROR`. Declaring authorizes a channel
  that was proven open. It says nothing about a channel the probe failed to
  test, so a broken adapter cannot be signed off into a green run.
- A `SKIPPED` channel stays `SKIPPED`. Nothing was tested, so there is nothing
  to authorize.
- A `PASS` stays `PASS`. Declaring a channel that turned out to be closed is
  harmless and reads as intent about a path that does not currently exist.

It also does not narrow the channel. `declared` authorizes the carrier as a
whole, not a particular value moving through it. Declaring
`git_remote:branch_name` authorizes anything any run can encode into a branch
name, which is an arbitrary amount of data. Declare it because you accept that,
not because you expect only build metadata to travel that way.

## Errors, not warnings

A `declared` entry is validated when the config loads, before any surface is
built, and a bad entry is a config error with exit code 2:

- malformed shape, meaning anything that is not exactly one colon with a
  non-empty name on each side
- a surface name that is not defined in `surfaces`
- a carrier name that the adapter for that surface does not have

The last one matters most. A misspelled allowlist entry authorizes nothing while
reading as though it authorized something, so `"fs:file_contents"` (the carrier
is `file_content`) fails at load with the list of carriers that surface actually
has. Silently ignoring it would leave an operator believing a channel was
reviewed when it was not.

## Using it

Declare narrowly. `declared` takes one carrier at a time on purpose, and there
is no wildcard: authorizing a whole surface in one line is exactly the decision
that should be uncomfortable enough to write out carrier by carrier.

Two shapes of run are useful in practice. In CI, declare the channels you accept
and let a non-zero exit catch anything new: a channel that appears after a
platform change shows up as a `FAIL` on the first run after it opens. In an
audit or an assessment, run with `declared` empty, so every open channel is a
`FAIL` and the report is the complete inventory of what is reachable rather than
the list of what nobody has approved yet.

Related: [report schema](report-schema.md).
