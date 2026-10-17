# Go schema reconstruction preserves source identities and exact values

- **Status:** Accepted
- **Revisions:** v1 2026-10-17 (reconstruction authority and consumed interfaces)
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
