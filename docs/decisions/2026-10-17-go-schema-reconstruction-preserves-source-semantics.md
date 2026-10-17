# Go schema reconstruction preserves source identities and exact values

- **Status:** Accepted
- **Revisions:** v1 2026-10-17 (reconstruction authority and consumed interfaces) · v2 2026-10-17 (source-bound registry and dependency arithmetic admission) · v3 2026-10-17 (selected schema admission and collector identities) · v4 2026-10-17 (independent resource base preservation) · v5 2026-10-17 (metadata validity preservation) · v6 2026-10-17 (canonical dialect rejection before sibling arithmetic)
- **Deciders:** Migration controller, applying the user's approved full migration and authorized reconstruction
- **Guard:** Reviewer; focused behavior tests and independent compilation required by the reconstruction plan
- **Related:** [reconstructed specification](../superpowers/specs/2026-10-17-go-schema-model-reconstruction-design.md); [implementation plan](../superpowers/plans/2026-10-17-go-backend-reconstruction.md)

## Context

The previous migration worktree and local Git objects became unavailable.
Some complete source files match retained historical hashes; other inputs are
transcripts, patches, or excerpts. Earlier related decision records are missing.
This new record attributes the retained decisions without inventing their old
documents, accepted commits, or test evidence. It establishes requirements for
new implementation; no reconstructed code has passed acceptance yet.

## Decision

Use the unchanged baseline JSON Schemas as the source of truth. Preserve physical
path, pointer, declared identity, raw data, and draft semantics. Generic loading
is strict and local; legacy interpretation requires an explicit profile bound
to unchanged source. No defaults, discarded constraints, implicit profile
fallback, or authoritative schema edits may make generation appear successful.

Keep `Value` and `Number` in `openmetadata-go/internal/schema`, presence support
in the public `schema` package, and the module path
`github.com/rafi566/OpenMetadata-Go/openmetadata-go`. Retain private owned raw JSON
and exact numeric tokens; checked views cannot round values or allocate enormous
powers. Missing, null, and zero remain distinct. Failed decoding preserves prior
state; successful reuse starts fresh. Detached typed projections do not replace
the raw model as serialization owner. Unset values cannot masquerade as null.

Generate names from physical schema identity, not display titles. Preserve wire
keys and reject symbol and filename collisions. All generated models validate
their exact original schema node before committing decoded state. Composition,
map, recursive, and full-corpus behavior require their own tests and review.

Bound raw decoding, source traversal, caches, numeric dependency admission, and
generation as specified in the reachable specification and plan. Exact token
retention does not certify complete arbitrary-exponent validation. Unsupported
semantics produce attributed blockers; they cannot become false successes,
rounded values, or recovered panics presented as validation.

## Consequences

Recovered originals remain unchanged in private provenance. Reconstructed source
uses this reachable citation and needs fresh tests, independent review, and
verified external checkpoints. No endpoint, connector, upgrade, full-migration,
or performance acceptance follows from this record or schema/model completion.


## Amendment v2 — source-bound registry and numeric dependency admission

This amendment attributes the recovered legacy interpretation and numeric
admission decisions to this reachable record. Their complete original records
remain private recovery inputs; missing historical decisions are not recreated.

Generic identities remain strict and local. The explicit legacy profile
`openmetadata-2f0d4a4a` binds every raw schema to baseline
`2f0d4a4a42663d565b23c6018f098cfb07516fd6`, the pinned raw manifest, physical
`https://open-metadata.org/schema/` paths, and declared identity metadata.
Physical identities take priority over declared aliases; ambiguous aliases fail.
No network or filesystem fallback retrieves references. Returned raw node bytes
are copies. Private locator keys escape physical-path separators independently
of unchanged public paths and RFC6901 pointers.

The regex policy is newly produced from unchanged source and finite, bounded
Java 21 development observations. Java `find` is compared to every Go search;
Java `matches` is retained separately. This evidence does not introduce Java as
a server dependency. Generic unsupported regex syntax remains attributed rather
than silently selecting a backtracking engine. Draft7 reference siblings and
2020-12 removed `additionalItems` remain distinct from earlier active drafts.

