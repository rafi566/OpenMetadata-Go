# Resume the full Go migration

The working branch is `go/full-backend-reconstruction` in
`https://github.com/rafi566/OpenMetadata-Go`. This is a reconstruction from
baseline `2f0d4a4a42663d565b23c6018f098cfb07516fd6`; the former migration branch,
its local commits, and interrupted Task9 working tree were not recovered.
Historical acceptance does not establish that reconstructed source passes.

## Checkpoints

Commit source, public specifications, plans, and this runbook normally with
repository hooks. Push the dedicated branch without force and verify its SHA
with `git ls-remote`. If shell Git authentication is unavailable, preserve
equivalent committed source through the connected GitHub app on
`go/full-backend-source-backup`; do not start a login flow or change credentials.
Verify every changed blob and the complete resulting tree against the immutable
local commit. Use a non-force expected-head update, then independently read the
ref, commit tree, parent, and `git ls-remote` result.

App-created commits have different metadata and SHAs. Record their mapping to
the original local commit and identical tree. Preserve the original commit DAG
in the actor-private Git bundle included in a source checkpoint. Its prerequisite
baseline is `2f0d4a4a42663d565b23c6018f098cfb07516fd6`. A verified incremental
bundle may supplement a newer local commit after its declared prerequisite has
been restored. An equivalent tree alone does not recover original metadata.
Keep credentials, private captures, controller artifacts, and raw evidence out
of this public repository.

Keep a separate actor-private backup of the task ledger, briefs, reports,
source provenance, checksum manifests, and any uncommitted source needed to
resume. Include the exact Git HEAD, task state, and outstanding review findings.
Read each uploaded backup back independently and verify its size and SHA256;
upload success alone is not a recovery check. Record the backup reference in
the private resume page. Back up at stable implementation milestones and after
reviewed units, before proceeding to dependent work. During implementation,
close and pause product writes for a checkpoint before more than 20 minutes of
source writing; resume after external verification. Mark unreviewed source and
incomplete test processes explicitly. Do not archive secrets or tool caches.
Keep the external evidence copy when cleaning up temporary local task files.

Ordered JSON parts avoid the 256 KiB text-readback limit. Verify actual downloaded
source bytes, each decoded part, the reassembled archive, and every member against
`CHECKPOINT.json`. Large immutable inventories may use explicit `external_members`
with member path, bytes, SHA256, direct anchor archive identity and ordered part
references. Verify those archives and members too; the newest archive alone is
then insufficient. Changed inventories must be included again. Current source
and runtime evidence remain captured; this mechanism does not authorize omission.

The private state's `latest_verified_checkpoint` identifies the source snapshot;
`git_history_backup` and `github_connector_source_backup` identify distinct
original-history and equivalent-tree supplements. Other compatibility fields
may retain historical receipts. Match immutable hashes and receipt paths instead
of inferring recency from filenames or every field containing "latest".

A temporary machine can still disappear. External verified checkpoints make
work recoverable up to the latest checkpoint; they do not guarantee that an
environment persists or that an in-progress write survives.

## Resume after a reset

1. Read the actor-private migration backup page in the connected account. Identify
   the latest verified source checkpoint, original HEAD, all required anchors and
   supplements, accepted tasks and outstanding review findings before writing.
2. Clone the repository and obtain the pinned baseline. Read the dedicated source
   backup mapping; verify its complete tree against the checkpoint. Restore the
   original full Git bundle and any prerequisite-ordered incremental supplements
   in an isolated repository. Run `git bundle verify`, compare advertised heads,
   and verify original objects/ancestry before checking out the recorded HEAD.
3. Download the checkpoint's restore envelope or ordered JSON parts and anchors.
   Text readback is limited to 256 KiB per file; larger archives use small parts.
   For multipart backups, verify each part_index, part_count, and part_sha256;
   decode part_base64 and concatenate decoded bytes in index order. Do not
   concatenate the JSON documents. Verify the complete archive byte count and
   SHA256 against the private page. For a single envelope, decode archive_base64
   and perform the same complete-archive checks.
   Inspect archive members before extracting into new private scratch space.
   Reject duplicate, absolute, escaping, linked, nonregular or oversized entries.
   Verify the full member manifest and required anchor members. Preserve this
   externally downloaded evidence copy.
4. Restore uncommitted source onto the matching original HEAD. Compare source
   hashes, modes and Git status with the snapshot. Apply recorded `deleted_paths`
   only as safe relative deletions within that isolated checkout; restore original
   `source_mode` separately from private archive permissions. Restore the matching
   ledger and evidence separately from public source. Distinguish byte-matched
   original files, transcripts, excerpts and reconstructed code. Never invent old
   commits, missing evidence, benchmark results or completed process exits.
5. Create or verify an isolated linked worktree. Activate Python 3.11 before
   Python work, install normal hooks, and use the selected Go toolchain. The
   current setup uses Go 1.27.2, Python 3.11.17, and Node 22 for hooks; tool
   locations are machine-local and must be re-established after a reset.
6. Resume the first incomplete task using a fresh implementer and independent
   spec/quality review. Re-run checks affected by reconstructed source. Save
   and verify a new external checkpoint before moving to dependent work.

## Tested restore boundary

The Task2 fix2 source checkpoint and exact731488 supplement were restored into
a new Git object database without alternates or network fallback after separately
providing the pinned baseline. Source hashes, modes, paused status, original
commit/tree objects and connectivity matched. This exercise covers that checkpoint;
it does not establish generic staged/index, merge/rebase, deletion recovery (the
snapshot had no deletions), tool-cache recreation or acceptance of later snapshots.

## Completion boundary

Schema/model reconstruction is a foundation. The goal remains all first-party
Java server components and Python ingestion/connectors in Go, including durable
jobs and workflows, compatible APIs and data, upgrade/rollback verification,
and measured performance. Acceptance targets are at least 30% lower RAM,
20% lower p95 latency, and 25% higher throughput, with CPU per operation no more
than 5% worse and no scenario p95 more than 5% worse. No performance improvement
has been measured for this reconstruction yet.
