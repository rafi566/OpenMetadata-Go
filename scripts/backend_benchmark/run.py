import hashlib
import json
import math
import re
import subprocess
import sys
import time
import uuid
from pathlib import Path
from urllib.request import Request, urlopen

root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(root / "scripts/backend_benchmark"))
import measure

label, rate, seconds = sys.argv[1], int(sys.argv[2]), int(sys.argv[3])
assert re.fullmatch(r"[A-Za-z0-9_-]{1,64}", label), "Invalid run label"
assert 1 <= rate <= 20000 and 1 <= seconds <= 1800, "Invalid workload bounds"
apis = (
    sys.argv[4].split(",") if len(sys.argv) > 4 else ["bettermetadata-benchmark-api-1"]
)
dependencies = [
    "bettermetadata-benchmark-postgres-1",
    "bettermetadata-benchmark-opensearch-1",
]
assert 1 <= len(apis) <= 64 and len(set(apis)) == len(apis), (
    "Use 1–64 distinct API containers"
)
assert all(re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", name) for name in apis), (
    "Invalid API container name"
)
assert not set(apis).intersection(dependencies), (
    "Do not include dependencies in API totals"
)
api_url = sys.argv[5] if len(sys.argv) > 5 else "http://api:8585/api/v1"
results = root / "docker/benchmark/results"
out = results / "runs" / label
out.mkdir(parents=True, exist_ok=False)
fixture = results / "fixtures/catalog-v1.json"
token = results / "private/admin-token"
login_request = Request(
    "http://127.0.0.1:18585/api/v1/users/login",
    data=json.dumps(
        {"email": "admin@open-metadata.org", "password": "YWRtaW4="}
    ).encode(),
    headers={"Content-Type": "application/json"},
)
with urlopen(login_request, timeout=15) as response:
    access_token = json.load(response)["accessToken"]
token.write_text(access_token)
docker = ["docker", "--host", "unix:///var/run/docker.sock"]
epoch = uuid.uuid4().hex
load_name = "bettermetadata-load-" + epoch[:12]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def info(name):
    data = measure.docker_get("/containers/" + name + "/json")
    tuning_names = {
        "JAVA_TOOL_OPTIONS",
        "ENTITY_CACHE_MAX_SIZE_BYTES",
        "DB_CONNECTION_POOL_MAX_SIZE",
        "DB_CONNECTION_POOL_MIN_SIZE",
        "DB_CONNECTION_POOL_MIN_IDLE",
        "DB_CONNECTION_POOL_INITIAL_SIZE",
        "QOS_MAX_REQUEST_COUNT",
        "QOS_MAX_SUSPENDED_REQUEST_COUNT",
        "ELASTICSEARCH_BATCH_SIZE",
        "SEMANTIC_SEARCH_ENABLED",
    }
    return {
        "id": data["Id"],
        "image": data["Image"],
        "started_at": data["State"]["StartedAt"],
        "running": data["State"]["Running"],
        "oom": data["State"]["OOMKilled"],
        "restarts": data["RestartCount"],
        "memory_limit_bytes": data["HostConfig"]["Memory"],
        "nano_cpus": data["HostConfig"]["NanoCpus"],
        "tuning": dict(
            value.split("=", 1)
            for value in data["Config"].get("Env", [])
            if value.split("=", 1)[0] in tuning_names
        ),
    }


def sample(name, previous=None):
    raw = measure.docker_get(
        "/containers/" + name + "/stats?stream=false&one-shot=true"
    )
    return {"timestamp": time.time(), **measure.resource_sample(raw, previous)}, raw[
        "cpu_stats"
    ]


def write(name, value):
    with (out / name).open("x", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2)


