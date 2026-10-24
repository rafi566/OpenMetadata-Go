# Backend Java/Go measurement record

## Scope and acceptance

Enhance the Java backend incrementally with Go while retaining the REST/schema, authorization/masking, persistence, indexing and event behavior used by existing clients. On 2026-10-24 the owner selected Go for migrated paths with Java serving the remaining endpoints. The complete API remains available throughout; a faster health check or a partial CRUD service does not satisfy the performance objective. See ADR:2026-10-24-go-migration-retains-java-fallback-and-counts-total-resources.

Compare original Java (A), Java with the office Helm tuning (B), and Go (C). Attribute A→B to configuration and B→C to implementation; A→C is the overall result. PostgreSQL, OpenSearch, ingestion and frontend resources are outside the API-memory target, but their load/configuration must be recorded. Include all remaining Java/Go API containers and API sidecars during coexistence.

Acceptance requires API memory at most 85%, successful throughput at least 120%, and CPU cost per successful operation at most 80% of baseline, with equivalent behavior and unchanged agreed latency/error limits. The user added the CPU target on 2026-10-24. Resource limits and heap sizes are configuration, not measurements.

Memory and capacity need separate runs. For memory, hold successful request rate constant (the comparison helper permits 1% timing variation) and compare aggregate container working-set p95, alongside peak and RSS. For capacity, increase offered load and record the highest repeatable successful rate meeting the same latency/error limits. Never compare JVM heap alone to Go heap or call error responses improved throughput.

Measure CPU at the same fixed successful-operation rate as memory. Sum cumulative CPU nanoseconds across every API container, take the difference over the measured interval, and report CPU-seconds per 1,000 successful operations, alongside average CPU cores and throttling. Keep API CPU limits unchanged. Lower CPU usage caused by doing less work does not meet the target.

Keep a fixed fixture snapshot, request mix, auth identity, CPU allocation, replica count and dependency configuration. Restore the snapshot before write runs. Warm the runtime/caches, record cold startup separately, and collect at least three repeats with variation reported. The initial workload proposal is 80% reads/20% writes; workload-specific conclusions must be labeled accordingly.

## Existing tools and remaining work

`bin/distributed-test/scripts/perf-test.sh` generates metadata and exercises read/write/search paths. Its overall throughput divides entities created by wall time; individual collectors use the count of both successful and failed request durations. It also includes Java-specific diagnostics. Preserve it for fixture generation and diagnostic context; do not use that overall number as a language-neutral capacity result.

`scripts/backend_benchmark/measure.py` is the Linux Docker resource collector and comparison helper used by `run.py`. It subtracts inactive file memory for working set, records RSS/CPU/throttling, and refuses missing, invalid or mismatched comparisons. Container sampling, workload validation, report assembly and restored Java A/B fixed-load repetitions have run against real services. Capacity qualification and the final Go comparison remain pending.

