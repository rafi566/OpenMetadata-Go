"""Behavior checks for the office deployment preflight."""

import importlib.util
import json
import os
import re
import shutil
import ssl
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
import yaml

HERE = Path(__file__).parent


@pytest.fixture
def preflight():
    path = HERE / "preflight.py"
    assert path.exists(), "preflight implementation is not present yet"
    spec = importlib.util.spec_from_file_location("preflight", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def values():
    text = (HERE / "values-office.yaml").read_text()
    # Substitution leaves the actual shipped values structure under test.
    return yaml.safe_load(
        re.sub(
            r"REPLACE_ME_([A-Z_]+)",
            lambda m: "office-" + m[1].lower().replace("_", "-"),
            text,
        )
    )


def test_unfilled_values_fail_before_running_kubectl():
    result = subprocess.run(
        [
            sys.executable,
            str(HERE / "preflight.py"),
            "--namespace",
            "office",
            "--values",
            str(HERE / "values-office.yaml"),
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "REPLACE_ME" in result.stderr
    assert "Traceback" not in result.stderr


@pytest.mark.parametrize(
    "change",
    [
        {"searchType": "elasticsearch"},
        {"scheme": "http"},
        {"host": "https://search.example:9200"},
        {"port": 0},
        {"clusterAlias": ""},
    ],
)
def test_rejects_wrong_search_configuration(preflight, values, change):
    values["openmetadata"]["config"]["elasticsearch"].update(change)
    with pytest.raises(ValueError):
        preflight.build_job(values, "office")


def test_rejects_unverified_postgres_tls(preflight, values):
    values["openmetadata"]["config"]["database"]["dbParams"] = "sslmode=require"
    with pytest.raises(ValueError):
        preflight.build_job(values, "office")


@pytest.mark.parametrize("field", ["databaseName", "username"])
def test_rejects_empty_database_identity_before_creating_a_job(
    preflight, values, field
):
    database = values["openmetadata"]["config"]["database"]
    (database["auth"] if field == "username" else database)[field] = ""
    with pytest.raises(ValueError):
        preflight.build_job(values, "office")


def test_job_uses_the_values_secrets_and_verified_tls(preflight, values):
    job = preflight.build_job(values, "office")
    pod = job["spec"]["template"]["spec"]
    assert job["metadata"]["namespace"] == "office"
    assert pod["automountServiceAccountToken"] is False
    postgres = pod["initContainers"][0]
    env = {item["name"]: item for item in postgres["env"]}
    assert env["PGHOST"]["value"] == "office-postgres-host"
    assert env["PGPASSWORD"]["valueFrom"]["secretKeyRef"] == {
        "name": "office-postgres-secret",
        "key": "password",
    }
    assert env["PGSSLMODE"]["value"] == "verify-full"
    assert env["PGSSLROOTCERT"]["value"] == "/etc/openmetadata/ca/postgres-ca.crt"
    assert [v["name"] for v in pod["volumes"]] == ["office-ca"]
    assert "PGPASSWORD=" not in json.dumps(job)


def test_render_is_offline_and_does_not_need_kubectl(preflight, values, tmp_path):
    path = tmp_path / "values.yaml"
    path.write_text(yaml.safe_dump(values))
    result = subprocess.run(
        [
            sys.executable,
            str(HERE / "preflight.py"),
            "--namespace",
            "office",
            "--values",
            str(path),
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["kind"] == "Job"


def test_run_requires_an_explicit_context():
    result = subprocess.run(
        [sys.executable, str(HERE / "preflight.py"), "--namespace", "office", "--run"],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "--run requires --context" in result.stderr


def test_missing_secret_key_prevents_job_creation(preflight, values, monkeypatch):
    def run(command, **kwargs):
        assert "create" not in command
        return subprocess.CompletedProcess(command, 0, stdout='{"data": {}}')

    monkeypatch.setattr(subprocess, "run", run)
    with pytest.raises(ValueError, match="missing/empty keys"):
        preflight.check_secrets(
            values, ["kubectl", "--context", "office", "--namespace", "office"]
        )


def test_chart_renders_the_external_service_profile(values, tmp_path):
    import base64

    helm = os.environ.get("HELM_BIN") or shutil.which("helm")
    chart = os.environ.get("OPENMETADATA_CHART_DIR")
    if not helm or not chart:
        pytest.skip("Set HELM_BIN and OPENMETADATA_CHART_DIR to test the pinned chart")
    path = tmp_path / "values.yaml"
    path.write_text(yaml.safe_dump(values))
    rendered = subprocess.run(
        [
            helm,
            "template",
            "openmetadata",
            chart,
            "--namespace",
            "office",
            "-f",
            str(path),
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    resources = [item for item in yaml.safe_load_all(rendered.stdout) if item]
    deployments = [r for r in resources if r["kind"] == "Deployment"]
    assert len(deployments) == 1
    assert not any(
        r["kind"]
        in {"StatefulSet", "HorizontalPodAutoscaler", "CustomResourceDefinition"}
        for r in resources
    )
    pod = deployments[0]["spec"]["template"]["spec"]
    assert deployments[0]["spec"]["replicas"] == 1
    for container in [pod["containers"][0], pod["initContainers"][0]]:
        assert (
            container["image"]
            == "office-registry/openmetadata-server:office-fork-commit-tag"
        )
        assert container["resources"]["limits"]["memory"] == "2Gi"
        assert {m["name"] for m in container["volumeMounts"]} >= {
            "office-ca",
            "jwt-keys",
        }
        env = {e["name"]: e for e in container["env"]}
        assert (
            env["DB_USER_PASSWORD"]["valueFrom"]["secretKeyRef"]["name"]
            == "office-postgres-secret"
        )
        assert (
            env["ELASTICSEARCH_PASSWORD"]["valueFrom"]["secretKeyRef"]["name"]
            == "office-opensearch-secret"
        )
        assert (
            env["FERNET_KEY"]["valueFrom"]["secretKeyRef"]["name"]
            == "office-runtime-secret"
        )
        assert env["OPENMETADATA_HEAP_OPTS"]["value"] == "-Xms256m -Xmx1g"
    data = {}
    for resource in resources:
        if resource["kind"] == "Secret":
            data.update(
                {
                    key: base64.b64decode(value).decode()
                    for key, value in resource.get("data", {}).items()
                }
            )
    assert data["DB_SCHEME"] == "postgresql"
    # The chart quotes some env values for substitution into the application's YAML.
    assert yaml.safe_load(data["SEARCH_TYPE"]) == "opensearch"
    assert yaml.safe_load(data["ELASTICSEARCH_CLUSTER_ALIAS"]) == "office_staging"
    assert (
        data["DB_PARAMS"]
        == "sslmode=verify-full&sslrootcert=/etc/openmetadata/ca/postgres-ca.crt"
    )


@pytest.mark.parametrize(
    "missing_secret,wait_status",
    [(True, 0), (False, 1), (False, 0), (False, "timeout")],
)
def test_run_reports_missing_secret_or_failed_job(
    preflight, values, tmp_path, monkeypatch, capsys, missing_secret, wait_status
):
    path = tmp_path / "values.yaml"
    path.write_text(yaml.safe_dump(values))
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "preflight.py",
            "--values",
            str(path),
            "--namespace",
            "office",
            "--context",
            "office",
            "--run",
        ],
    )
    created = []

    def run(command, **kwargs):
        if "get" in command:
            keys = [
                "password",
                "truststore-password",
                "fernet-key",
                "postgres-ca.crt",
                "opensearch-ca.crt",
                "opensearch-truststore.p12",
                "public_key.der",
                "private_key.der",
            ]
            data = {} if missing_secret else {key: "do-not-print" for key in keys}
            return subprocess.CompletedProcess(
                command, 0, stdout=json.dumps({"data": data})
            )
        if "create" in command:
            created.append(json.loads(kwargs["input"]))
            return subprocess.CompletedProcess(
                command, 0, stdout='{"metadata": {"name": "probe-test"}}'
            )
        if "wait" in command and wait_status == "timeout":
            raise subprocess.TimeoutExpired(command, 180)
        return subprocess.CompletedProcess(
            command, wait_status if "wait" in command else 0
        )

    monkeypatch.setattr(subprocess, "run", run)
    assert preflight.main() == (1 if missing_secret or wait_status else 0)
    if missing_secret:
        assert not created
    output = capsys.readouterr()
    assert "do-not-print" not in output.out + output.err


@pytest.mark.parametrize(
    "distribution,version,status,success",
    [
        ("opensearch", "2.19.0", 200, True),
        ("opensearch", "2.19.7", 200, True),
        ("opensearch", "2.18.0", 200, False),
        ("opensearch", "3.4.0", 200, False),
        ("elasticsearch", "2.19.0", 200, False),
        ("opensearch", "2.19.bad", 200, False),
        ("opensearch", "2.19.0", 401, False),
        ("opensearch", "2.19.0", 302, False),
    ],
)
def test_real_probe_rejects_wrong_engine_version_and_http_errors(
    preflight, values, distribution, version, status, success
):
    paths = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            paths.append(self.path)
            self.send_response(status)
            if status == 302:
                self.send_header("Location", "/redirected")
            self.end_headers()
            body = (
                {"version": {"distribution": distribution, "number": version}}
                if self.path == "/"
                else {"hits": {"hits": []}}
            )
            self.wfile.write(json.dumps(body).encode())

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        job = preflight.build_job(values, "office")
        code = job["spec"]["template"]["spec"]["containers"][0]["command"][-1]
        result = subprocess.run(
            [sys.executable, "-c", code],
            check=False,
            capture_output=True,
            text=True,
            env={
                **os.environ,
                "SEARCH_URL": f"http://127.0.0.1:{server.server_port}",
                "SEARCH_USER": "reader",
                "SEARCH_PASSWORD": "do-not-print",
                "SEARCH_CA": "",
                "SEARCH_PREFIX": "office_staging",
            },
        )
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
    assert (result.returncode == 0) == success, result.stdout + result.stderr
    assert "do-not-print" not in result.stdout + result.stderr
    if status == 302:
        assert paths == ["/"]


def test_probe_verifies_certificate_chain_and_hostname(preflight, values, tmp_path):
    openssl = shutil.which("openssl")
    if not openssl:
        pytest.skip("OpenSSL is needed to generate the temporary TLS test certificate")
    key, cert, config = (
        tmp_path / name for name in ("key.pem", "cert.pem", "openssl.cnf")
    )
    config.write_text("""[req]
distinguished_name = dn
x509_extensions = extensions
prompt = no
[dn]
CN = localhost
[extensions]
subjectAltName = DNS:localhost
basicConstraints = critical,CA:TRUE
keyUsage = critical,digitalSignature,keyEncipherment,keyCertSign
extendedKeyUsage = serverAuth
subjectKeyIdentifier = hash
authorityKeyIdentifier = keyid:always
""")
    subprocess.run(
        [
            openssl,
            "req",
            "-x509",
            "-newkey",
            "rsa:2048",
            "-nodes",
            "-days",
            "1",
            "-config",
            str(config),
            "-keyout",
            str(key),
            "-out",
            str(cert),
        ],
        capture_output=True,
        check=True,
    )

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            body = (
                {"version": {"distribution": "opensearch", "number": "2.19.0"}}
                if self.path == "/"
                else {"hits": {"hits": []}}
            )
            self.send_response(200)
            self.end_headers()
            self.wfile.write(json.dumps(body).encode())

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(cert, key)
    server.socket = context.wrap_socket(server.socket, server_side=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    code = preflight.build_job(values, "office")["spec"]["template"]["spec"][
        "containers"
    ][0]["command"][-1]
    try:
        for host, ca, success in [
            ("localhost", "", False),
            ("localhost", str(cert), True),
            ("127.0.0.1", str(cert), False),
        ]:
            result = subprocess.run(
                [sys.executable, "-c", code],
                check=False,
                capture_output=True,
                text=True,
                env={
                    **os.environ,
                    "SEARCH_URL": f"https://{host}:{server.server_port}",
                    "SEARCH_CA": ca,
                    "SEARCH_USER": "reader",
                    "SEARCH_PASSWORD": "do-not-print",
                    "SEARCH_PREFIX": "office_staging",
                },
            )
            assert (result.returncode == 0) == success, result.stdout + result.stderr
            assert "do-not-print" not in result.stdout + result.stderr
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
