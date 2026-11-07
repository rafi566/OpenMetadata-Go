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

Current public design/plan work continues on `go/partitioned-model-generation`.
The latest reviewed design checkpoint is commit
`63952bd5e5d1e140edd7916d134366a3c0254b33`; its normal push and exact remote head
were verified. The four source/tool helper scripts were accepted at
`6ffd32aabbdcaa6682cfb26db25a37bcbd25ed39` after31 Python checks and independent
review. The newer host/fixture supervision design has passed review; its P0B1
implementation is in progress, without new Go execution authority. This branch
retains the recovered original product history. Read its latest reviewed
commits and the private ledger before choosing a resume point.

The latest verified complete private execution archive has SHA256
`776df04664b505741cdcc17ced6ebeccfedc362a701ed6d546221103b5806596`.
Its 593 logical files include all new raw execution, parent logs and independent
reviews; all eleven native SOURCE parts were read back and a fresh restore
verified. Accepted source/helper evidence is preserved in checkpoint
`33476c2db881dcce7182c7f740f9a09eae1f80e25fa0c295d828d794446df654`:
91files/four SOURCE parts. The latest verified private design WIP delta is
`f9e4c9f2ee79bc6791ec508f7f33880511f1bf051a411ddbf5cbfbda3b158487`:
29files/three parts, also read back and restored. It preserves the first
design correction; subsequent clean reviews, final counter correction and P0B1
code are later work. The chain now has237 ordered SOURCE references and all882 references
on the private backup Page remain available. These snapshots depend on the
preserved code, metadata and older archive chain; a delta is not a replacement.

The repaired finite prototype passed 28 positive declarations and four exact
negative conversion controls, with independent review. Only the small private
representation is accepted. Production partitioned generation, complete corpus,
server behavior and performance remain unaccepted. Its eight-command release
is spent; do not replay it or infer a new Go release from a planning document.
The older failed negative-attribution result remains historical evidence and
was not retroactively accepted. Both complete old generated modules were also
restored byte-for-byte; preserve them instead of regenerating over them.

The new plan starts with full-source and tool-invocation supervision. Its
four-script helper unit is accepted; the composed host/fixture supervisor is
still incomplete. Continue P0B1 events/host evidence, P0B2 SDK trace parsing,
P0B3 fixture/driver integration, and the separately released P0B4 SDK
characterization before shared presence and the opt-in generator. Full generation and compilation
need distinct reviewed releases. Follow the current ledger's next action and
closed reviews, not an old checkpoint's historical pending label. Preserve all
unfinished WIP as such; a backup is not acceptance.

Keep normal commits at reviewable source milestones and push them before long
tests or an environment transition. Read back the remote head; a local commit
alone is not an external backup. Do not force-push or overwrite older backups.

Checkpoint private uncommitted work before long tests and at least every
20 minutes while changing it; start preparation10 minutes after the previous
verified checkpoint. Verify uploaded bytes and hashes, and perform a
restore check before treating a checkpoint as recoverable. If that check fails,
pause new changes until the backup is repaired. Preserve previous checkpoints
and their dependency chain; never publish private evidence in the public repo.
Record the latest verified checkpoint and next action in the recovery ledger.
The 20-minute target has been missed during review/backup preparation; misses
are recorded. These safeguards reduce recovery risk, not guarantee zero loss.

Generated work, tool caches, isolated checkouts, and private evidence live in
ignored directories. After a restart, recover the original Git history, verify
the source tree, restore the checkpoint dependency chain and compare file hashes
before resuming. Reinstall tools separately; caches are not backups. The earlier
missing October 17 commit was not recovered by this reconstruction.
