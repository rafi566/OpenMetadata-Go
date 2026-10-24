# Local backend measurement

This profile runs the original Java source, PostgreSQL 15 and OpenSearch 2.19.7 on Docker Desktop. It does not connect to office services. The API has a 2 CPU / 2 GiB budget. Build and runtime run sequentially on this 16 GiB host.

Use the Linux baseline checkout at revision `f38e3487c729fe4663269bd367ed9a853fa9d3e6`. Keep its build output on the Linux filesystem; the Maven cache and Docker Desktop virtual disks are on D:. Invoke Compose from Ubuntu WSL so Linux source mounts resolve correctly.

Create ignored `.env` values for `BENCHMARK_SOURCE_DIR`, `BENCHMARK_M2_DIR`, `BENCHMARK_DB_PASSWORD` and `BENCHMARK_FERNET_KEY`. The last two must be private generated values. The Fernet key must encode 32 random bytes using URL-safe base64. Do not publish `.env`, tokens, database dumps or raw authentication responses.

From this directory in WSL:

```bash
docker --host unix:///var/run/docker.sock compose --env-file .env -f compose.yaml --profile build run --rm java-build
docker --host unix:///var/run/docker.sock compose --env-file .env -f compose.yaml up -d postgres opensearch
docker --host unix:///var/run/docker.sock compose --env-file .env -f compose.yaml run --rm api \
  java -cp '/source/target/benchmark-provided/*:/source/openmetadata-service/target/classes:/source/target/benchmark-libs/*' \
  org.openmetadata.service.util.OpenMetadataOperations -c /source/conf/openmetadata.yaml migrate --force
docker --host unix:///var/run/docker.sock compose --env-file .env -f compose.yaml up -d api
```

API: `http://127.0.0.1:18585/api/v1`; admin health: `http://127.0.0.1:18586/healthcheck`. The isolated fixture retains the source's default local admin account. Database/search ports are not published. The profile disables OpenSearch security only on its private local network.

## Fixture and runs

The current fixture was generated using the baseline's `bin/distributed-test/scripts/perf-test.sh`: 10,100 tables, four columns each, across three schemas. Its manifest and snapshots live under ignored `results/`:

- `fixtures/catalog-v1.json`: IDs, FQNs and schema counts for the workload.
- `private/catalog-v1.dump`: custom-format PostgreSQL snapshot.
- `private/search-snapshot.json`: metadata for OpenSearch repository `benchmark_fixture`, snapshot `catalog-v1`; the snapshot data is in the named `search-snapshots` volume.
- `environment/sample-detail.json`: pre-workload entity used to verify both restored stores.

These inputs describe this local dataset, not an office catalog. `restore.ps1` pins the saved dump hash and checks container ownership, all restored shards, the table count and golden values in both stores. It refuses to reset a fixture while a benchmark load container is running. Run it from Windows PowerShell with `docker.exe` on PATH:

```powershell
& .\scripts\backend_benchmark\restore.ps1
```

From the repository root in WSL, activate the required Python venv. Use a fresh output label for every invocation:

```bash
python scripts/backend_benchmark/run.py warm-java-a-50-r1 50 60
python scripts/backend_benchmark/run.py fixed-java-a-50-r1 50 180
```

The runner refreshes the local token before each run. It starts pinned k6 with 100 VUs, 1 CPU and 512 MiB, records cumulative API CPU and API/dependency/load-generator resource samples, and rejects errors, dropped arrivals, SLO failures, runtime restarts and OOM. Each logical write includes PATCH plus a persisted read-back. The operation mix is 40% detail, 20% list, 20% search and 20% write.

Restore before each repeat, then warm and measure without a restore between warmup and measurement. Preserve the restore ID and warmup label with each measurement. Use at least three repeats. Inspect actual successful rates as well as the offered rate; fixed-load comparisons require matching successful throughput. CPU capture includes the bounded container start/stop interval around the workload; its raw counter timestamps are retained.

## Tuned Java and interpretation

For B, recreate only the API using both files, then restore/warm/measure with the same fixture and workload:

```bash
docker --host unix:///var/run/docker.sock compose --env-file .env \
  -f compose.yaml -f java-tuned.yaml up -d --no-deps --force-recreate api
```

For A, recreate with `compose.yaml` alone. The tuning overlay maps the office Helm settings onto this direct Java invocation. Deployment tuning is reported separately from Go improvements.

`results/runs/<label>/` contains the k6 summary, sampled resources, sanitized container metadata, workload hashes and report. `valid_run` establishes workload/SLO validity, not a capacity boundary or a passing Java/Go comparison. Determine capacity separately by increasing offered load, then qualify the chosen boundary with restored repeated runs. Include every Java/Go API process in the final resource totals.

See [the measurement record](../../docs/perf/backend-java-go.md) for observed results and outstanding work.

## Go fallback compatibility

Build `openmetadata-go/Dockerfile` as local image `bettermetadata-go:gateway` before starting runtime services. The current build used a dedicated `docker-container` BuildKit builder capped with `memory=1g`, `cpu-period=100000`, `cpu-quota=200000`; the builder was stopped after the image was loaded.

Add `go-gateway.yaml` after the base and tuning files. It exposes Go on loopback port 18587 and splits the existing 2 CPU / 2 GiB API budget between Java and Go. It currently forwards every route to Java. Keep the direct Java port for local differential checks.

Supply both API containers when sampling this combined runtime:

```bash
python scripts/backend_benchmark/run.py smoke-go-fallback-01 10 20 \
  bettermetadata-benchmark-api-1,bettermetadata-benchmark-gateway-1 \
  http://gateway:8585/api/v1
```

This short cold run verifies integration and aggregate accounting only. Performance qualification still needs warmed repeated runs and a capacity boundary after business logic has actually moved to Go.

## Experimental native table detail

Build `bettermetadata-go:table-reads` from `openmetadata-go/`, then append `go-table-reads.yaml` to the three files above. It enables admin-only native plain-table reads against the pinned Java revision, using the same aggregate API budget. PostgreSQL credentials come from the ignored local environment file; plaintext database traffic is confined to this disposable Docker network.

Non-admins and all unsupported fields/metadata retain Java fallback. The office Helm profile uses Java until the experimental slice qualifies. See the exact supported cases and read-only/payload/concurrency bounds in [the Go README](../../openmetadata-go/README.md).

`restore.ps1` now stops and resumes a running gateway along with Java, preventing its PostgreSQL pool from surviving a fixture reset. Failed load/gateway inventory commands abort before mutation. Restore after mutation tests, then use fresh warmup/measurement labels and both API container names as above.
