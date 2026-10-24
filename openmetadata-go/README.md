# Incremental Go backend

The executable keeps Java fallback for the approved incremental migration. By default every route is forwarded to Java. An opt-in table-detail reader is under differential testing; no Go performance target has been verified.

The module path and Go 1.27.2 toolchain match `go/full-backend-reconstruction`. That branch's schema primitives remain separate and unchanged; this HTTP bootstrap does not replace schemas or generated models.

```bash
go test -race ./...
go vet ./...
JAVA_BACKEND_URL=http://127.0.0.1:8587 go run ./cmd/metadata-go
```

`JAVA_BACKEND_URL` must be an HTTP(S) origin without credentials, path prefix, query or fragment. `HTTP_ADDR` defaults to `:8585`. TLS verification uses the system CA bundle. Authentication, authorization, masking and writes still run in Java. The proxy preserves encoded paths, request/response bodies, auth context, cookies, error statuses and streaming responses; it does not add compression or cache responses.

The upstream connection pool is capped at 64. Header reads time out after 10 seconds, idle connections after 90 seconds, and SIGTERM drains requests for up to 30 seconds. There is no whole-response write timeout that would cut off long exports or event streams.

The Dockerfile uses the pinned Go image and a non-root scratch runtime with CA certificates. Keep the combined Java + Go CPU/memory budget equal to the baseline when measuring improvements. A Go-only resource figure cannot qualify the migration. See [the measurement record](../docs/perf/backend-java-go.md).

## Experimental table reads

`GO_TABLE_READS_ENABLED=true` enables admin-only native `GET /api/v1/tables/{uuid}` for default fields and `owners,tags`, against the measured Java revision `f38e3487`. Each request first reads the non-secret base URL setting through Java's admin-protected settings endpoint. Non-admins always retain the complete Java GET, including conditional policies and its authorized entity snapshot. Neither auth decisions nor table responses are cached. Persona/impersonation headers, other parameters and unsupported metadata also fall back to the original Java request.

This first slice serves only plain tables: no assigned/inherited owners or tags, column references, parent retention, stored service references, incomplete change histories, unknown JSON properties or large payloads. Those cases retain Java behavior. Go reads PostgreSQL and forms the JSON response; writes, indexing, events, search and lists stay in Java. This is a limited migration case, not general table API parity. Native responses support simple gzip negotiation; quality parameters and uncommon encoding forms retain Java negotiation.

Use standard `PGHOST`, `PGPORT`, `PGDATABASE`, `PGUSER`, `PGPASSWORD`, `PGSSLMODE`, and `PGSSLROOTCERT` settings. Native requests are capped at four, matching the read-only pool. Statement/description caches hold 32 entries; statements time out at 200 ms, requests at 250 ms before fallback. SQL bounds combined table/service bytes before transfer, and projection also bounds combined input and serialized output to 256 KiB. Never enable this experimental profile against office services before compatibility/resource qualification; the office deployment still uses Java. Use verified TLS for office PostgreSQL.

Run real-store differential tests only against the disposable benchmark fixture, with `GO_TABLE_INTEGRATION=1` and `JAVA_BACKEND_URL` set. They verify both native admin projections, non-admin/denied-user fallback, owner/tag preservation, read-only connections and missing/invalid-token rejection. The mutation test creates fixture users/roles and refuses enabled SMTP. Restore the snapshot afterward. Ordinary `go test` skips environment-dependent tests.
