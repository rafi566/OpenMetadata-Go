#!/usr/bin/env python3
"""Sample Linux Docker containers and validate Java/Go benchmark comparisons."""

import argparse
import http.client
import json
import math
import socket
import time
from pathlib import Path
from urllib.parse import quote


def resource_sample(stats, previous_cpu=None):
    try:
        memory = stats["memory_stats"]
        counters = memory["stats"]
        inactive = counters.get("total_inactive_file", counters.get("inactive_file"))
        if inactive is None or memory["usage"] <= 0:
            raise ValueError("missing memory counters")
        current = stats["cpu_stats"]
        system_usage = current["system_cpu_usage"]
        cpu_usage = current["cpu_usage"]["total_usage"]
        online_cpus = current["online_cpus"]
        previous = previous_cpu or stats.get("precpu_stats", {})
        cores = None
        if "system_cpu_usage" in previous:
            system_delta = system_usage - previous["system_cpu_usage"]
            cpu_delta = cpu_usage - previous["cpu_usage"]["total_usage"]
            if system_delta > 0 and cpu_delta >= 0:
                cores = cpu_delta / system_delta * online_cpus
        return {
            "working_set_bytes": max(0, memory["usage"] - inactive),
            "rss_bytes": counters.get("rss", counters.get("anon")),
            "cpu_cores": cores,
            "cpu_usage_ns": cpu_usage,
            "throttled_ns": current.get("throttling_data", {}).get("throttled_time"),
        }
    except (KeyError, TypeError) as error:
        raise ValueError("missing memory or CPU counters") from error


def api_totals(samples):
    if not 1 <= len(samples) <= 64:
        raise ValueError("Use 1–64 API container samples")
    keys = ("working_set_bytes", "cpu_usage_ns")
    if any(
        type(sample.get(key)) is not int or sample[key] < 0
        for sample in samples
        for key in keys
    ):
        raise ValueError("missing or invalid API resource counter")
    return {key: sum(sample[key] for sample in samples) for key in keys}


def request_summary(summary):
    try:
        metrics = summary["metrics"]
        good = metrics["valid_ops"]["values"]["count"]
        bad = metrics["invalid_ops"]["values"]["count"]
        if good + bad <= 0:
            raise ValueError("empty request measurement")
        if good <= 0:
            raise ValueError("no successful operations")
        scheduled_seconds = summary["benchmark"]["seconds"]
        completed_ms = metrics["operation_end_ms"]["values"]["max"]
        if scheduled_seconds <= 0 or completed_ms <= 0:
            raise ValueError("empty request interval")
        seconds = max(scheduled_seconds, completed_ms / 1000)
        latency = metrics["valid_latency"]["values"]
        return {
            "operation_seconds": seconds,
            "successful_ops": good,
            "successful_rps": good / seconds,
            "error_rate": bad / (good + bad),
            "dropped_iterations": metrics.get(
                "dropped_iterations", {"values": {"count": 0}}
            )["values"]["count"],
            "latency_p95_ms": latency["p(95)"],
            "latency_p99_ms": latency["p(99)"],
        }
    except (KeyError, TypeError) as error:
        raise ValueError("missing request measurements") from error


