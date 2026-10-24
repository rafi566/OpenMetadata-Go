# The office preflight checks existing services without writing application data

- **Status:** Accepted
- **Revisions:** v1 2026-10-23 (initial)
- **Deciders:** Repository owner (external-service deployment scope); implementation author (initial resource budgets)
- **Guard:** `docker/kubernetes/test_preflight.py`, `docker/kubernetes/test_postgres.py` and Helm render validation
- **Related:** `docker/kubernetes/README.md`

## Context

The office has PostgreSQL of an initially unknown version and OpenSearch 2.19.x. The source snapshot uses an OpenSearch Java client that supports 2.x, but its integration tests default to a 3.4.0 server. Resource reduction and throughput improvement have not been measured.

## Decision

Reuse Helm chart 2.0.0 with explicitly supplied images from the fork. Keep endpoints and Kubernetes Secret names as placeholders. Read the same values for a separate preflight Job; do not introduce a chart wrapper or modify shaded clients. Require verified TLS, the PostgreSQL 12 version floor, pgcrypto/pg_trgm, migration-role privileges, and OpenSearch 2.19.x basic reads. Preflight SQL runs in a read-only transaction. It never migrates data or writes indexes. Helm installation is a separate, deliberate command.

Start with one API replica and HPA disabled. Initial requests are 500m/1Gi and limits 2 CPU/2Gi; heap is 256MiB initial/1GiB maximum, each weighted entity cache is 64MiB, the database pool is 20 maximum/2 idle, and QoS admits 16 requests. This leaves native-memory headroom and reserves database connections beyond request admission; these values require workload validation. A preflight Job gets 120 seconds, no retries and a 600-second post-completion TTL, keeping failed checks inspectable without leaving long-running resources.

## Consequences

The preparation can be reviewed without office credentials. Live preflight creates only a diagnostic Job; referenced Secrets stay in the selected namespace. Its success does not prove index creation permissions, PKCS12 truststore correctness, application migrations, semantic search or API compatibility. Validate those after startup on disposable/staging data. Resource targets remain API memory at most 85% and throughput at least 120% of a comparable baseline, including all API replicas/sidecars and unchanged latency/error bounds.
