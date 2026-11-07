# Partitioned Go model generation

Status: accepted design; implementation and complete-corpus acceptance are pending.
This continues Task 6 of the approved full backend migration. The schema/model
reconstruction specification remains binding except for the explicit presence
location and opt-in model representation amendments below.

## Problem and selected approach

The complete generated model package reached the selected compilation memory
stop. Repeating that monolithic build cannot establish a usable foundation.
The private small representation experiment passed its consumer, semantic and
cross-corpus rejection controls. It does not establish complete-corpus coverage,
ordinary production embedding, or backend performance.

Partition implementation declarations by the emitted Go dependency graph,
grouped by physical schema document and condensed into strongly connected
components (SCCs). Keep aliases at the requested public package. This avoids
requiring application callers to learn implementation package paths. A package
per node would create excessive files/packages; a package per document without
SCC condensation would introduce import cycles. Keep the existing single-package
generator available with its existing default behavior.

## Interfaces and compatibility

Keep `GenerateOptions` with exactly `Package, OutputDir string` and
`Generate(*Registry, GenerateOptions) ([]string, error)`. Its returned sorted
paths and emitted bytes for existing inputs remain unchanged. Add:

```go
type GeneratePartitionedOptions struct { Package, OutputDir, ImportPath string }
func GeneratePartitioned(*Registry, GeneratePartitionedOptions) ([]string, error)
```

CLI `schema generate` defaults to `--layout=legacy` when the flag is absent.
`--layout=partitioned` requires `--import-path`; legacy rejects a supplied import
path rather than silently ignoring it. Reject other layouts and missing/invalid
partitioned import paths before writing. The import path is the generated root's
canonical path within `github.com/rafi566/OpenMetadata-Go/openmetadata-go`, with
a nonempty relative suffix. Do not infer it from the package, output location,
working directory or `go env`. Physical output roots may live in independent
copies of that module. Imports must never point into a live generated checkout.
Require a normalized ASCII suffix of slash-separated nonempty components
containing only letters, digits, `-`, `_` and `.`, beginning with a letter or
digit; reject `.`/`..`, trailing dots, Windows device components and a first
component of `internal`, `cmd`, `work`, `scripts` or `testdata`. These are new-mode
configuration restrictions, not changes to admitted source schema paths.
Validate Package as a Go identifier other than `_` or a keyword. Require
`Package == "schema"` for `ImportPath == <module>/schema`. Verify the explicit
import suffix equals OutputDir's relative path inside the nearest copied
original-module root; reading `go.mod` verifies the supplied identity, never
infers a missing ImportPath. Reject a mismatch before staging or writing.

Preserve every named model, object projection, constant, typed signature,
JSON tag, validator node and numeric token. Preserve zero composite literals,
ordinary and pointer conversions between raw wrappers in one generated corpus,
and rejection between distinct generated roots. Models continue to own exact
private `support.Value` data. A distinct carrier per generated root gives all
its raw wrapper definitions the same private field provenance; constructing an
already validated composition branch uses that internal carrier without another
decode, validation or exposed unchecked public constructor.

Partitioned model aliases deliberately acquire implementation defining package
paths and private field provenance. Reflection, `%T`, default gob identity and
binary identity are not preserved. There is no deployed Go foundation whose
binary identity must be migrated; Java/Python wire data and durable job/workflow
state remain binding contracts for later backend migration work.

### Shared presence is an explicit cross-mode prerequisite

Move the exact hand-maintained `Optional[T]` algorithm to
`internal/schema/presence/optional.go`; retain public `schema.Optional[T]` as a
generic alias and `Some`/`Null` as same-signature forwarding functions. Preserve
shallow ownership of arbitrary `T`, transactionality, methods, constraints and
JSON behavior. Keep `schema/optional_test.go` byte-identical. Update independent
module support-copy lists to include the leaf implementation without weakening
their semantic assertions.

This relocation changes `Optional`'s defining package and private provenance for
**all** users, including legacy layout users. It is a deliberate cross-mode
exception, not an opt-in identity guarantee. The default generator's source
output and APIs remain unchanged; the public support definition changes once.
Record this exception in the reconstruction specification, plan and a new ADR
before implementation. It supersedes the prior decision to keep the definition
in the public package only to this stated extent.

The generator never owns `schema/optional.go`, its tests or the presence leaf.
For the canonical generated root `<module>/schema`, those hand-owned files
supply the support facade. For any other root, generate `models_presence.go`
with equivalent aliases/forwarders, and list that file in generated ownership.
Implementation shards import the shared presence leaf and never the public
facade, eliminating the package cycle.
Retain facade-local `modelRegistry`, `modelDecode`, `modelValidate` and
`modelBranch` forwarding helpers with their existing signatures, all forwarding
to the same root-owned registry. Existing complete-corpus and branch-error tests
must compile without weaker assertions or duplicate registry construction.

## Dependency layout and determinism

The graph must describe actual typed references emitted after shape/reference
resolution, including object fields, map and array results, and composition
method signatures and bodies. Attribute each declaration to its original
document even when its projected shape resolves into another document. Keep
the authoritative schema reference graph and its 14 recursive source groups as
a separate acceptance audit; it is not the Go package graph.

Use the existing source-bound emitter with a private optional rendering context.
A single child-name resolver records typed references at every field, return
type, child declaration and branch construction site; the context also selects
carrier access/commit, branch construction, registry and presence references.
A nil context retains existing legacy output. A fresh planning emitter records
dependencies/declarations and discards node source; a second fresh emitter
qualifies component references and emits the layout. Reconcile their complete
edge and declaration digests. Do not regex-rewrite generated source or build a
second schema semantic interpreter. Parse emitted Go to independently audit
declarations/imports and their manifest targets.

