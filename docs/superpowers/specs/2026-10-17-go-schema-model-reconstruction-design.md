# Go schema and model reconstruction

## Authority and scope

The user approved migrating the entire Java backend and Python ingestion and
every connector to Go, selected subagent-driven execution, and subsequently
authorized continuation from the available checkout without manual recovery.
The historical specification commit and implementation tree are unavailable.
This document reconstructs the reachable schema/model requirements from that
authorization, baseline source, and attributed source salvage. It does not
claim that missing historical commits or their evidence were recovered.

The available source baseline is `2f0d4a4a42663d565b23c6018f098cfb07516fd6`.
Byte-matched complete files, complete transcript copies without historical
final pins, unapplied patches, and excerpts have separate private provenance.
Use those inputs where complete, then verify reconstructed behavior afresh.

This phase supplies a reusable schema registry, exact JSON support, and generated
Go models for the complete authoritative corpus. It is not full backend
acceptance. Contracts/reference capture, SQL/migrations, authentication and
authorization, all API and entity lifecycle behavior, search, jobs/workflows,
all ingestion/connectors, RDF, operator/MCP, packaging, upgrade/rollback, and
measured performance remain required later. Stateful jobs and workflows must
migrate without losing state. Performance acceptance remains RAM at least 30%
lower, p95 at least 20% lower, throughput at least 25% higher, CPU/operation at
most 5% worse, and each scenario p95 at most 5% worse. No improvement is claimed.

## Constraints

- The baseline JSON Schemas are authoritative. Do not repair, narrow, or relax
  them to simplify Go models. Never hand-edit generated output.
- Keep the generic registry strict and the legacy source profile explicit and
  source-bound. No implicit profile fallback, network retrieval, or temporary
  extraction for embedded schemas. Retain exact source paths and RFC6901 pointers.
- Use Go 1.27.2, Python 3.11.17 in an activated venv for Python work, and Node 22
  for applicable normal hooks. Pin `github.com/santhosh-tekuri/jsonschema/v6`
  to v6.0.3 unless a separately recorded, evidenced amendment justifies changing
  that dependency. Store no credentials or private runtime data in Git.
- Respect repository license, bounded-cache, schema-first, append-only migration,
  and normal commit-hook rules. Do not modify CI workflows or default production
  entry points in this phase. No deployment or force push.
- Every implementation unit needs meaningful RED/GREEN behavior checks,
  independent spec and quality review, and verified external checkpoints.
  Setup/compile failures are not feature REDs. Historical tests are not current
  test results. Unfinished processes have no asserted exit status.

## Registry and diagnostics

Retain the recovered `Node` fields `ID`, `Path`, and `Pointer` as strings and
`Document` as `json.RawMessage`; preserve the actual recovered public method
signatures for `LoadRegistry`, `LoadLegacyRegistry`, `Resolve`, `Nodes`,
`Validate`, and `Check`. Check reports Documents, References, Nodes, and actual
successful Compiled counts. Typed diagnostics identify stages and `ErrBlocked`.
Attempt independent nodes after failures; never report partial work as complete.

Collect applicable local resource identities separately from active assertions,
including recognized containers beneath ignored Draft7 reference siblings. Keep
unrelated ignored references and arbitrary annotation identities inactive.
Explicit raw-pointer selection remains supported: admit the selected schema,
effective descendants and newly reached local reference closure in an immutable,
bounded request-local view. Reuse source bytes without changing the loaded graph
or identities; a document-only cache hit cannot admit a different selected target.
An independently retrieved resource copy, including a root alias, preserves its
collected absolute base and effective draft, with draft-correct ID semantics. Relative IDs must not move
compilation away from the original physical targets covered by admission.
Preserve present malformed metadata in copies for canonical-metaschema rejection
at original source pointers; contextual normalization must not silently repair
invalid fields or replace ordinary invalidity with unsupported-semantics blockers.
Reject nonstring dialect declarations through the pinned canonical metaschema
before sibling evaluation can select a different arithmetic domain. This early
check sees only the original declaration within the existing admitted metaschema
scope and uses its collected fallback draft; native errors retain original source
attribution. It must not compile whole unadmitted source documents or inspect
unrelated annotation containers.

`LoadEmbeddedRegistry(source fs.FS, profile string) (*Registry, error)` consumes
the same bounded loader/index/resolver as disk loading. Empty profile uses the
retrieval root `file:///__openmetadata_embedded__/`; the only nonempty profile
is the explicit source-bound legacy profile. Sort valid relative source paths,
reject symlinks and nonregular files, confine resolution, copy raw data, and
preserve declared identity separately from retrieval identity. Bound documents
at 10,000, document/value bytes at 16 MiB, nesting depth at 256, and raw entries
at 1,000,000. Bound reads before allocation and reject duplicate JSON keys.

Preserve the fixes that ignore Draft7 `$ref` object schema siblings and treat
2020-12 `additionalItems` as an annotation rather than a schema child; earlier
drafts retain its applicable behavior. Freshly
characterize ignored Draft7 `$ref` sibling `patternDiagnostics` against the
pinned compiler, with active-pattern controls; correct any observed divergence.
Legacy regex compatibility needs finite, reproducible, source-bound policy and
independent Java behavior evidence. Rebuilt policy/data are new artifacts, not
missing historical evidence. Unsupported semantics block with precise locators.

## Exact values and presence

`Value` owns private immutable raw bytes, with `ParseValue([]byte) (Value,error)`,
`RawJSON() []byte`, JSON methods, `IsNull() bool`, `StringValue() (string,bool)`,
`BoolValue() (bool,bool)`, `NumberValue() (Number,bool)`,
`Object() (map[string]Value,bool)`, and `Array() ([]Value,bool)`. All ingress
and egress copy; views decode fresh and commit transactionally. Failed reuse
cannot retain stale decoded data. Unset serialization errors; null is a value.

