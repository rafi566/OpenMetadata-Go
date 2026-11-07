# Go model partitions share presence and preserve wire semantics

- **Status:** Accepted
- **Revisions:** v1 2026-11-07 (explicit partition layout and shared presence prerequisite)
- **Deciders:** Migration controller, applying the user's approved full migration and delegated implementation
- **Guard:** Reviewer; default-output characterization, Optional tests, independent partition consumers and complete-corpus/resource gates
- **Related:** ADR:2026-10-17-go-schema-reconstruction-preserves-source-semantics; [partition design](../superpowers/specs/2026-11-07-go-partitioned-model-generation-design.md); [implementation plan](../superpowers/plans/2026-11-07-go-partitioned-model-generation.md)

## Context

The complete monolithic generated Go package reached the selected compilation
memory stop. A finite private representation experiment passed its consumer
and conversion controls. Complete production generation, ordinary embedding,
full semantics and backend performance remain unproven. Aliasing implementation
packages requires a presence leaf to avoid a facade/import cycle.

## Decision

Keep the existing GenerateOptions/Generate API and default single-package output.
Add an explicit partitioned API/CLI mode. Condense the actual emitted typed
dependencies by physical document SCC before creating packages; facade aliases
retain public spelling, exact typed signatures and JSON semantics. Each root
owns a distinct raw carrier and one registry, preserving admitted within-root
raw conversions while rejecting cross-root conversions. Default validation,
source identity, precision, ownership and wire/state requirements remain binding.

Amend only the earlier record's requirement that Optional's definition live in
the public schema package: copy its exact algorithm into internal/schema/presence
and retain public aliases/forwarders. This is hand-maintained support, never
generator/installer-owned. Keep optional_test.go byte-identical. This relocation
deliberately changes defining package/private provenance/reflect/fmt/default gob
identity for ALL Optional consumers, including default-layout clients. It is
not an opt-in identity promise. There is no deployed Go foundation compatibility
claim; Java/Python data, jobs and workflow state still require migration parity.

Partitioned raw models also deliberately acquire implementation defining package
paths. Do not promise binary or reflection identity. Preserve every named model,
object and constant, raw owner and strict original-node validation. No defaults,
flattened constraints or unchecked public constructors may replace semantics.

Preserve original registry/<schema-path> bytes and use one additional safe raw
mirror for ordinary embedding. Both copies count against the new-mode 28,000
file, 16-MiB/member, 256-MiB output and 240-byte component bounds. Existing 30,000
export/checkpoint paths and all source/numeric/cache/resource limits remain.
Block before writes on collisions, unsafe paths, incomplete graph or overflow.
Install only manifest-owned generated output, preserving support and tests.

## Consequences

Applications keep the public model spelling and behavior; compilation can be
scheduled by actual dependency components. Raw source mirroring costs generated
disk/archive bytes without embedding the original copy twice. Global Optional
and opt-in model defining identity changes are explicit compatibility costs.

The private tiny result cannot accept the full layout. Twice-clean original-path
modules, every source/node/reference, all recursive and semantic groups, ordinary
embedding, final ordinary/race/build/schema checks and independent review remain
required. New full-source/process supervision and exact bounded command releases
must precede Go execution; no monolithic retry or resource cap increase follows
from this decision. Full backend/ingestion/connectors/state and measured
performance acceptance remain separate later gates.
