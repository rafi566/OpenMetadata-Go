# Incremental Go backend

The current executable is the Java fallback for the approved incremental migration. Every route is forwarded to Java. It does not yet optimize table reads or meet a performance target.

The module path and Go 1.27.2 toolchain match `go/full-backend-reconstruction`. That branch's schema primitives remain separate and unchanged; this HTTP bootstrap does not replace schemas or generated models.

```bash
go test -race ./...
go vet ./...
JAVA_BACKEND_URL=http://127.0.0.1:8587 go run ./cmd/metadata-go
```

`JAVA_BACKEND_URL` must be an HTTP(S) origin without credentials, path prefix, query or fragment. `HTTP_ADDR` defaults to `:8585`. TLS verification uses the system CA bundle. Authentication, authorization, masking and writes still run in Java. The proxy preserves encoded paths, request/response bodies, auth context, cookies, error statuses and streaming responses; it does not add compression or cache responses.

The upstream connection pool is capped at 64. Header reads time out after 10 seconds, idle connections after 90 seconds, and SIGTERM drains requests for up to 30 seconds. There is no whole-response write timeout that would cut off long exports or event streams.

The Dockerfile uses the pinned Go image and a non-root scratch runtime with CA certificates. Keep the combined Java + Go CPU/memory budget equal to the baseline when measuring improvements. A Go-only resource figure cannot qualify the migration. See [the measurement record](../docs/perf/backend-java-go.md).
