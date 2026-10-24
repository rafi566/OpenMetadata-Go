# Office Kubernetes deployment

Use the existing PostgreSQL instance and OpenSearch **2.19.x** cluster. This profile adds the OpenMetadata API and ingestion Jobs, using the official Helm chart **2.0.0**. It does not install a database, search engine, Airflow, Redis, or an operator/CRDs.

The source checkout is `2.0.0-SNAPSHOT`; supply server and ingestion images built from the same fork revision. The chart version is a template/configuration pin, not proof that every snapshot feature works on OpenSearch 2.19. The existing Java client supports OpenSearch 2.x, but this repository's default integration-test engine is 3.4.0. Run the application tests below against 2.19 before promoting the deployment.

## Fill the values and prepare Secrets

Copy `values-office.yaml` to `values-office.local.yaml` in this directory (the local copy is ignored). Replace every `REPLACE_ME` value, including the image repositories/tags, database, usernames, JWT key ID, endpoints and Secret names. For private registries set both `imagePullSecrets` and `pipelineServiceClientConfig.k8s.imagePullSecrets` to your registry Secret as supported by the chart. Endpoint fields take hostnames without `https://`, paths or ports; set the separate port fields to the actual service ports, including 443 where applicable. Keep a dedicated database and a unique `clusterAlias` per environment; the supplied `office_staging` prefix must not overlap another installation.

Create the referenced Secrets in the **same namespace** as the release, using your existing secret-management process:

| Reference in values | Required keys |
|---|---|
| `database.auth.password.secretRef` | `password` |
| `elasticsearch.auth.password.secretRef` | `password`, `truststore-password` |
| `fernetkey.secretRef` | `fernet-key` (a generated Fernet key, preserved across upgrades) |
| `extraVolumes` → `jwt-keys` | `public_key.der`, `private_key.der` (persistent RSA public/private keys) |
| `extraVolumes` → `office-ca` | `postgres-ca.crt`, `opensearch-ca.crt`, `opensearch-truststore.p12` |

Use the real CA chains, including intermediates. Build the PKCS12 truststore from the OpenSearch CA chain with Java `keytool`; its password must match `truststore-password`. Both the PEM CA and the PKCS12 store must trust the same server chain. No TLS bypass is provided. PostgreSQL uses `sslmode=verify-full` and OpenSearch uses HTTPS with Basic authentication. IAM/SigV4 authentication needs a different connection profile. The probe verifies the PEM CA; application startup must also validate the PKCS12 truststore/password.

The DBA should create a dedicated database, install `pgcrypto` and `pg_trgm` there, and give the application/migration role USAGE and CREATE on `public`, plus ownership of existing OpenMetadata tables/sequences. The preflight reads the unknown server version and checks the documented PostgreSQL 12 floor; this is not a substitute for running the actual migrations on that PostgreSQL version. A failed extension check prints an action for the DBA; it never installs extensions itself.

## Render and run the preflight

Use Python 3.10+ in a virtual environment with PyYAML (`python -m pip install PyYAML`). For this repository activate `env` first: `source env/bin/activate` on Linux/macOS, or `.\env\Scripts\Activate.ps1` in PowerShell. The launcher also needs `kubectl` when using `--run`.

From the repository root, render the Job without contacting Kubernetes:

```sh
python docker/kubernetes/preflight.py --values docker/kubernetes/values-office.local.yaml --namespace openmetadata-staging > docker/kubernetes/preflight-job.json
```

Create the namespace and Secrets through your normal cluster provisioning process, then run:

```sh
python docker/kubernetes/preflight.py --values docker/kubernetes/values-office.local.yaml --namespace openmetadata-staging --context YOUR_OFFICE_CONTEXT --run
```

The explicit context prevents accidental use of another current cluster. The caller needs permission to read the referenced Secrets, create/get/watch Jobs and read Pod logs in that namespace. Secret values are not printed or embedded in the generated Job. The Job has no Kubernetes API token; it only mounts CA material and receives database/search credentials through Secret references.

The Job uses `postgres:15-alpine` for psql and `python:3.13-alpine` for the search probe. Ensure the nodes can pull these images, or edit the generated Job to use your approved mirrors and execute that reviewed manifest instead. Allow namespace egress to DNS, PostgreSQL and OpenSearch; the probe Pod has component label `preflight` and uses the namespace's default service account. If your API has more restrictive identity/network policies, give the reviewed probe manifest the same relevant policy before treating its network result as representative.

