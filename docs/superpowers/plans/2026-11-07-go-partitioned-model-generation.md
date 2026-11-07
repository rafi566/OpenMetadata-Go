# Partitioned Go Model Generation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Preserve the user's four reused agent limit. Steps use checkbox syntax; no nested or fresh agents.

**Goal:** Complete Task 6 with independently buildable, complete, deterministic
Go models under the selected resource boundary.

**Architecture:** Retain the single-package generator and add an explicit
partitioned layout using document SCC implementation packages and public aliases.
All implementations share a per-root carrier/registry and a common presence
leaf. Preserve exact schema semantics and use bounded source/process supervision
for complete-corpus validation.

**Tech Stack:** Go 1.27.2, jsonschema/v6 v6.0.3, Python 3.11.17 in the activated
reference venv, existing normal Git hooks. No new dependencies.

**Spec:** `docs/superpowers/specs/2026-11-07-go-partitioned-model-generation-design.md`;
the original `2026-10-17-go-schema-model-reconstruction-design.md` also applies.

## Global Constraints

- Original module: `github.com/rafi566/OpenMetadata-Go/openmetadata-go`.
- Preserve authoritative schemas, wire keys, physical/RFC6901 identities,
  strict validation, exact Value/Number algorithms and existing semantic tests.
- Preserve `GenerateOptions{Package,OutputDir string}`, default `Generate`
  output bytes and absent-layout CLI behavior. Shared Optional relocation is
  the explicitly documented cross-mode defining-identity exception.
- Input 16 MiB, depth 256, 10,000 documents, 1,000,000 raw entries. Numeric
  mantissa 10,000, absolute exponent 10,000, joint closure/instance cost
  1,000,000; cardinalities fit int64/platform int; bounded cache <=10,000.
- New partition layout: <=28,000 generated files, <=16 MiB/file,
  <=256 MiB output and <=240-byte filename components. Check actual support,
  controls and generated files against the unchanged 30,000-path export cap.
- Four CPUs, 16-GiB hard boundary, 15-GiB observed stop, 900-second command
  timeout, 20-second cleanup; normal inherited caches, no cache clearing or
  resource/environment policy changes.
- No new Go invocation until its exact source/controller/command release has
  independent review and a verified recoverable external checkpoint. The tiny
  prototype release is spent. No old monolithic retry.
- Keep original full-a/full-b modules and private source/evidence immutable.
  Commit and push source milestones normally; verify the remote SHA. Snapshot
  private WIP before long tests and every 20 minutes while changing it, including
  honest incomplete work. Do not wait for feature acceptance to save it.
- Review each implementation unit for spec compliance and quality before its
  dependent unit. Final strongest whole-foundation review is separate.
- No SQL, CI, deployment, authoritative schema or dependency changes. Backend,
  ingestion/connectors, state migration and performance acceptance remain later
  mandatory work.

## Review Focus

1. A reference resolves into another document: field, array/map and branch
   signatures and constructors must record imports from the original owner.
2. Admitted hostile asset names or a reserved-prefix collision: ordinary embed
   retains exact bytes/paths and includes no helper/control file.
3. A reused Optional/model contains a shallow mutable payload: preserve existing
   ownership and transactional semantics without inventing a deep clone.
4. A large/cyclic graph or colliding output crosses a bound: reject before
   writes, without dropping nodes or installing a partial layout.
5. Warm-cache assumptions or a nested Go subprocess fail: process/capture/source
   guards fail closed with terminal cleanup; no silent retry or missing coverage.

---

## Files and interfaces

All code paths below start at `openmetadata-go/`.