The user requested Docker for execution. `docker/benchmark/compose.yaml` prepares a constrained Maven builder (2 GiB / 2 CPU, JVM heap 1 GiB), separate Java API (2 GiB / 2 CPU, matching the source launcher's default 1 GiB heap), PostgreSQL (512 MiB / 2 CPU) and OpenSearch (1.5 GiB / 2 CPU, JVM heap 512 MiB). During fixture generation the initial OpenSearch 1 GiB / 1 CPU limit reached approximately 982 MiB and 88% of one core, while API CPU was approximately 35% of one core. Dependency limits were increased before qualifying runs; these fixture-generation observations are calibration, not Java/Go results. All image digests are pinned. Only API/admin ports are published, on loopback. Database/search traffic is plaintext inside the local Docker network; this is a local fixture profile, not the office verified-TLS deployment profile. Builder and runtime must run sequentially on this host.

Set `BENCHMARK_SOURCE_DIR` to the unmodified Linux baseline checkout, `BENCHMARK_M2_DIR` to a writable cache, and generate private `BENCHMARK_DB_PASSWORD` / `BENCHMARK_FERNET_KEY` values in ignored `docker/benchmark/.env`. This host uses `/home/rafi566/.cache/bettermetadata-baseline/source` and `/mnt/d/BetterMetadataBenchmark/maven-cache`, running Compose through Ubuntu's Docker client connected to Desktop. An unused NTFS source copy is not the active checkout. The profile starts no office services. `build-java.sh` checks the baseline source SHA/working tree, builds the real server and copies dependencies. Its standalone classpath includes the source-declared provided Servlet 6 API before Felix's bundled Servlet classes; omitting that API initially caused real HTTP 500 errors. The Java source and POMs were not changed. Docker configuration, build, migrations, authentication and catalog read/write/search smoke checks now pass.

## Environment preparation — 2026-10-24

| Item | Observed state |
|---|---|
| Baseline source | `f38e3487c729fe4663269bd367ed9a853fa9d3e6` |
| Work branch | `codex/backend-measurement-go`, based on Helm-preparation commit `03fd423` |
| Host | Windows 11 Pro, Ryzen 7 5700X, 16 logical CPUs, approximately 16 GiB RAM |
| Local Linux | Ubuntu 24.04 under WSL2, kernel 5.15.153.1, approximately 8 GiB assigned RAM |
| Java build / Maven | Docker Temurin JDK 21.0.10 / Maven 3.9.12; earlier native attempt used Ubuntu OpenJDK 21.0.12.1 / Maven 3.8.7 |
| Java runtime | Temurin JRE `21.0.12.1+1`, identical pinned image for A and B |
| Docker tools | Ubuntu Engine 29.1.3; Docker Desktop 4.96.3 with Linux Engine / Windows CLI 29.9.2 and Compose 5.6.1; Desktop `hello-world` smoke passed |
| PostgreSQL | `postgres:15.19-alpine`, digest `sha256:a8e042598834300dfaa17a54f695b87b7f25d3490433bbbe2ef3bffbb9747f24` |
| OpenSearch | `opensearchproject/opensearch:2.19.7`, digest `sha256:1f81bb6a552637d6f551baeb8d8fad5ed969a0577374e76af14d1131ab750cd9` |
| Load generator | `grafana/k6:2.3.0`, digest `sha256:9c2dee7f8ed74d317e4027c06a10f169b625638189de8d4555d0b3486a5aeb34` |

The Linux source is `/home/rafi566/.cache/bettermetadata-baseline/source`; the build log is `/home/rafi566/.cache/bettermetadata-baseline/java-build.log`. Task-local `scripts/backend_benchmark/maven-settings.xml` directs Central to its canonical HTTPS endpoint after the existing mirror stalled; it does not change Java source or dependency versions.

The build reached module 7/7 after compiling common/spec and packaging the shaded search clients. During service dependency/build work, host available RAM fell to approximately 240 MiB and Ubuntu command execution stopped responding. Subsequent host readings showed partial memory recovery, while guest `/proc/meminfo` still reported available memory; memory pressure alone is not an established root cause of the WSL execution failure.

The original build launcher was interrupted, but guest PID 557 initially remained present and a targeted termination request did not return. The subsequently authorized WSL recovery stopped the old build; no Maven process was present in the successful post-recovery inventory, and the build log still ended at service module 7/7. No test database/search containers or API runtime had been started. C: had approximately 3.2 GiB free after Docker installation; keep image storage and new build caches on D: and verify host RAM before running the full stack.

Initially the Windows Docker Desktop service was registered but stopped, its program/CLI paths were missing and no Docker named pipe was present. The user subsequently requested installing the downloaded Docker Desktop on D:. The signed Docker Inc installer installed version 4.96.3 to `D:\DockerDesktop`; CLI 29.9.2 and Compose 5.6.1 execute successfully. Temporary extraction also uses D:. A stale registration for the missing C: installation prevented relocation; that registration was exported before removal. Application settings were backed up and their other values preserved.

The installer records `wslDefaultDataRoot=D:\DockerData\wsl`. Existing settings overrode that default, so the stopped application's `CustomWslDistroDir` was also set to that path, with `DataFolder=D:\DockerData\vm-data`. Startup reported `Wsl/Service/CreateInstance/E_FAIL` and `HCS_E_CONNECTION_TIMEOUT`. The user explicitly authorized restarting WSL, including stopping Ubuntu and Docker processes. Graceful shutdown and service restart stalled; terminating the identified, stop-pending WSL service process allowed it to recover. Ubuntu command execution now succeeds. Windows was not restarted and no Docker data reset was performed.

The Desktop engine is running. Both `D:\DockerData\wsl\main\ext4.vhdx` and `D:\DockerData\wsl\disk\docker_data.vhdx` exist. An explicitly addressed local Desktop engine successfully pulled and ran `hello-world` with 32 MiB / 0.5 CPU limits and `--rm`, using an isolated empty client configuration rather than changing saved credentials. Engine inspection reports Linux amd64, cgroup v1, 16 logical CPUs and approximately 7.7 GiB VM RAM. This qualifies basic Docker execution only; it is not an OpenMetadata measurement.

## Results

The bounded Docker build completed with exit 0 and no OOM: 3 min 29 sec for the reactor, followed by dependency packaging. The running API reports version `2.0.0-SNAPSHOT` and revision `f38e3487c729fe4663269bd367ed9a853fa9d3e6`. Login succeeds; an unauthenticated table request returns 401. Creating 100 smoke tables, list/detail reads, exact-ID search and a description PATCH followed by a separate persisted read all passed. A later restart became ready for an authenticated catalog read about 22.3 seconds after Docker process start, with warm dependencies; raw timestamps are retained.

Reusing `perf-test.sh` added 10,000 tables. The observed total is 10,100: 100 in `public` and 5,000 each in `schema_000` and `schema_001`. The exported fixture has SHA-256 `66f7602b2935cf0ee651e345bc22a178cd4f16cdc6a65bbe7ab5d41d9203c913`. With the API stopped, PostgreSQL was dumped and OpenSearch snapshot `benchmark_fixture/catalog-v1` completed successfully with 92 indices and no failed shards. Snapshots and tokens stay in ignored private artifacts; restore both stores before repeated write workloads.

The workload validates entity IDs/FQNs, schema totals, columns, deletion flags and search shard status. Each write operation includes a separate read-back. The mix is 40% detail, 20% list, 20% search and 20% write operations; writes therefore issue two HTTP requests. Throughput counts valid logical operations. Write descriptions include a run-specific epoch so warmup cannot turn measurement writes into no-ops.

The second k6 smoke passed 101 valid operations with no errors or dropped arrivals. A later 20-second pilot passed 200 operations, with working-set p95 1,416,855,552 bytes and 24.06 CPU-seconds per 1,000 valid operations. These are instrumentation checks, not qualifying comparison results. An expired-token pilot produced only 401 responses and was rejected rather than counted as capacity.

Restore `23b4d60b98ea45168882fabfa4491672` reset the PostgreSQL fixture and all 92 OpenSearch shards, then verified the saved table version, description and update timestamp through both stores. The admin health check reported the server, database and deadlock checks healthy. Each repetition restores both stores, warms for 60 seconds and measures for 180 scheduled seconds, with k6 offered rate 50 logical operations/second. Observed successful rates were approximately 48.6–48.7, within 0.4% across A/B runs; use those actual rates for comparability. Completion timestamps include request drain rather than assuming the offered rate was achieved.

`docker/benchmark/java-tuned.yaml` maps the office Helm tuning to this source-classpath runtime, including its smaller initial heap, connection pool, bounded entity cache, QoS and search batch size. The heap setting uses `JAVA_TOOL_OPTIONS` because this profile invokes Java directly. Resource limits, source, JRE and dependencies remain the same as A.

| Stage | Evidence | Status |
|---|---|---|
| Measurement-helper calculations | 33 pytest cases (including two Linux builder guards), 10 Node contract/schedule cases, 3 PowerShell restore-failure cases | Passed; review's invalid-run comparison, CPU-rate matching, baseline-source integrity and late snapshot-preflight findings were fixed and rechecked |
| Java A | Three restored, warmed fixed-load runs, approximately 9,000 valid operations each | Memory/CPU measured; capacity pending |
| Java B | Same three-repeat protocol with Helm tuning | Memory/CPU measured; capacity pending |
| Go C | Transparent Java fallback implemented and integration-smoked; no business path migrated yet | Compatibility bootstrap passed; no performance comparison |
| Resource/performance targets | Tuning reduces median working set 32.2%; CPU cost increases 6.7%; maximum throughput unmeasured | Overall target not met |
| Office Kubernetes | Endpoints/Secrets not supplied; no office services contacted | Not run |

### Fixed-load measurements

Values below are medians of three per-run results. Each run passed every operation's p95 ≤500 ms / p99 ≤1,000 ms limits, with zero invalid operations, dropped arrivals, runtime restarts or OOM. Working set is sampled container memory, not JVM heap. CPU covers the recorded container interval surrounding the load run and is normalized by valid logical operations.

| Metric | Java A | Tuned Java B |
|---|---:|---:|
| Working-set p95, MiB | 1,359.4 | 921.6 |
| Working-set p95 range, MiB | 1,354.2–1,369.8 | 839.5–955.6 |
| CPU-seconds / 1,000 valid operations | 9.434 | 10.070 |
| CPU cost range | 9.292–9.492 | 9.690–10.269 |
| Valid operations/second | 48.695 | 48.594 |
| Logical-operation latency p95 / p99, ms | 35 / 53 | 37 / 55 |

Raw artifacts are retained locally under ignored `docker/benchmark/results/runs/fixed-java-{a,b}-50-r{1,2,3}/`, including their restore IDs and warmup labels. The summary checks matching fixture/dump/snapshot/workload/contract identifiers, runtime image and dependency budgets. Load-generator CPU p95 was below 0.08 cores in B, leaving substantial headroom under its 1-CPU limit. These workstation results do not establish office-cluster behavior.

### Analysis and Go work

The tuning profile meets the RAM threshold on this fixture, including its highest observed memory result. It does not meet the CPU target; its CPU range is above A's and its median latency is slightly higher. Smaller configured heap/pools alone therefore do not demonstrate the overall enhancement. Profiling is needed to attribute the CPU difference rather than assuming a cause.

A separate, non-qualifying Java Flight Recorder capture collected 276 Java execution samples and allocation samples during warmup/login and workload activity. It includes Jdbi SQL parsing, Jackson serialization and Jetty request handling. The capture includes bcrypt login work and is not a steady-state CPU-share measurement. It identifies SQL/result mapping and table-response construction as candidates for a focused per-operation profile; it does not prove which dominates the mixed workload.

The built OpenAPI asset contains 1,593 paths, 2,107 operations and 1,240 schemas (SHA-256 `214a3b4e4aebefc3c1874f0fca930fdef63479e7aaff54d3be2cef8ce0fb5efc`). The approved rollout keeps Java fallback for the complete API while Go paths are implemented and checked against it. The existing Go reconstruction branch contains schema primitives, not an HTTP backend; preserve that work and its module/toolchain choices.

### Go fallback bootstrap

The Go 1.27.2 fallback uses the standard library reverse proxy. Race tests and `go vet` pass. HTTP boundary tests cover encoded paths, exact JSON numbers, auth/persona/impersonation headers, cookies, 401/403/404 responses, streaming and safe backend errors. A regression ensures the proxy does not introduce gzip negotiation when the client omitted it. Real HTTP 101 tests cover WebSocket draining and forced tunnel closure at the shutdown deadline, because `http.Server.Shutdown` alone omits hijacked connections. Its rebuilt non-root runtime image is 10,874,884 bytes, ID `sha256:272fa1fa7f73004ffd57ab8ed8b2a6e4cf092a7addbd0d739ec1b5ac1d7331b5`; this is image size, not RAM usage. The dedicated BuildKit container was verified at 1 GiB / 2 CPU with no OOM and stopped before restarting the runtime.

With real PostgreSQL/OpenSearch, Go login succeeded and version/detail/list/404 response bytes matched Java. Missing and invalid tokens returned 401. A cold 20-second integration smoke completed 200 valid operations with zero errors/drops. The resource runner counted Java and Go together: 10.7032434 + 0.1243638 = 10.8276072 CPU-seconds. This cold smoke is not comparable to the warmed fixed-load results. After the WebSocket fix, the rebuilt image passed login and the same byte-level comparisons, exited 0 on SIGTERM without OOM, and restarted successfully. The earlier resource smoke used the pre-fix gateway image and is only accounting evidence.

`go-gateway.yaml` keeps the aggregate API budget at 2 CPU / 2 GiB: Java 1.5 CPU / 1,984 MiB and Go 0.5 CPU / 64 MiB. Combined resource sampling sums simultaneous working sets and cumulative CPU counters, rather than reporting Go alone. All application routes still execute in Java; these checks establish the migration boundary, not an enhancement result. Non-admin permission/masking cases require live differential coverage before any authorization-sensitive fast path is enabled.

Next: profile the selected read paths, implement their compatible Go behavior, and qualify capacity and combined Java/Go resource use. A gateway alone is not a performance enhancement. Keep migrated cases, Java fallbacks and unresolved compatibility gaps visible.
