# Resume the full Go migration

The working branch is `go/full-backend-reconstruction` in
`https://github.com/rafi566/OpenMetadata-Go`. This is a reconstruction from
baseline `2f0d4a4a42663d565b23c6018f098cfb07516fd6`; the former migration branch,
its local commits, and interrupted Task9 working tree were not recovered.
Historical acceptance does not establish that reconstructed source passes.

## Checkpoints

Commit source, public specifications, plans, and this runbook normally with
repository hooks. Push the dedicated branch without force, then verify its
SHA with `git ls-remote`. Keep credentials, private captures, controller
artifacts, and raw evidence out of this public repository.

Keep a separate actor-private backup of the task ledger, briefs, reports,
source provenance, checksum manifests, and any uncommitted source needed to
resume. Include the exact Git HEAD, task state, and outstanding review findings.
Read each uploaded backup back independently and verify its size and SHA256;
upload success alone is not a recovery check. Record the backup reference in
the private resume page. Back up at stable implementation milestones and after
reviewed units, before proceeding to dependent work. Mark unreviewed source and
incomplete test processes explicitly. Do not archive secrets or tool caches.

A temporary machine can still disappear. External verified checkpoints make
work recoverable up to the latest checkpoint; they do not guarantee that an
environment persists or that an in-progress write survives.

## Resume after a reset

1. Clone the repository and check out `go/full-backend-reconstruction`.
   Compare HEAD to the latest verified private checkpoint before writing.
2. Open the actor-private migration backup page in the connected account.
   Download the latest restore envelope and verify its SHA256 against that
   page. Decode its base64 archive; verify the archive byte count and SHA256.
   Inspect archive member paths before extracting into a new private scratch
   directory. Reject absolute paths, traversal, and links outside that directory.
3. Restore the matching ledger and evidence. Read task completion and review
   entries before dispatching work. Distinguish byte-matched original files,
   transcript copies, patch excerpts, and reconstructed code. Never invent old
   commits, missing evidence, benchmark results, or completed process exits.
4. Create or verify an isolated linked worktree. Activate Python 3.11 before
   Python work, install normal hooks, and use the selected Go toolchain. The
   current setup uses Go 1.27.2, Python 3.11.17, and Node 22 for hooks; tool
   locations are machine-local and must be re-established after a reset.
5. Resume the first incomplete task using a fresh implementer and independent
   spec/quality review. Re-run checks affected by reconstructed source. Save
   and verify a new external checkpoint before moving to dependent work.

## Completion boundary

Schema/model reconstruction is a foundation. The goal remains all first-party
Java server components and Python ingestion/connectors in Go, including durable
jobs and workflows, compatible APIs and data, upgrade/rollback verification,
and measured performance. Acceptance targets are at least 30% lower RAM,
20% lower p95 latency, and 25% higher throughput, with CPU per operation no more
than 5% worse and no scenario p95 more than 5% worse. No performance improvement
has been measured for this reconstruction yet.