def compare(baseline, candidate):
    context = baseline["context"]
    required = {"fixture", "workload", "cpu_limit", "replicas", "memory_target_rps"}
    if not required.issubset(context) or context != candidate["context"]:
        raise ValueError("benchmark context differs")
    keys = (
        "memory_p95_bytes",
        "memory_successful_rps",
        "cpu_seconds_per_1000_ops",
        "cpu_successful_rps",
        "successful_rps",
        "latency_p95_ms",
        "latency_p99_ms",
        "error_rate",
        "dropped_iterations",
        "samples",
    )
    for report in (baseline, candidate):
        if report.get("valid_run") is not True:
            raise ValueError("benchmark run failed qualification")
        if any(key not in report for key in keys):
            raise ValueError("missing measurements")
        if report["samples"] <= 0:
            raise ValueError("missing resource samples")
        if any(not math.isfinite(report[key]) or report[key] < 0 for key in keys):
            raise ValueError("invalid measurement")
        if report["memory_p95_bytes"] <= 0 or report["successful_rps"] <= 0:
            raise ValueError("empty baseline or candidate")
        if report["cpu_seconds_per_1000_ops"] <= 0:
            raise ValueError("empty CPU measurement")
        if context["memory_target_rps"] <= 0 or not math.isclose(
            report["memory_successful_rps"], context["memory_target_rps"], rel_tol=0.01
        ):
            raise ValueError("memory load did not reach the common target rate")
        if not math.isclose(
            report["cpu_successful_rps"], context["memory_target_rps"], rel_tol=0.01
        ):
            raise ValueError("CPU load did not reach the common target rate")
    memory_ratio = candidate["memory_p95_bytes"] / baseline["memory_p95_bytes"]
    throughput_ratio = candidate["successful_rps"] / baseline["successful_rps"]
    cpu_ratio = (
        candidate["cpu_seconds_per_1000_ops"] / baseline["cpu_seconds_per_1000_ops"]
    )
    return {
        "memory_reduction_pct": (1 - memory_ratio) * 100,
        "throughput_improvement_pct": (throughput_ratio - 1) * 100,
        "cpu_efficiency_improvement_pct": (1 - cpu_ratio) * 100,
        "passed": memory_ratio <= 0.85
        and throughput_ratio >= 1.2
        and cpu_ratio <= 0.8
        and candidate["error_rate"] <= baseline["error_rate"]
        and baseline["dropped_iterations"] == candidate["dropped_iterations"] == 0
        and candidate["latency_p95_ms"] <= baseline["latency_p95_ms"]
        and candidate["latency_p99_ms"] <= baseline["latency_p99_ms"],
    }


class DockerConnection(http.client.HTTPConnection):
    def __init__(self):
        super().__init__("localhost", timeout=10)

    def connect(self):
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.settimeout(self.timeout)
        self.sock.connect("/var/run/docker.sock")


def docker_get(path):
    connection = DockerConnection()
    try:
        connection.request("GET", "/v1.45" + path)
        response = connection.getresponse()
        if response.status != 200:
            raise ValueError(f"Docker returned HTTP {response.status}")
        return json.load(response)
    finally:
        connection.close()


def collect(containers, output, duration, interval):
    if (
        duration <= 0
        or interval <= 0
        or not 1 <= len(containers) <= 64
        or len(set(containers)) != len(containers)
    ):
        raise ValueError(
            "Use positive duration/interval and 1–64 distinct API containers"
        )
    identities = {}
    for name in containers:
        info = docker_get("/containers/" + quote(name, safe="") + "/json")
        if not info["State"]["Running"]:
            raise ValueError(f"Container {name} is not running")
        identities[name] = info["Id"]
    previous_cpu = dict.fromkeys(identities)
    deadline = time.monotonic() + duration
    with output.open("x", encoding="utf-8") as stream:
        while time.monotonic() < deadline:
            began = time.monotonic()
            samples = {}
            for name, identity in identities.items():
                stats = docker_get(
                    "/containers/" + identity + "/stats?stream=false&one-shot=true"
                )
                samples[name] = {
                    "id": identity,
                    **resource_sample(stats, previous_cpu[name]),
                }
                previous_cpu[name] = stats["cpu_stats"]
            stream.write(
                json.dumps({"timestamp": time.time(), "containers": samples}) + "\n"
            )
            stream.flush()
            time.sleep(max(0, interval - (time.monotonic() - began)))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--containers", nargs="+", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--duration", type=float, required=True)
    parser.add_argument("--interval", type=float, default=1)
    args = parser.parse_args()
    collect(args.containers, args.output, args.duration, args.interval)


if __name__ == "__main__":
    main()
