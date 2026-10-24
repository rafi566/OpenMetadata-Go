# Require admin authorization for the first native Go table reads

- **Status:** Accepted
- **Revisions:** v1 2026-10-24 (initial)
- **Deciders:** Implementation of the owner-approved incremental rollout
- **Guard:** Go differential/authorization/concurrency tests and independent review
- **Related:** ADR:2026-10-24-go-migration-retains-java-fallback-and-counts-total-resources

## Context

The first native slice reads plain table metadata directly from PostgreSQL. Resource permission results alone cannot authorize a later SQL snapshot: a concurrent metadata change can alter a conditional non-admin policy. The pinned Java revision reuses the entity resolved during authorization, so the Go path must preserve that protection.

## Decision

Keep every non-admin table request entirely on Java. For the measured Java revision `f38e3487`, verify effective admin authorization on every native request through `GET /api/v1/system/settings/openMetadataBaseUrlConfiguration`. This existing non-secret setting calls Java's `authorizeAdmin` and supplies the base URL needed for response links. Do not cache that decision. Persona and impersonation headers, including repeated or empty values, retain the original Java request.

Native reads initially support default fields and owners/tags for plain table metadata only. Assigned/inherited owners or tags, column references, ancestor retention, unknown fields, legacy shapes and oversized payloads fall back. PostgreSQL queries are read-only, parameterized and bounded: four connections, 32-entry statement/description caches, a 200 ms statement timeout, a 250 ms read deadline and 256 KiB native payloads. Cap native requests at four so completed SQL responses cannot accumulate unbounded projection work under the 64 MiB Go container budget. Overflow uses Java.

Stop both API runtimes before restoring the fixture, and resume only containers that were running. Treat failed Docker inventories as preflight failures before any mutation.

## Consequences

This slice can improve the measured admin workload while all endpoints and non-admin behavior remain available. It does not establish improved performance for ordinary office-user traffic. Supporting native non-admin reads requires authorization bound to the served snapshot, with conditional-policy race tests. A Java upgrade must revalidate the protected endpoint contract before enabling this experimental slice.
