# Go backend migration recovery

Overall migration progress: **2%**. Tasks 1–5 are accepted. Task 6 and the remaining
server, ingestion, state compatibility, and performance acceptance work are
unfinished.

The last product snapshot is commit
`04d0cd2a453e1032f5904d0a611a252a39d289eb`, with tree
`bba90dc7589b64bb8366668a506cb86cc4fb26f2`. Its original Git history was recovered
on 2026-11-07 from bundle SHA256
`ec3911cc1e02c8e90c8e7e4d0ce81786218209d07d7dc77b44a2763c2373ad9f`.
The original history is now also preserved on GitHub at
`go/migration-source-original-20261107`; its remote head was read back and
matches the original commit above. The public `go/full-backend-source-backup` branch at commit
`e424f06c30acddae4b928c3611c4f2067198f4b8` has the same source tree.

The latest verified private execution archive has SHA256
`f1b34b50f07fbff283654fbc3516ab5ce3cee52914ce60fdbed1ff3a999325b8`.
Its 213 logical files were recovered and independently checked against the
archive, embedded census, byte hashes, and file modes. The archived experiment
passed 28 positive test declarations. Its first negative compilation rejected
the intended conversion, then failed the frozen diagnostic attribution rule;
three negative commands were not run. The prototype remains unaccepted.

The required prototype preparation and execution archives have been restored.
The interrupted diagnostic-contract review has no accepted final verdict. A new
independent review is in progress. Complete it before applying a correction in a
new scope. Preserve the historical failed result and original product snapshot.

Keep normal commits at reviewable source milestones and push them before long
tests or an environment transition. Read back the remote head; a local commit
alone is not an external backup. Do not force-push or overwrite older backups.

Checkpoint private uncommitted work before long tests and at least every
20 minutes while changing it. Verify uploaded bytes and hashes, and perform a
restore check before treating a checkpoint as recoverable. If that check fails,
pause new changes until the backup is repaired. Preserve previous checkpoints
and their dependency chain; never publish private evidence in the public repo.
Record the latest verified checkpoint and next action in the recovery ledger.

Generated work, tool caches, isolated checkouts, and private evidence live in
ignored directories. After a restart, recover the original Git history, verify
the source tree, restore the checkpoint dependency chain and compare file hashes
before resuming. Reinstall tools separately; caches are not backups. The earlier
missing October 17 commit was not recovered by this reconstruction.