| File | Responsibility |
| --- | --- |
| `internal/schema/presence/optional.go`, `schema/optional.go` | Exact shared presence implementation and hand-owned public facade |
| `internal/schema/generate.go`, `generate_composition.go` | Existing templates with optional rendering hooks; default stays unchanged |
| `internal/schema/generate_partition_graph.go` | Typed reference planning, document SCCs, deterministic import/component graph |
| `internal/schema/generate_partitioned.go` | Explicit API, configuration checks and generation orchestration |
| `internal/schema/generate_partition_emit.go` | Component implementations, root aliases/carrier/registry and raw mirror |
| `internal/schema/generate_partition_manifest.go` | Versioned complete ownership/alias/source manifest and output preflight |
| `cmd/om-contracts/schema.go` | Explicit layout/import-path CLI selection |
| `internal/schema/generate_partitioned_test.go`, `generate_partition_graph_test.go` | New behavior tests; existing default tests remain |
| `scripts/partitioned_source_guard.py`, private execution evidence | Complete bounded streaming source validation around unchanged tiny controller |
| `scripts/record_partitioned_tool.py` | Bounded exact tool-exec argument recording, including nested Go invocations |
| `scripts/install_partitioned_models.py` | Staged manifest-owned model installation without touching support/tests |

Private planner identities are structured `{Path,Pointer string}` values, not
ambiguous strings split on `#`. `typedEdge` stores structured `Owner`, `Target`
and `Kind`; `partitionPlan` records nodes, declarations, components, DAG imports,
full membership digests and root import path. Bound all collections by admitted
source/node counts; these are request-local planning data, not persistent caches.

### Task P0: Supervised full-source and compiler evidence support

**Run this task before P1.** P1–P3 cannot run their Go checks using the small
prototype's source/capture assumptions. P4 later closes the actual complete
layout schedule; it consumes this already reviewed support.

**Files:** Create `scripts/partitioned_source_guard.py`,
`scripts/test_partitioned_source_guard.py`, `scripts/record_partitioned_tool.py`,
`scripts/test_record_partitioned_tool.py`; new private wrapper/command plans.

**Interfaces:** `verify_manifest(root: Path, manifest: dict) -> dict` consumes
strict versioned JSON containing root-relative file rows (path, bytes, SHA256,
mode) and explicitly closed excluded output/temp subtrees. It independently
streams exact membership and bytes with nofollow ancestry, stable regular-file
identity and nlink=1, within30,000 paths/16MiB member/256MiB root. Missing/extra,
duplicate JSON/paths, symlinks, unstable reads or bounds produce failure. Return
compact complete digest/count receipts, not replacement raw evidence.
The tool recorder's `main(argv: list[str]) -> int` records exact selected-tool
arguments and TOOLEXEC_IMPORTPATH before exec, preserving tool/version output
and exit behavior. Bind approved tools, invocation/environment/source scope,
response-file policy and finite argument/record budgets in its release.

- [ ] Write real filesystem and owned child fixture tests for source tampering,
  extra/omitted files, symlink/ancestor redirect, duplicate entries, changed read,
  bound+1, record persistence failure, argument misclassification and version
  probing. A missing module is setup evidence; record meaningful RED from a
  real contract assertion after an importable initial API exists.
- [ ] Implement only those guards. Exercise actual small child processes;
  preserve their terminal exits/EOF/cleanup. No Go, tool impersonation or
  uncontrolled subprocess is needed for Python behavior checks.
- [ ] Review the full-source wrapper composition: immutable narrow controller
  inputs remain under its old500files/4MiB guard; full input checks execute
  before/after the child INSIDE the same900s/resource supervision. It cannot
  return success if any guard, terminal or persistence check fails.
- [ ] Under activated Python3.11.17 run
  `python -B -m unittest discover -s scripts -p 'test_*partitioned*.py'`.
  Expect all new real behavior/fault tests to pass; this is migration tooling,
  not a Python production server. Review/pin exact recorder and wrapper paths,
  flag propagation including nested fixture Go, and finite command evidence.
- [ ] Independently review, normal commit/push/readback and externally checkpoint
  this support. Close a separate finite P1 command release before P1 Go. P0
  itself authorizes no Go or complete-corpus command schedule.

### Task P1: Shared presence and legacy characterization

**Files:** Create `internal/schema/presence/optional.go` and a focused sibling
test; modify `schema/optional.go`, only support-copy wiring in
`internal/schema/generate_test.go`, and the new partitioned test file.

**Interfaces:** Produce `presence.Optional[T any]`, `Some[T](T) Optional[T]`,
`Null[T]() Optional[T]` with the exact current methods/algorithm; public schema
exposes the generic alias and same-signature functions. `optional_test.go`
remains byte-identical. Value/Number and default model semantics stay unchanged.

