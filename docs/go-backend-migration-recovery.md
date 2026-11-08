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
The current private recovery checkpoint, observed on 2026-11-08 at
07:50:28 UTC, is snapshot commit
`0926b329a061fff378df6851abb3d6e53c263345` on
[codex/openmetadata-go-backups in the private herse repository](https://github.com/rafi566/herse/tree/codex/openmetadata-go-backups).
That repository was empty and only the owner's collaborator access was present
before the first backup push. The product repository remains OpenMetadata-Go.
The snapshot contains 3,984 files / 135,908,852 logical bytes, including all
1,388 current selected files and authenticated bases, retained historical source
and evidence, and 47 checkpoint archives. A normal push, exact remote-head
readback, independent remote clone and fresh restore verified all file bytes,
modes and nine hardlink groups. MANIFEST.json SHA256 is
`43f867cfa76092e153fe83a741aeb6ba1554587201e780e69b3211e2e8f512b6`;
restore proof SHA256 is
`1783d6878a39c223d3f6bb1fc0e758335f8a50192ee6fe00c5321d4132430c51`.
Read RECOVERY.json on that branch first for newer continuation metadata.
Toolchains, environments and caches are installed and checked separately;
this is a named source/evidence snapshot, not a machine image.

Earlier Page/File checkpoints and their dependencies remain preserved. They
include the independently restored 203-file archive
`dbc2dcb77c5866e707b5b3b9e60409e7503e9d966b372813ef76d85133381cf2`
and exact reconstructed 105-file archive
`389bced74b67f93fbd65acfcf8f1113889453cb4196f1e471ca01f8286fbb8de`.
The compiler-concurrency source correction is now accepted after independent
review and 30 passing checks. The external controller's latest 45 tests pass,
but whole-core review found an adopted-child wait cleanup defect. The original
author must correct it and the same reviewer must verify the correction.
The controller remains unaccepted. None of this authorizes Go or native execution.

Use the [main recovery Page](https://chatgpt.com/space/page_6880055acd3881919465f9c35c7d0f4d)
for recovery links and the preserved dependency chain. The earlier verified
chain has 269 File SOURCE references and 126 Page SOURCE blocks; all
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
P0B4B external controller/source/resource integration from the accepted P0B4A
compiler-concurrency source unit. Exact finite SDK characterization needs
a separate reviewed release and verified external restore before any Go starts.
Shared presence, opt-in partitioned generation and full generation/compilation
remain later gates. Follow the current ledger's next action and closed reviews,
not an old snapshot's pending label. Preserve all unfinished WIP as such.

Keep normal commits at reviewable source milestones and push them before long
tests or an environment transition. Read back the remote head; a local commit
alone is not an external backup. Do not force-push or overwrite older backups.

Checkpoint private uncommitted work with normal private-branch commits, remote
readback and a fresh clone restore before long tests and at least every
20 minutes while changing it; start preparation 10 minutes after the previous
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
