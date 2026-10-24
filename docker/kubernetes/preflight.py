#!/usr/bin/env python3
"""Render an office preflight Job; --run executes it in an explicit kube context."""

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path
from urllib.parse import parse_qs

import yaml

HERE = Path(__file__).resolve().parent

SEARCH_PROBE = r"""
import base64, json, os, re, ssl, sys
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, build_opener, HTTPSHandler, HTTPRedirectHandler

class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None

try:
    context = ssl.create_default_context(cafile=os.environ["SEARCH_CA"] or None)
    opener = build_opener(NoRedirect(), HTTPSHandler(context=context))
    credentials = (os.environ["SEARCH_USER"] + ":" + os.environ["SEARCH_PASSWORD"]).encode()
    auth = "Basic " + base64.b64encode(credentials).decode()
    def get(path):
        request = Request(os.environ["SEARCH_URL"] + path, headers={"Authorization": auth})
        with opener.open(request, timeout=10) as response:
            body = response.read(65537)
        if len(body) > 65536:
            raise ValueError("oversized response")
        return json.loads(body)
    version = get("/")["version"]
    if not isinstance(version, dict) or version.get("distribution") != "opensearch" or not re.fullmatch(r"2\.19\.\d+", version["number"]):
        sys.exit("FAIL: expected OpenSearch 2.19.x")
    prefix = quote(os.environ["SEARCH_PREFIX"], safe="")
    result = get("/" + prefix + "*/_search?size=0&ignore_unavailable=true&allow_no_indices=true")
    if not isinstance(result, dict) or not isinstance(result.get("hits"), dict):
        sys.exit("FAIL: invalid scoped search response")
    print("PASS: OpenSearch " + version["number"] + "; scoped search accepted")
except HTTPError as error:
    sys.exit("FAIL: OpenSearch HTTP " + str(error.code))
except (URLError, OSError, ValueError, KeyError, TypeError):
    sys.exit("FAIL: OpenSearch connection, TLS or response validation failed")
"""


def reject_placeholders(value):
    if isinstance(value, dict):
        for item in value.values():
            reject_placeholders(item)
    elif isinstance(value, list):
        for item in value:
            reject_placeholders(item)
    elif isinstance(value, str) and "REPLACE_ME" in value:
        raise ValueError("Fill all REPLACE_ME placeholders in the values file first")


def secret_env(name, reference):
    if (
        not isinstance(reference, dict)
        or not reference.get("secretRef")
        or not reference.get("secretKey")
    ):
        raise ValueError(f"{name} requires a nonempty secretRef and secretKey")
    return {
        "name": name,
        "valueFrom": {
            "secretKeyRef": {
                "name": reference["secretRef"],
                "key": reference["secretKey"],
            }
        },
    }