- [ ] Record baseline legacy fixture output hashes and the two-field unkeyed
  GenerateOptions literal in a new characterization test. Include canonical
  schema and alternate-package generation. Do not alter existing assertions.
- [ ] Add a behavior test proving public Optional assignment/method expressions
  use the shared leaf, plus shallow map/slice payload ownership, null/missing,
  reuse and failed-decode preservation. Record compilation prerequisite failures
  separately; claim RED only for an actual unmet behavior assertion.
- [ ] Copy the existing algorithm exactly to the leaf and implement only public
  alias/forwarders. Add the leaf to independent-module copy allowlists.
- [ ] Under a new reviewed command release run
  `go test ./schema ./internal/schema/presence ./internal/schema -count=1`.
  Expect all retained Optional and default independent fixtures to pass, exact
  baseline generated hashes to match, and chosen all-consumer defining package
  differences to be asserted. Capture nested fixture Go scheduling/flags.
- [ ] Independently review, commit `refactor: share exact schema presence support`,
  push/read back remote SHA, and checkpoint private checks before P2.

### Task P2: Source-bound typed dependency planning

**Files:** Modify `generate.go` and `generate_composition.go`; create
`generate_partition_graph.go`, `generate_partition_graph_test.go`.

**Interfaces:** `modelGenerator` receives optional private rendering context.
Its single `resolveType(owner,target *entry,kind string,imports map[string]string)
(string,error)` serves all property/map/items/branch signature and construction
sites. Context helpers select raw-value access, decode commit, composition
branch construction, registry prefix and presence import. Nil context emits
the exact old templates. `documentComponents(edges []typedEdge,nodes []Node)
(partitionPlan,error)` returns deterministic SCC membership and dependency order.

- [ ] Add cases where pure refs and modern sibling projections resolve shapes
  in another document. Assert original owner/resolved child locators for object
  properties, items, additionalProperties and every composition branch.
  Include escaped `#`/percent paths and a two-document recursive pair.
- [ ] Add shuffled-input determinism, isolated documents, self/multidocument
  cycles, shortened-key collision and whole-node membership checks. Test existing
  parent-invalid versus branch-nonmatch/blocker behavior stays unchanged.
- [ ] Implement minimal template hooks and a fresh planning pass that renders
  one node at a time, records typed edges/declaration AST inventory and discards
  its bytes. Condense grouped documents with an iterative bounded graph walk.
  Sort component memberships/imports and collision-check complete digests.
- [ ] Under the reviewed release run
  `go test ./internal/schema -run 'Test(PartitionGraph|Generated|Composition|MapPattern|RecursiveViews|Generate)' -count=1`.
  Expect fresh graph assertions and baseline output hash equality. A missing API
  compile error is a prerequisite result, never the behavioral RED evidence.
- [ ] Review, commit `feat: plan schema component dependencies deterministically`,
  push/read back and checkpoint. No generated production package is installed.

### Task P3: Complete opt-in output and ordinary embedding

**Files:** Create `generate_partitioned.go`, `generate_partition_emit.go`,
`generate_partition_manifest.go`, `generate_partitioned_test.go`; modify CLI
`schema.go` and add focused tests to a new `schema_partitioned_test.go`.

**Interfaces:** Produce the exact three-field GeneratePartitionedOptions and
GeneratePartitioned API from the spec. CLI absent layout=legacy; explicit
partitioned requires canonical generated-root ImportPath verified against the
copied module/output location. Canonical `<module>/schema` requires package
`schema`. Returns sorted generated-root-relative paths. Registry exports
`Instance() (*support.Registry,error)`, `Decode(string,[]byte)
(support.Value,error)`, `Validate(string,support.Value) error`,
`Branch(string,support.Value) (support.Value,bool,error)` and
`RawSources() (fs.FS,error)`; facade private helpers forward to this instance.
Carrier exposes internal-only `Carrier`, `FromValue(support.Value) Carrier`,
`Value(Carrier) support.Value`. Every root owns a distinct carrier definition.

- [ ] First add a CLI behavior test using valid partitioned flags: existing
  schemaCommand returns nonzero for the new mode, whereas the expected contract
  is successful partitioned generation. Record this real feature rejection as
  RED, independently of later new-symbol compilation prerequisites.