PostgreSQL queries run inside `BEGIN READ ONLY` and check version, writable-primary settings, schema privileges, extensions and existing table/sequence ownership. OpenSearch checks authenticated `GET /`, requires the actual engine/version to be OpenSearch 2.19.x, then reads `/<clusterAlias>*/_search` with `size=0`. Redirects and invalid certificates fail. The search role needs permission to read that prefix. No table, extension, index, alias or search pipeline is created. Index creation/mapping and write permissions remain application-level tests.

The Job has no retries, a 120-second deadline and a 10-minute cleanup TTL. `--run` returns nonzero on failure and attempts to print container logs. Inspect its named Job/Pod in the same context if a policy or image-pull failure prevents logs. The probes are diagnostic; they are not installed as Helm hooks.

## Validate and deploy

Install Helm 3, then render the pinned chart first:

```sh
helm repo add open-metadata https://helm.open-metadata.org/
helm repo update open-metadata
helm pull open-metadata/openmetadata --version 2.0.0 --untar --untardir CHART_WORK_DIR
helm lint CHART_WORK_DIR/openmetadata -f docker/kubernetes/values-office.local.yaml --strict
helm template openmetadata CHART_WORK_DIR/openmetadata --namespace openmetadata-staging -f docker/kubernetes/values-office.local.yaml
```

After a successful preflight and a database backup, deploy the reviewed values:

```sh
helm upgrade --install openmetadata open-metadata/openmetadata --version 2.0.0 --kube-context YOUR_OFFICE_CONTEXT --namespace openmetadata-staging -f docker/kubernetes/values-office.local.yaml --wait --timeout 15m
```

The chart runs database migrations in an init container; that step **writes** to the selected database. Existing data migrations require a tested backup/restore path. Helm rollback does not reverse database migrations. Automatic scheduled pipeline redeployment and scheduled reindexing are disabled in this initial profile; trigger them deliberately after startup validation.

Access starts as internal `ClusterIP` with ingress disabled. Keep it internal until your office authentication, public URL and TLS ingress are configured. Native ingestion Jobs are enabled without the OMJob operator; a forcibly terminated ingestion Pod may not report its final status. Semantic search is disabled for the initial API baseline and needs separate plugin/mapping tests before enabling it.

## Verify compatibility and resource targets

1. Wait for startup/readiness, sign in, create a test service/schema/table, and verify authorization and PII masking.
2. Verify indexed search, filters/facets, cursor pagination, update/delete visibility and a full reindex against the **actual 2.19 patch**. Preflight success proves connectivity/basic reads, not all application features.
3. Run the repository's integration tests with `-DsearchType=opensearch -DsearchImage=opensearchproject/opensearch:2.19.PATCH` and `-DdatabaseImage=postgres:YOUR_MAJOR`; replace both versions. Keep these tests on disposable services, not the office database/search indexes.
4. Compare the original backend configuration and this profile on equivalent nodes/CPU budgets and the same dataset/request mix, with cold/warm cache measured separately. Use `bin/distributed-test/scripts/perf-test.sh` against the explicit staging URL; record successful requests/sec, p95/p99, errors, container RSS/working set, GC and CPU throttling.
5. Accept API memory at most **85%** of baseline and throughput at least **120%**, with no worse agreed latency/error bounds. Count all API replicas/sidecars. Requests/limits are scheduling/enforcement settings, not measured savings.

The initial API budget is 500m CPU/1Gi memory requested, 2 CPU/2Gi memory limited, `-Xms256m -Xmx1g`, two 64MiB weighted entity caches, 20 DB connections with 2 idle, and QoS admission 16. These are starting values, not validated capacity. HPA stays off and one replica keeps comparisons stable; scale/HA needs a separate shared-cache/session and database-connection budget.

Run local checks with `python -m pytest docker/kubernetes -q` (install pytest in the venv if needed). To include the chart rendering test, set `OPENMETADATA_CHART_DIR` to the unpacked chart directory and put Helm on PATH (or set `HELM_BIN` to its executable). The TLS integration test uses OpenSSL to generate a temporary certificate; it is skipped when OpenSSL is unavailable.

The SQL regression tests start and stop a disposable PostgreSQL cluster bound to localhost; they never use the office values. Install PostgreSQL 15 binaries (including `initdb`, `pg_ctl`, `psql`, extension libraries and shared files), set `POSTGRES_BIN_DIR` to their `bin` directory, and run the same pytest command as a non-root user. The tests cover a successful check, missing extensions, read-only defaults, schema permissions and table ownership. They are skipped when the binaries are unavailable. PostgreSQL prerequisite failures raise SQL exceptions under `ON_ERROR_STOP` so psql returns nonzero.
