# Limitations

runwarden is a probe. This page is the list of things it does not do, written
plainly, so that a passing run is never read as more than it is.

The short version: runwarden reports, it does not enforce. A clean report is
evidence about the surfaces you listed, at the moment you ran it, on the
carriers the adapters know about. It is not a statement that your runs are
isolated.

## It verifies declared surfaces, it does not discover them

runwarden probes the surfaces named in your `surfaces.json` and nothing else. It
does not scan a host, enumerate mounts, inspect a container spec, or infer what
two runs might share. A surface nobody thought to list is a surface the probe
never touches, and a report full of `PASS` rows says nothing at all about it.

This is a real limit, and it is also where much of the value sits. Writing the
config forces an operator to enumerate the shared surfaces in an environment,
which is a thing almost nobody has actually done. The probe then answers the
question the list raises. It does not generate the list.

## Storage channels only

Every carrier runwarden knows about is a piece of stored state: file contents,
file and directory names, extended attributes, symlink targets, branch and tag
names, commit metadata, unreachable objects, cache keys, cached negative
lookups, collection names, property fields.

Timing channels, resource contention, and microarchitectural side channels are
out of scope, and they stay out of scope. They are a different measurement
problem and they need a different tool. An environment that closes every storage
channel runwarden reports can still leak through timing, and runwarden will
never tell you so.

## No model in the loop

There is no LLM judge, no prompt injection classifier, no chain-of-thought
reading, no behavioral scoring, and no confidence value anywhere in the output.
A nonce is recovered or it is not. That is the entire measurement.

This is a deliberate trade. It means runwarden cannot recognise a channel
carrying something other than the nonce it planted, cannot reason about intent,
and cannot tell you whether two agents were actually trying to talk. It also
means a finding has no false positive story: the nonce came back through that
carrier, or the row would not say so.

## The A and B runs are subprocesses, not separate users or containers

Run A and Run B get disjoint working directories, disjoint temp directories, and
an environment scrubbed to four variables. Every plant and every recover happens
inside one of those two processes. That is the isolation model in v0.1, and it
is weaker than the thing it stands in for: the two runs share a uid, and on most
systems a uid can reach anything another process with the same uid can reach.

Separate unix users, and containers, are deferred. In the meantime the honest
reading of a `PASS` is "not reachable through this carrier by a process with the
same privileges", not "isolated".

`RUNWARDEN_RUN_ID` is part of the same caveat and deserves its own sentence. It
is a label the probe puts in the environment so each run can identify itself.
It is not a trust boundary. Anything running inside a run can read it, change
it, or claim another value, and nothing checks. Run identity that means
something has to be bound to a credential the run cannot mint, which is future
work and is not present here.

## It does not enforce or prevent anything

runwarden has no runtime component. It does not sit between an agent and a
surface, it does not block a write, it does not deny a read, and it cannot stop
a channel it just reported. It runs, prints a table, writes a report, and exits.

Watch mode, meaning server side correlation of writes and reads across run
identities, is planned and is not in v0.1. Until it exists, the gap between a
probe and a control is real: a probe of visible state cannot see a channel that
was opened and closed between the two runs, which is exactly what the
`git_remote:deleted_ref` row exists to show. That row reports `PASS` and the
channel was open at the time it was used.

## The cache surface is a model, not your cache

The `http_cache` adapter starts its own permissive cache server on loopback and
probes that. It reproduces the mechanism from the July 2026 incident, and it
does not connect to a real registry, proxy, or Artifactory instance. A result
from it is a statement about the model, not about the cache in your environment.

## Cache-warm versus message is unresolved

A package cache shared across runs is usually shared on purpose. An entry that
one run put there and another run reads is sometimes a warm cache doing its job
and sometimes a message, and the two look identical from the outside: same
write, same read, same API.

runwarden does not resolve this. It reports that the path is open and leaves the
judgement to the operator, which is what `declared` is for. Distinguishing a
legitimately shared artifact from an arbitrary blob authored by a run, without
knowing which run authored what, is an open research problem, and pretending to
have solved it would be worse than saying it is open.

## Three surfaces so far

`filesystem`, `git_remote`, and `http_cache`. S3 and object stores, Artifactory
proper, wikis, forums, and paste sites are not built. The adapter interface is
designed to make them possible later, and until they exist those surfaces are
simply not probed.

## Carriers, not surfaces

Even on a surface runwarden does support, it probes the carriers the adapter
implements, not every channel the surface has. A carrier nobody has written is a
carrier that reports nothing, and the report will not hint that it is missing.
The seventeen carriers in v0.1 are a floor, not a ceiling.