- [ ] Add original-module consumer tests for aliases, exact field/method/function
  signatures, enum constants, JSON interfaces, zero literals, within-root value
  and pointer conversions, and negative cross-root conversions. Assert selected
  reflection differences. Construct invalid parents by same-root conversion
  from an unconstrained model; keep parent-first/blocker assertions.
- [ ] Add ordinary no-overlay embed tests for top-level `[`, `#`, `@`, `-`,
  whitespace and Unicode-letter paths, hidden/underscore/testdata descendants,
  mirror prefix collisions and raw/helper file-directory collisions. Assert
  original/mirror/embedded file-set and hash equality, with no extra files.
- [ ] Add no-write failures for nil registry, malformed package/import/module
  location, reserved support destinations, canonical-root wrong package,
  existing/symlink output, symbol/case-fold/path collisions, 28,000+1 paths,
  16-MiB+1 member, 256-MiB+1 total, 240-byte+1 component and oversized SCC.
  Use shared buffers/metadata at budget boundaries rather than massive fixtures.
- [ ] Implement a second fresh emitter state: qualified component references,
  combined imports and one implementation file per component; per-node facade
  aliases, constant forwarding, one registry/carrier, alternate-root presence
  facade, original assets plus safe mirror, indexes and partition manifest.
  Reconcile planned/emitted edge and declaration digests before writing.
  Manifest format is `openmetadata-go-partitioned-models-v1`: `import_path`,
  `package`, sorted `sources` (path/SHA256), `components` (package/full digest/
  document members/imports), `declarations` (structured identity/kind/name/
  implementation/facade), typed `edges`, and sorted `files` (path/bytes/SHA256).
  `owned_paths` includes the manifest itself; `files` excludes its self-hash.
  Component digests use SHA256 over sorted original member paths, each encoded
  as UTF-8 followed by one LF (admitted paths cannot contain LF). Retain full digests and reject
  shortened-key collisions. Other JSON is deterministic indented UTF-8 plus LF.
- [ ] Run reviewed targeted new tests and all default tests in independent copied
  modules; verify exact legacy hashes, full tiny semantics and ordinary embed
  without overlays. Expect all positive controls and exact intended negative
  rejections; setup failures never pass.
- [ ] Review, commit `feat: generate partitioned schema models with ordinary embed`,
  push/read back and externally checkpoint before complete-corpus execution.

### Task P4: Full-source execution composition

**Files:** Create a new private finite execution plan/launcher using the P0
source guard/recorder and unchanged reviewed controller. Do not mutate old
controllers, releases, module pairs or receipts.

**Interfaces:** Consume P0's exact guarded manifest/recorder interfaces and P3's
actual output/import manifests. Controller watches narrow immutable code; the
reviewed composition preserves complete before/after source checks within the
same supervised resources/timeout, never merely a smaller watched source set.

- [ ] Verify the pinned P0 support and review any new scheduling-specific fault
  controls. Preserve normal/failure evidence; don't repeat unchanged passed
  checks or treat historical results as fresh executions.
- [ ] Derive a finite dependency-first schedule from actual manifests/imports.
  Start with <=32 package targets/batch and <=128 commands per (copy,mode),
  including its final all-package command. Account for actual cold closures,
  standard library, vet, cgo and test variants; smaller batches need a closed
  reviewed plan, never automatic retry. Keep each unchanged controller's total
  256 owned identities/128 compiler captures and every raw output/telemetry cap.
- [ ] Use `-p=1` and explicit all-package compiler `-c=1` flags, with independently
  recorded effective command coverage including nested fixture Go children.
  Warm normal/race dependency closures separately using normal caches; no cache
  deletion, fabricated cold claims, changed GC budget or hidden compiler scope.
- [ ] Reserve lossless raw/telemetry budget before each batch. Segment verified
  external checkpoints before aggregate capsule limits; never discard output
  to fit. Preserve terminal/wait4/EOF/process identity/no-survivor/source/resource
  gates. Any budget/cache/ownership/source failure stops the schedule for review.
- [ ] Review exact source and plan independently, checkpoint all closed inputs,
  then record a new explicit root command release. Do not execute full corpus
  merely because this prose plan or the private tiny result exists.
