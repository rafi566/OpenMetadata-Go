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

Current public source work continues on `go/partitioned-model-generation`.
The latest reviewed source checkpoint is commit
`a7daaf2c6d5f81acc059a3c793f27dd6f083c6b4`; its normal push and exact remote head
were verified. P0B1 event/host supervision and P0B2 trace reconciliation remain
accepted. P0B3 shared driver capture and fixture lifecycle is now accepted after
independent review and fixes for FIFO admission, cleanup on persistence failure,
and a single cleanup deadline. Its affected Python suites passed 127 and 32
checks. The added Go fixture helper has not been compiled or executed. These
source units grant no new Go execution authority. This branch retains the
recovered original product history; read its latest reviewed commits and the
private ledger before choosing a resume point.

The latest verified complete private execution archive has SHA256
`776df04664b505741cdcc17ced6ebeccfedc362a701ed6d546221103b5806596`.
Its 593 logical files include all new raw execution, parent logs and independent
reviews; all eleven native SOURCE parts were read back and a fresh restore
verified. Accepted source/helper evidence is preserved in checkpoint
`33476c2db881dcce7182c7f740f9a09eae1f80e25fa0c295d828d794446df654`:
91 files/four SOURCE parts. An earlier reviewed B2 source delta is
`b0e4fd0add7992970d37a8e9c0fd57bc85ab139ae3b25ec3538912223523bcee`:
64 files/four Page SOURCE parts, including final reviewed B2 source, tests,
reports and all new failed/corrected evidence. An independent fresh restore
verified all file bytes, hashes and modes; proof SHA256 is
`386c56a345deedb931a68befd589391e86b4655da76c178633b506fca6a9d271`.
The latest verified private preparation checkpoint, observed on 2026-11-08 at
02:17:19 UTC, has SHA256
`e7ab38b63c5d9bdf86c5afc725b01bde5d1c2fec0c5dc3db9dbc495b5f299a70`:
169 files / 3,408,417 logical bytes / five Page SOURCE parts. External readback
and a fresh restore verified all file bytes, hashes and modes; proof SHA256 is
`6f99207464e1f7f8076ce01a36a6ea080ea7ec303fb9200c51c1bd3abc50c108`.
It preserves the four-case private SDK preparation before its independent
review found a compiler-concurrency admission bug. That source unit is not
accepted; its correction and refreshed controls require scoped review and a
later verified checkpoint. It contains no authorized Go or native execution.

Use the [main recovery Page](https://chatgpt.com/space/page_6880055acd3881919465f9c35c7d0f4d)
for the newest private checkpoint and its complete dependency chain. The latest
verified chain has 269 File SOURCE references and 82 Page SOURCE blocks; all
914 existing File references remain on the main Page. Private snapshots depend
on their preserved code, metadata and older archives; a delta is not a replacement.
Earlier duplicate uploads, failed reads and one upload with unknown outcome
retain their actual receipts. Uncertain writes are never blindly repeated.
Page SOURCE blocks carry new archives after the File upload path returned an
unknown outcome. Extra newlines in old saved copies were corrected from actual
SOURCE readbacks; failed copies and exact diagnoses remain preserved. A backup
can preserve failing or unfinished work without accepting it.

The repaired finite prototype passed 28 positive declarations and four exact
negative conversion controls, with independent review. Only the small private
representation is accepted. Production partitioned generation, complete corpus,
server behavior and performance remain unaccepted. Its eight-command release
is spent; do not replay it or infer a new Go release from a planning document.
The older failed negative-attribution result remains historical evidence and
was not retroactively accepted. Both complete old generated modules were also
restored byte-for-byte; preserve them instead of regenerating over them.

The new plan starts with full-source and tool-invocation supervision. Its
source guard and P0B1/P0B2/P0B3 source units are accepted. Continue the private
P0B4A compiler-concurrency fix and independent review, then P0B4B external
controller/source/resource integration. Exact finite SDK characterization needs
a separate reviewed release and verified external restore before any Go starts.
Shared presence, opt-in partitioned generation and full generation/compilation
remain later gates. Follow the current ledger's next action and closed reviews,
not an old snapshot's pending label. Preserve all unfinished WIP as such.

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
After uncertain or truncated tool output, reconcile the still-running execution,
stored receipts and external state before repeating an upload or save. Preserve
actual failed attempts and duplicate references. Do not run Git commit/push
while code authors or tests are active: both normal hooks can temporarily
stash and restore tracked changes. Verify source hashes after each hook.
The 20-minute target has been missed during review/backup preparation; misses
are recorded. These safeguards reduce recovery risk, not guarantee zero loss.

Generated work, tool caches, isolated checkouts, and private evidence live in
ignored directories. After a restart, recover the original Git history, verify
the source tree, restore the checkpoint dependency chain and compare file hashes
before resuming. Reinstall tools separately; caches are not backups. The earlier
missing October 17 commit was not recovered by this reconstruction.
