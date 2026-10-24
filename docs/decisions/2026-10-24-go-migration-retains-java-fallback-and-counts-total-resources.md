# Migrate backend paths to Go incrementally and count the complete API runtime

- **Status:** Accepted
- **Revisions:** v1 2026-10-24 (initial)
- **Deciders:** Repository owner
- **Guard:** Differential API checks, benchmark comparison and reviewer
- **Related:** `docs/perf/backend-java-go.md`

## Context

The owner wants API RAM reduced by at least 15%, successful throughput increased by at least 20%, and CPU cost per successful operation reduced by at least 20%. The original Java build exposes 2,107 documented operations. Replacing a small API subset and omitting the remaining behavior would break existing clients.

## Decision

The owner selected an incremental migration on 2026-10-24. Go may implement selected paths while Java continues serving the remaining endpoints. Preserve the complete externally available API throughout the migration, including authorization, masking, validation, persistence and indexing semantics. Unsupported cases within a migrated path must retain Java behavior.

Measure the combined Java and Go API runtime, including proxies and sidecars, under the same aggregate CPU and memory budget as the baseline. Compare deployment tuning separately from implementation changes. Qualify memory and CPU at a common successful operation rate, and capacity at the same latency/error limits. Retain the original Java path for differential tests and rollback.

The initial fallback uses the Go standard library reverse proxy without response caching or automatic compression. Its upstream connection pool is capped at 64, matching the original Java active-request budget. A 10-second header-read timeout bounds slow headers, a 90-second idle timeout releases unused connections, and shutdown drains for up to 30 seconds. Leave whole-response write time unbounded to retain long exports and event streams. Java continues applying authentication, authorization and masking until a migrated path has differential coverage for those behaviors.

## Consequences

A useful first enhancement can ship before every endpoint is ported. A proxy alone is infrastructure progress, not a demonstrated performance improvement. Report the migrated cases, Java fallbacks and workload limits alongside measured results. Neither a Go-only memory figure nor faster failures can satisfy the targets.