- [ ] Checkpoint the reviewed exact full schedule and private preparation/release.

### Task P5: Twice-clean complete corpus and semantic acceptance

**Files:** Generate only into NEW independent modules under ignored
`work/schema/reconstruction/partitioned-{a,b}`. Copy pinned support/dependencies,
protected corpus fixtures/semantic template and presence leaf. No live imports.

**Interfaces:** Both modules keep the original module path and generate
ImportPath=`<module>/schema`, Package=`schema`; output is their own `schema/`.
Manifest parsing/auditing uses structured schema identities and complete hashes.

- [ ] Freshly audit unchanged 1,071 documents, every 6,745 reference and all
  18,084 required nodes; independently cross-check all 14 recursive source member
  sets with typed traversal and invalid-leaf controls. Recompute the emitted Go
  component graph; do not copy the earlier 1,069-component expectation.
- [ ] Run the two reviewed partitioned generations through the explicit CLI and
  compare all relative output bytes/hashes and partition manifests. Reconcile
  source hashes, exactly-once declarations, every alias/object/constant target,
  file budgets and dependency/import closure; no facade/self/live import cycle.
- [ ] Execute both independent modules through the released finite normal and
  race schedules, including literal final `go test ./... -count=1` and
  `go test -race ./... -count=1` with reviewed scheduling/compiler flags. Preserve
  all actual terminal evidence and failures; graph checks do not replace runtime
  semantic tests.
- [ ] Preserve complete emitted semantic assertions: CreateTable/Table nested
  columns, connections, entity references, extensions/timestamps, direct ODCS
  vendor fields, RDF sparqlTripleTerm/sparqlResponse recursion and test-suite
  resultSummary. Workflow `{}` matches exactly 17/rejects, AutoClassification
  exactly three/rejects; null/missing/defaultabsence/typearray/anyOf/allOf/
  conditionals/strict oneOf and numeric/ownership/reuse controls remain.
- [ ] Independent spec and quality acceptance of full outputs/semantics/resources
  precedes installation. Checkpoint complete outputs, source context and results
  in bounded segments; retain old monolithic modules and failed history.

### Task P6: Manifest-owned installation and foundation acceptance

**Files:** Create `scripts/install_partitioned_models.py` plus behavior tests;
generate staging and install only into the product's `schema/` generated paths.
Update public runbook/spec status after verified results, never before them.

**Interfaces:** Installer accepts validated old/new generated ownership manifests
and staging root, fully preflights exact path ownership/delta and protected files,
then replaces only owned output. No force/overwrite escape hatch; partial I/O
failure preserves staged output/recovery information and cannot claim success.

- [ ] Python RED/GREEN covers unowned collision, protected Optional/test paths,
  stale manifest/hash, symlink/ancestor redirect, malicious path, interrupted
  publication and deterministic deletion of only previously owned stale output.
- [ ] Install the independently accepted complete generation from staging;
  verify full output/corpus manifest hashes and byte-identical protected tests.
- [ ] Run released product `go test ./... -count=1`, `go test -race ./... -count=1`,
  `go build ./cmd/om-contracts` and full-profile `schema check` with unchanged
  source/resources, complete exact compiler/process/terminal evidence.
- [ ] Strongest independent whole-foundation review compares accepted Task1–5
  invariants and Task6 requirements against the complete final diff and results.
  Fix real findings and rerun affected checks; then normal hooks/commit/push,
  remote SHA readback and verified external source/history/evidence checkpoint.
- [ ] Only then accept Task6, update overall progress honestly and continue the
  approved server/ingestion/connector/state migration. Performance requires its
  own measured Java/Go baseline and approved acceptance gates.

## Plan self-review and execution state

Coverage: full input/compiler supervision=P0; presence/default identity=P1;
typed graph/default templates=P2; opt-in API/layout/ordinary embed/bounds=P3;
complete layout schedule/process/resource proof=P4;
complete graph/14 recursive groups/seven semantic groups/twice-clean outputs=P5;
manifest installation and final foundation gates=P6. Each Review Focus item
has an owning task. Names/signatures and source ownership are explicit above.

Plan is drafted for the already-selected subagent-driven method. No task is
marked complete and no new Go execution is released by writing this plan.