tracked = apis + dependencies
before_info = {name: info(name) for name in tracked}
assert all(value["running"] for value in before_info.values()), "Runtime is not ready"
command = docker + [
    "create",
    "--name",
    load_name,
    "--network",
    "bettermetadata-benchmark_default",
    "--memory",
    "512m",
    "--cpus",
    "1",
    "--mount",
    f"type=bind,source={root / 'scripts/backend_benchmark'},target=/benchmark,readonly",
    "--mount",
    f"type=bind,source={fixture},target=/fixture.json,readonly",
    "--mount",
    f"type=bind,source={token},target=/secrets/admin-token,readonly",
    "--mount",
    f"type=bind,source={out},target=/results",
    "--env",
    f"RATE={rate}",
    "--env",
    f"SECONDS={seconds}",
    "--env",
    "VUS=100",
    "--env",
    f"RUN_ID={epoch}",
    "--env",
    f"FIXTURE_SHA256={digest(fixture)}",
    "--env",
    f"API_URL={api_url}",
    "grafana/k6:2.3.0@sha256:9c2dee7f8ed74d317e4027c06a10f169b625638189de8d4555d0b3486a5aeb34",
    "run",
    "--quiet",
    "/benchmark/workload.mjs",
]
created = subprocess.run(
    command, check=True, capture_output=True, text=True
).stdout.strip()
before_cpu = {name: sample(name)[0] for name in apis}
previous = dict.fromkeys(tracked + [load_name])
samples = []
with (
    (out / "load.log").open("wb") as log,
    (out / "resources.jsonl").open("x") as stream,
):
    process = subprocess.Popen(
        docker + ["start", "--attach", load_name], stdout=log, stderr=subprocess.STDOUT
    )
    deadline = time.monotonic() + seconds + 60
    while process.poll() is None:
        if time.monotonic() > deadline:
            subprocess.run(
                docker + ["stop", "--time", "5", load_name],
                check=True,
                capture_output=True,
            )
            raise TimeoutError("Load exceeded its execution bound")
        current = {}
        for name in previous:
            if name == load_name and not info(name)["running"]:
                continue
            current[name], previous[name] = sample(name, previous[name])
        row = {"timestamp": time.time(), "containers": current}
        stream.write(json.dumps(row) + "\n")
        stream.flush()
        samples.append(measure.api_totals([current[name] for name in apis]))
        time.sleep(1)
    exit_code = process.wait()
after_cpu = {name: sample(name)[0] for name in apis}
after_info = {name: info(name) for name in tracked}
unchanged = all(
    before_info[name]["id"] == after_info[name]["id"]
    and before_info[name]["started_at"] == after_info[name]["started_at"]
    and before_info[name]["restarts"] == after_info[name]["restarts"]
    and after_info[name]["running"]
    and not after_info[name]["oom"]
    for name in tracked
)
write(
    "metadata.json",
    {
        "rate": rate,
        "seconds": seconds,
        "write_epoch": epoch,
        "api_containers": apis,
        "fixture_sha256": digest(fixture),
        "postgres_dump_sha256": digest(results / "private/catalog-v1.dump"),
        "search_snapshot_uuid": json.loads(
            (results / "private/search-snapshot.json").read_text()
        )["snapshot"]["uuid"],
        "workload_sha256": digest(root / "scripts/backend_benchmark/workload.mjs"),
        "contracts_sha256": digest(root / "scripts/backend_benchmark/contracts.mjs"),
        "runner_sha256": digest(Path(__file__)),
        "before": before_info,
        "after": after_info,
        "cpu_before": before_cpu,
        "cpu_after": after_cpu,
        "load_container_id": created,
        "load_state": info(load_name),
        "load_exit_code": exit_code,
        "runtime_unchanged": unchanged,
    },
)
try:
    summary = measure.request_summary(json.loads((out / "summary.json").read_text()))
except ValueError as error:
    failure = {"valid_run": False, "reason": str(error), "load_exit_code": exit_code}
    write("report.json", failure)
    print(json.dumps(failure), flush=True)
    sys.exit(1)
cpu_seconds = (
    measure.api_totals(list(after_cpu.values()))["cpu_usage_ns"]
    - measure.api_totals(list(before_cpu.values()))["cpu_usage_ns"]
) / 1e9
assert unchanged and cpu_seconds > 0 and len(samples) >= 2, (
    "Invalid resource measurement"
)
working_set = sorted(sample["working_set_bytes"] for sample in samples)
report = {
    **summary,
    "samples": len(samples),
    "memory_p95_bytes": working_set[math.ceil(len(samples) * 0.95) - 1],
    "memory_peak_bytes": max(working_set),
    "cpu_seconds": cpu_seconds,
    "cpu_seconds_per_1000_ops": cpu_seconds / summary["successful_ops"] * 1000,
    "measurement_seconds": max(value["timestamp"] for value in after_cpu.values())
    - min(value["timestamp"] for value in before_cpu.values()),
    "valid_run": exit_code == 0 and unchanged,
}
write("report.json", report)
print(json.dumps(report), flush=True)
sys.exit(0 if report["valid_run"] else 1)