def build_job(values, namespace):
    reject_placeholders(values)
    if (
        not re.fullmatch(r"[a-z0-9](?:[-a-z0-9]*[a-z0-9])?", namespace)
        or len(namespace) > 63
    ):
        raise ValueError("Use a valid Kubernetes namespace")
    config = values["openmetadata"]["config"]
    database, search = config["database"], config["elasticsearch"]
    for identity in (
        database["databaseName"],
        database["auth"]["username"],
        search["auth"]["username"],
    ):
        if not isinstance(identity, str) or not identity.strip():
            raise ValueError(
                "Database name and service usernames must be nonempty strings"
            )
    if (
        database["dbScheme"] != "postgresql"
        or database["driverClass"] != "org.postgresql.Driver"
    ):
        raise ValueError("The office profile requires PostgreSQL")
    if search["searchType"] != "opensearch" or search["scheme"] != "https":
        raise ValueError("The office profile requires OpenSearch over HTTPS")
    for service in (database, search):
        if not isinstance(service["host"], str) or not re.fullmatch(
            r"[A-Za-z0-9.-]+", service["host"]
        ):
            raise ValueError(
                "Hosts must be DNS names or IPv4 addresses without a scheme, path or port"
            )
        if type(service["port"]) is not int or not 1 <= service["port"] <= 65535:
            raise ValueError("Service ports must be integers between 1 and 65535")
        if service.get("enabled") is not True:
            raise ValueError(
                "Database and search connection configuration must be enabled"
            )
    if not re.fullmatch(r"[a-z0-9][a-z0-9_-]*", search["clusterAlias"]):
        raise ValueError("Set a dedicated lowercase OpenSearch clusterAlias prefix")
    if (
        search["auth"]["enabled"] is not True
        or search["trustStore"]["enabled"] is not True
    ):
        raise ValueError("OpenSearch credentials and trustStore must be enabled")
    params = parse_qs(database["dbParams"])
    if params.get("sslmode") != ["verify-full"] or params.get("sslrootcert") != [
        "/etc/openmetadata/ca/postgres-ca.crt"
    ]:
        raise ValueError(
            "PostgreSQL requires sslmode=verify-full and the mounted postgres-ca.crt"
        )
    volumes = [v for v in values["extraVolumes"] if v["name"] == "office-ca"]
    if len(volumes) != 1:
        raise ValueError("Provide exactly one office-ca Secret volume")
    expected = {"postgres-ca.crt", "opensearch-ca.crt", "opensearch-truststore.p12"}
    if {item["path"] for item in volumes[0]["secret"]["items"]} != expected:
        raise ValueError(
            "The office-ca volume must contain the PostgreSQL CA, OpenSearch CA and truststore"
        )
    mounts = [m for m in values["extraVolumeMounts"] if m["name"] == "office-ca"]
    if (
        len(mounts) != 1
        or mounts[0]["mountPath"] != "/etc/openmetadata/ca"
        or mounts[0].get("readOnly") is not True
    ):
        raise ValueError("Mount office-ca read-only at /etc/openmetadata/ca")
    if search["trustStore"]["path"] != "/etc/openmetadata/ca/opensearch-truststore.p12":
        raise ValueError("Use the mounted OpenSearch truststore")

    security = {
        "allowPrivilegeEscalation": False,
        "readOnlyRootFilesystem": True,
        "capabilities": {"drop": ["ALL"]},
    }
    resources = {
        "requests": {"cpu": "50m", "memory": "64Mi"},
        "limits": {"cpu": "500m", "memory": "128Mi"},
    }
    postgres_env = {
        "PGHOST": database["host"],
        "PGPORT": str(database["port"]),
        "PGDATABASE": database["databaseName"],
        "PGUSER": database["auth"]["username"],
        "PGCONNECT_TIMEOUT": "10",
        "PGSSLMODE": "verify-full",
        "PGSSLROOTCERT": "/etc/openmetadata/ca/postgres-ca.crt",
        "PGOPTIONS": "-c statement_timeout=10000 -c lock_timeout=5000",
    }
    search_env = {
        "SEARCH_URL": f"https://{search['host']}:{search['port']}",
        "SEARCH_USER": search["auth"]["username"],
        "SEARCH_PREFIX": search["clusterAlias"],
        "SEARCH_CA": "/etc/openmetadata/ca/opensearch-ca.crt",
    }
    return {
        "apiVersion": "batch/v1",
        "kind": "Job",
        "metadata": {"generateName": "openmetadata-preflight-", "namespace": namespace},
        "spec": {
            "backoffLimit": 0,
            "activeDeadlineSeconds": 120,
            "ttlSecondsAfterFinished": 600,
            "template": {
                "metadata": {
                    "labels": {
                        "app.kubernetes.io/name": "openmetadata",
                        "app.kubernetes.io/component": "preflight",
                    }
                },
                "spec": {
                    "restartPolicy": "Never",
                    "automountServiceAccountToken": False,
                    "securityContext": {
                        "runAsNonRoot": True,
                        "runAsUser": 65532,
                        "seccompProfile": {"type": "RuntimeDefault"},
                    },
                    "volumes": volumes,
                    "initContainers": [
                        {
                            "name": "postgres",
                            "image": "postgres:15-alpine",
                            "command": [
                                "sh",
                                "-ec",
                                "exec psql -X --no-password -v ON_ERROR_STOP=1 <<'OFFICE_SQL'\n"
                                + (HERE / "check-postgres.sql").read_text(
                                    encoding="utf-8"
                                )
                                + "\nOFFICE_SQL\n",
                            ],
                            "env": [
                                {"name": name, "value": value}
                                for name, value in postgres_env.items()
                            ]
                            + [secret_env("PGPASSWORD", database["auth"]["password"])],
                            "volumeMounts": mounts,
                            "securityContext": security,
                            "resources": resources,
                        }
                    ],
                    "containers": [
                        {
                            "name": "opensearch",
                            "image": "python:3.13-alpine",
                            "command": ["python3", "-c", SEARCH_PROBE],
                            "env": [
                                {"name": name, "value": value}
                                for name, value in search_env.items()
                            ]
                            + [
                                secret_env(
                                    "SEARCH_PASSWORD", search["auth"]["password"]
                                )
                            ],
                            "volumeMounts": mounts,
                            "securityContext": security,
                            "resources": resources,
                        }
                    ],
                },
            },
        },
    }