Assign SCC package names from a deterministic digest of their sorted full
document memberships; collision-check shortened names against full digests.
Within each component, emit one combined implementation Go file with sorted,
deduplicated imports and deterministic declaration order. Proposed P3 correction:
aggregate opt-in facade node groups into deterministic `models_aliases_NNNN.go`
chunks bounded at16MiB including formatted imports, as specified in
[the alias aggregation amendment](2026-11-07-go-partitioned-alias-aggregation-design.md).
The old per-node physical promise cannot fit64KiB argv. Default generator paths
and bytes remain exact. Preserve actual model-index fields path/pointer/name/
sha256 and values; each partition declaration maps to its actual owned chunk and
exactly one implementation target. Adoption of this correction is required
before P3 code, independently of current P0B1 work.

Emit a versioned partition manifest containing every source document/hash,
component/full membership digest, intercomponent import edge, declaration and
facade alias target, generated path and ownership. A manifest cannot attest its
own final byte hash; the surrounding generation result supplies that hash.
Fresh audits must reconcile all 1,071 documents, 6,745 references and 18,084
required nodes against current source. Counts are comparison points, never a
substitute for enumeration. Do not discard a node or split an SCC to meet a cap.

All shards depend only on their component dependencies, root-owned registry and
carrier, and copied shared validation/presence support. No registry-per-shard,
initialization injection, application dependency or global registration.

## Ordinary embedding and raw source ownership

Preserve raw bytes at every original `registry/<schema-path>`. A registry package
at that directory cannot directly embed all admitted top-level filenames: Go's
safe-argument checks reject some paths even after pattern escaping. Keep an
additional raw-source mirror under one deterministic safe ASCII child component
of `registry/`, selected against all admitted source paths and generated paths.
Embed only `all:<safe-component>` and use `fs.Sub` to recover the original
relative schema paths. This ordinary embed uses no Go overlay or extraction.

Select the first available `omraw`, `omraw1`, ... using Unicode simple-fold
component collision checks. Search at most 10,001 candidates (one beyond the
document bound). Distinguish file/directory conflicts as well as exact names.
The mirror contains only admitted raw files, never generated Go/control files.
Both physical copies count against file and output-byte bounds. Only the mirror
is embedded; the binary does not embed both physical copies.

The existing `embeddedSourcePath` admission still applies. Preserve hidden,
underscore, `testdata`, bracket, hash, percent and Unicode-letter names already
admitted; blocked source paths remain precisely attributed. Test raw hashes
through the registry's read-only source view and compare both physical copies.
If a source accessor is exposed for the new registry package it returns
`(fs.FS, error)` and propagates `fs.Sub` errors. The legacy generator has no
exported `RawSources` API to preserve. A private experiment's accessor signature
does not silently become the product API.

## Bounds, output safety and installation

Partitioned generation preflights at most 28,000 generated regular files,
16 MiB per file, 256 MiB aggregate bytes, and 240 bytes per filename component.
These are finite new-mode bounds; existing checkpoint/exporter 30,000-path
limits and all raw input, graph, numeric and cache limits remain unchanged.
Include both raw copies, helper code, facades, implementation, indexes and
manifests in the generated count. Check portable case-folded paths, symbol and
file/directory collisions, existing destinations and every ancestor symlink
before writing. A semantic, bound or collision failure writes nothing.

Build in a new staging directory; do not install partially validated output.
The final installer replaces only previous manifest-owned generated files and
preserves hand-owned support/tests and unrelated files. Validate the complete
ownership delta before replacing anything. Installation does not grant
permission to overwrite an unowned path.

## Acceptance and execution

Retain all accepted Task 1–5 tests, including default single-package emitted
fixtures. Add partitioned independent-module and consumer tests for every
public shape, conversions, presence, precise numbers, detached ownership,
transactional reuse, parent-first composition failures and cross-document
recursion. Explicitly assert the chosen defining-package differences. Prove
ordinary embedding with hostile admitted paths and reserved-prefix collisions.

Generate twice into clean independently copied original-path modules and compare
complete path/hash and partition manifests. Audit exactly-once declarations,
every alias target, every embedded source hash, all 14 recursive source groups
and all seven complete-corpus semantic groups. The complete corpus's workflow
`{}` must still match 17 branches and reject; AutoClassification must match three
and reject. Preserve direct ODCS vendor and recursive RDF typed traversal.

Before any new Go invocation, separately review a full-source execution protocol.
The small prototype controller's 500-file/4-MiB source cap, 128 capture cap and
256 total owned identities cannot simply cover full generated modules. A full
protocol must separately stream bounded complete source censuses, schedule
bounded package compilation using normal inherited caches, and preserve exact
process ownership, terminal/EOF evidence, resources and cleanup. No blind
monolithic retry or reuse of the spent prototype command release.

Keep four CPUs, the 16-GiB hard boundary, 15-GiB observed stop, 900-second command
timeout and 20-second cleanup. Do not clear caches, guess new GC budgets or
increase resource limits. Final independent ordinary/race tests, CLI build,
full-profile schema check, normal hooks, strongest whole-foundation review and
verified external backups remain required. Model completion does not establish
server/ingestion/connector/state parity or the approved performance gains.

## Design review and authority

The initial builder review found that a canonical schema root could request a
different package and conflict with protected support/tests. The explicit
configuration admission above closes that design gap; the implementation must
still prove it with a no-write negative test. This is a technical continuation
of the user's approved full migration and subagent-driven method. It changes
the internal Go foundation layout rather than Java/Python wire/state scope.
Implementation needs the reviewed concrete plan and per-command resource
release; this document alone does not authorize executing Go or accept Task 6.