Before dependent compilation or evaluation, admit at most 10,000 mantissa digits
and absolute explicit exponent 10,000 per numeric token, with joint cost at most
1,000,000 across the physical reference closure and instance. Effective known
numeric assertions and const/enum descendants retain their draft semantics.
Effective nonnegative integral cardinalities and lengths must fit checked int64
and platform int; ordinary negative/fractional operands retain metaschema errors.
Raw Number and Value storage keep exact tokens independently of these budgets.

Pinned compiler metaschemas also perform arithmetic before ignoring Draft7
reference assertions or rejecting malformed elements of uniqueness arrays.
Admit those canonical metaschema obligations separately, including recognized
schema containers under ignored siblings. Union physical-document/pointer
numeric locations with effective assertion locations, counting each once.
Distinct metaschema blockers identify that obligation; inactive cardinalities
acquire no platform-int width restriction. Raw input, graph membership, identity,
reference resolution and compiler input remain unchanged. Unknown/default/example
annotations acquire no blanket numeric assertions. Custom metaschema-selected
vocabulary arithmetic remains unsupported through explicit canonical-draft
admission; an ordinary canonical schema's own vocabulary declaration does not
select a new metaschema.

Select nested drafts using the pinned compiler's resource collector: a nested
declaration requires an applicable resource ID, including the Draft7 reference
object ID rule and fallback draft. Ignore declarations in unknown annotation
ancestors. Resource discovery and metaschema traversal have different purposes;
an explicit target inherits the collector's resource draft even when its source
container is a removed assertion. Share this selection with numeric admission
without adding graph nodes or rewriting raw source.

Discover collector-visible local resource identities independently of active
assertions. A reference may select a resource beneath an ignored Draft7 sibling;
unrelated sibling references and arbitrary annotation IDs remain inactive.
For an explicitly selected raw pointer outside the loaded graph, copy bounded
entry metadata and maps into a request-local view, mark its effective descendants,
and resolve newly reached local reference targets before arithmetic admission.
A document cache hit cannot admit a different selection. Immutable source bytes
are shared; request selection cannot mutate the loaded graph, identities or raw
documents. Physical source locations retain joint numeric union accounting.
An independently retrieved scoped-resource copy carries its actual collected
draft, including when its raw nested declaration was ignored by ID/ref fallback.
The original physical compiler document and raw schema bytes stay unchanged.
Preserve the collected absolute base in that copy's applicable `$id` as well;
reapplying a relative path ID would move its inner references to different
physical targets. Draft7 reference-object IDs retain their ignored semantics.
Admission and compilation must resolve the same original source targets.
Root aliases use the same independent-copy rule; retrieval through an original
physical URL keeps its original compiler input.
Only absent or string-typed metadata receives contextual string replacements.
Present malformed `$schema` or `$id` types stay in independent copies for the
pinned canonical metaschema to reject at their original source locations.
Projection must not repair invalid metadata or turn ordinary invalidity into
unsupported-semantics blockers; no separate canonical validator is introduced.

Nonstring `$schema` in a detached resource would select the compiler's default
draft instead of its inherited draft. Within the existing metaschema admission
scope, reject this metadata before compiling any source siblings: submit only
the original `$schema` value to the pinned compiler's canonical metaschema with
the collected fallback draft. Its string-type check returns before arithmetic
or traversal of the malformed value. Preserve the native canonical error and
attribute it to the original physical source pointer. This does not duplicate
canonical validation rules, compile unadmitted original documents, or scan
unknown annotation containers. Ordinary invalid metadata is still invalid,
not unsupported arithmetic; valid and absent declarations keep their existing
scope. Early rejection never contributes a successful requested Compile count.

A Check-local document-closure cache is bounded by admitted documents (at most
10,000) and discarded. Check continues independent nodes and counts only actual
successful Compile calls. Instance blockers include their escaped pointer.
Arbitrary-exponent validation, custom arithmetic domains, dynamic scope and full
migration parity remain explicit frontiers; bounded admission is not semantic
acceptance of every exact raw token.