def check_secrets(values, kubectl):
    config = values["openmetadata"]["config"]
    references = [
        config["database"]["auth"]["password"],
        config["elasticsearch"]["auth"]["password"],
        config["elasticsearch"]["trustStore"]["password"],
        config["fernetkey"],
    ]
    required = {}
    for ref in references:
        secret_env("credential", ref)
        required.setdefault(ref["secretRef"], set()).add(ref["secretKey"])
    for volume in values["extraVolumes"]:
        secret = volume.get("secret")
        if secret:
            required.setdefault(secret["secretName"], set()).update(
                item["key"] for item in secret["items"]
            )
    for name, keys in required.items():
        data = json.loads(
            subprocess.run(
                kubectl + ["get", "secret", name, "-o", "json"],
                check=True,
                capture_output=True,
                text=True,
                timeout=30,
            ).stdout
        ).get("data", {})
        missing = [key for key in keys if not data.get(key)]
        if missing:
            raise ValueError(
                f"Secret {name} has missing/empty keys: {', '.join(sorted(missing))}"
            )
    print("PASS: referenced Secret keys exist", file=sys.stderr)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--values", type=Path, default=HERE / "values-office.yaml")
    parser.add_argument("--namespace", required=True)
    parser.add_argument(
        "--context", help="Required with --run; never silently uses the current context"
    )
    parser.add_argument(
        "--run",
        action="store_true",
        help="Check Secrets, then create and wait for the probe Job",
    )
    args = parser.parse_args()
    if args.run and not args.context:
        parser.error("--run requires --context")
    try:
        values = yaml.safe_load(args.values.read_text(encoding="utf-8"))
        job = build_job(values, args.namespace)
        if not args.run:
            print(json.dumps(job, indent=2))
            return 0
        kubectl = ["kubectl", "--context", args.context, "--namespace", args.namespace]
        check_secrets(values, kubectl)
        created = subprocess.run(
            kubectl + ["create", "-f", "-", "-o", "json"],
            input=json.dumps(job),
            capture_output=True,
            text=True,
            check=True,
            timeout=30,
        )
        name = json.loads(created.stdout)["metadata"]["name"]
        print(
            f"Created Job {name}; it expires 10 minutes after finishing",
            file=sys.stderr,
        )
        result = subprocess.run(
            kubectl
            + ["wait", "--for=condition=complete", f"job/{name}", "--timeout=150s"],
            check=False,
            timeout=180,
        )
        subprocess.run(
            kubectl + ["logs", f"job/{name}", "--all-containers=true", "--prefix=true"],
            check=False,
            timeout=30,
        )
        if result.returncode:
            print(
                f"FAIL: inspect kubectl describe job {name} in the selected context/namespace",
                file=sys.stderr,
            )
            return 1
        print(
            "PASS: dependency preflight; application migrations and search compatibility tests are still required"
        )
        return 0
    except subprocess.CalledProcessError:
        print(
            "FAIL: kubectl failed; check the selected context, namespace and permissions",
            file=sys.stderr,
        )
    except subprocess.TimeoutExpired:
        print(
            "FAIL: kubectl timed out; inspect preflight Jobs in the selected namespace",
            file=sys.stderr,
        )
    except yaml.YAMLError:
        print("FAIL: invalid YAML in the values file", file=sys.stderr)
    except (OSError, ValueError, KeyError, TypeError) as error:
        print(f"FAIL: {error}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