`Number` privately retains the exact token with `ParseNumber(string)
(Number,error)`, `String() string`, `Int64() (int64,error)`,
`Uint64() (uint64,error)`, `IsInteger() bool`, and JSON methods. Preserve large
integers, arbitrary exponents, and negative zero without float conversion or
allocating enormous powers. Conversions check overflow using work bounded by
input token length; uninitialized and invalid tokens error.

`Optional[T]` has missing zero state, `IsSet`, `IsNull`, `Value`, `IsZero`,
`Some`, `Null`, and JSON support compatible with `omitzero`. Distinguish missing,
explicit null, zero, empty collections, and false. Defaults do not insert data;
required nullable members must still be present.

## Numeric validation frontier

Exact token retention is separate from safe dependent arithmetic. Before risky
compile/evaluation admit at most 10,000 mantissa digits and absolute explicit
exponent at most 10,000 per token. Joint aggregate cost is at most 1,000,000,
summing digits and absolute exponents across the selected physical schema
document's transitive reference closure and the instance. Use decimal text,
never floating point or huge powers. Schema traversal respects effective
draft/ref keyword activity, known assertions, cardinalities, and const/enum
descendants; unknown/default/examples annotations do not become assertions.

The dependency validates canonical metaschemas before compiling runtime
assertions. Separately admit numeric arithmetic required by those metaschemas,
including ignored Draft7 ref siblings, recognized schema containers beneath
them, and numeric descendants of uniqueness-checked enum/required/type/dependency
arrays where the declared canonical draft imposes uniqueness. Malformed array
elements need admission before the dependency's later type error. Use the union
of physical-document/RFC6901 numeric source locations required by effective
assertions and metaschema arithmetic; count each location once. The same joint
closure-plus-instance cost applies. Keep raw documents, compiler input, identities,
graph nodes and references unchanged; do not follow ignored references during
this traversal. Metaschema blockers identify that obligation explicitly. The preflight inherits
each compiler resource's dialect; a nested declaration switches it only at an
applicable ID-bearing resource, preserving Draft7 ref-object ID behavior.
Custom metaschema-selected vocabulary arithmetic domains are unsupported before
dependent arithmetic. An ordinary schema declaring a vocabulary while selecting
a canonical metaschema does not select a custom metaschema. Unknown/default/example
annotations remain outside blanket arithmetic scanning.

Effective nonnegative integral min/max Items, Length, Properties, and Contains
operands must fit checked int64 and platform int. Contains bounds apply only
in an active applicable contains context. Ordinary negative/fractional operands
remain metaschema-invalid; stored instance integers are not narrowed.

Out-of-budget arithmetic returns typed `ErrBlocked` at the exact source/schema
pointer and instance pointer where applicable. No false success, false invalid,
rounding, or panic-recovery-as-validation. Check admits each document closure
and continues independent nodes with truthful Compiled counts. Any per-Check
closure cache is bounded by document count (at most 10,000) and discarded.
The complete arbitrary-exponent arithmetic domain remains explicit later work;
this bounded admission is not a claim of complete numeric semantic parity.

## Generated models

Generate from every physical schema and its schema nodes deterministically.
Names derive from full physical path/pointer/kind. Reject model/helper/enum and
case-insensitive filename collisions with both source locators. Export Unicode
names correctly and preserve wire keys when Go struct tags cannot represent
them. Do not substitute an unchecked `map[string]any` for composition semantics.

Each named model wraps a private `Value`, validates its exact embedded node
before committing a fresh decode, errors when serializing unset, and exposes
`Validate() error` and `JSONValue() support.Value`. Object projections use
`NameObject` with exact-tag `Optional[*ChildName]` members and
`Object() (NameObject,bool,error)`. Arrays provide
`Items() ([]*ItemName,bool,error)`; primitives provide checked typed views.
One-level pointer projections avoid eager recursive expansion. Raw models own
lossless serialization; projections are detached read views and do not promise
to roundtrip unknown data independently.

For schema-valued additionalProperties provide
`AdditionalProperties() (map[string]*ChildName,bool,error)`. Validate the parent,
exclude declared and applicable pattern-matched keys, retain null as a nonnil
child containing null, and precisely block unsupported pattern semantics.
Unconstrained maps remain accessible through `JSONValue().Object()`.

Support all authoritative compositions, conditionals, nullable/type arrays,
open/untyped/nonobject values, all recursive strongly connected components,
and references. oneOf requires exactly one match: workflow `{}` with 17 matches
and AutoClassification values with three matches must reject. anyOf retains
raw data and all matching typed views; allOf enforces all constraints. Treat
unknown-container resultSummary targets as schemas, without invented instance
properties; misplaced schema-looking annotations stay draft-correct.

## Acceptance evidence

Freshly inventory the complete baseline corpus, references, nodes, and recursive
graph; the historical 1,071 documents and 14 recursive components are comparison
points, not a substitute for current enumeration. Check every admitted node and
resolve every reference. Generate into two independent clean directories and
compare bytes, compile both independently, and exercise semantic CreateTable,
Table, connections, entity references, extensions, timestamps, and nested
columns. Cover precision/presence/reuse/ownership, recursion, invalid unions,
unknown data, draft activity, collisions, and numeric blocker diagnostics.

Retain commands, terminal exits, outputs, manifests, exact BASE..HEAD, and review
findings in private evidence. Public source/runbooks go to the dedicated GitHub
branch with exact remote-SHA readback. Private source/evidence archives require
independent download/decode/size/SHA verification before the next dependent unit.
Use the committed resume runbook after a reset; do not delete the only evidence
copy at a skill's cleanup step.
