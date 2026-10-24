"""Check neutral resource accounting and refuse misleading comparisons."""

import copy
import importlib.util
from pathlib import Path

import pytest

MODULE = Path(__file__).with_name("measure.py")


@pytest.fixture
def measure():
    spec = importlib.util.spec_from_file_location("measure", MODULE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def stats():
    return {
        "memory_stats": {"usage": 1000, "stats": {"inactive_file": 200, "anon": 600}},
        "cpu_stats": {
            "cpu_usage": {"total_usage": 400},
            "system_cpu_usage": 4000,
            "online_cpus": 4,
            "throttling_data": {"throttled_time": 100},
        },
        "precpu_stats": {"cpu_usage": {"total_usage": 200}, "system_cpu_usage": 2000},
    }


def test_uses_container_working_set_instead_of_language_heap(measure, stats):
    result = measure.resource_sample(stats)
    assert result["working_set_bytes"] == 800
    assert result["rss_bytes"] == 600
    assert result["cpu_cores"] == pytest.approx(0.4)
    assert result["cpu_usage_ns"] == 400


def test_accepts_cgroup_v1_memory_counters(measure, stats):
    stats["memory_stats"]["stats"] = {"total_inactive_file": 150, "rss": 700}
    assert measure.resource_sample(stats)["working_set_bytes"] == 850


def test_missing_memory_counters_are_not_reported_as_zero(measure, stats):
    stats["memory_stats"] = {}
    with pytest.raises(ValueError, match="memory"):
        measure.resource_sample(stats)


def test_first_one_shot_sample_does_not_report_lifetime_cpu(measure, stats):
    stats["precpu_stats"] = {"cpu_usage": {"total_usage": 0}}
    assert measure.resource_sample(stats)["cpu_cores"] is None


def test_cpu_uses_two_observed_samples(measure, stats):
    previous = copy.deepcopy(stats["cpu_stats"])
    stats["precpu_stats"] = {}
    stats["cpu_stats"]["cpu_usage"]["total_usage"] = 600
    stats["cpu_stats"]["system_cpu_usage"] = 6000
    assert measure.resource_sample(stats, previous)["cpu_cores"] == pytest.approx(0.4)


def test_combined_api_totals_include_remaining_java_and_go(measure):
    java = {"working_set_bytes": 900, "cpu_usage_ns": 8_000_000_000}
    go = {"working_set_bytes": 200, "cpu_usage_ns": 1_000_000_000}
    assert measure.api_totals([java, go]) == {
        "working_set_bytes": 1100,
        "cpu_usage_ns": 9_000_000_000,
    }
    assert measure.api_totals([java]) == java
    with pytest.raises(ValueError, match="counter"):
        measure.api_totals([java, {"working_set_bytes": 200}])


@pytest.mark.parametrize("samples", [[], [{}] * 65])
def test_combined_api_totals_require_a_bounded_nonempty_set(measure, samples):
    with pytest.raises(ValueError, match="1–64"):
        measure.api_totals(samples)


def test_reset_cpu_counters_are_not_reported_as_negative_usage(measure, stats):
    previous = copy.deepcopy(stats["cpu_stats"])
    stats["cpu_stats"]["cpu_usage"]["total_usage"] = 100
    stats["cpu_stats"]["system_cpu_usage"] = 6000
    assert measure.resource_sample(stats, previous)["cpu_cores"] is None


@pytest.mark.parametrize("containers", [[], [str(i) for i in range(65)]])
def test_collector_requires_a_bounded_nonempty_container_set(
    measure, tmp_path, containers
):
    with pytest.raises(ValueError, match="1–64"):
        measure.collect(containers, tmp_path / "samples.jsonl", 1, 1)


def test_failed_requests_never_increase_successful_throughput(measure):
    summary = {
        "metrics": {
            "valid_ops": {"values": {"count": 80}},
            "invalid_ops": {"values": {"count": 20}},
            "dropped_iterations": {"values": {"count": 0}},
            "valid_latency": {"values": {"p(95)": 100, "p(99)": 150}},
            "operation_end_ms": {"values": {"max": 10000}},
        },
        "benchmark": {"seconds": 10},
        "state": {"testRunDurationMs": 10000},
    }
    result = measure.request_summary(summary)
    assert result["successful_rps"] == 8
    assert result["error_rate"] == pytest.approx(0.2)


def test_throughput_excludes_teardown_but_includes_request_drain(measure):
    summary = {
        "metrics": {
            "valid_ops": {"values": {"count": 100}},
            "invalid_ops": {"values": {"count": 0}},
            "valid_latency": {"values": {"p(95)": 100, "p(99)": 150}},
            "operation_end_ms": {"values": {"max": 10050}},
        },
        "benchmark": {"seconds": 10},
        "state": {"testRunDurationMs": 12000},
    }
    assert measure.request_summary(summary)["successful_rps"] == pytest.approx(
        100 / 10.05
    )
    summary["metrics"]["operation_end_ms"]["values"]["max"] = 8000
    assert measure.request_summary(summary)["successful_rps"] == 10
    del summary["metrics"]["operation_end_ms"]
    with pytest.raises(ValueError, match="missing"):
        measure.request_summary(summary)


def test_all_failed_operations_have_no_valid_latency_or_cpu_cost(measure):
    summary = {
        "metrics": {
            "valid_ops": {"values": {"count": 0}},
            "invalid_ops": {"values": {"count": 100}},
            "valid_latency": {"values": {"p(95)": 0, "p(99)": 0}},
        },
        "state": {"testRunDurationMs": 10000},
    }
    with pytest.raises(ValueError, match="successful"):
        measure.request_summary(summary)


@pytest.fixture
def baseline():
    return {
        "context": {
            "fixture": "snapshot-1",
            "workload": "mix-1",
            "cpu_limit": 2,
            "replicas": 1,
            "memory_target_rps": 100,
        },
        "memory_p95_bytes": 1000,
        "memory_successful_rps": 100,
        "cpu_seconds_per_1000_ops": 10,
        "cpu_successful_rps": 100,
        "successful_rps": 100,
        "latency_p95_ms": 100,
        "latency_p99_ms": 200,
        "error_rate": 0,
        "dropped_iterations": 0,
        "samples": 120,
        "valid_run": True,
    }


def test_comparison_requires_all_resource_and_performance_targets(measure, baseline):
    candidate = copy.deepcopy(baseline)
    candidate.update(
        memory_p95_bytes=850, successful_rps=120, cpu_seconds_per_1000_ops=8
    )
    assert measure.compare(baseline, candidate)["passed"] is True
    candidate["successful_rps"] = 119
    assert measure.compare(baseline, candidate)["passed"] is False


def test_cpu_efficiency_requires_twenty_percent_improvement(measure, baseline):
    candidate = copy.deepcopy(baseline)
    candidate.update(
        memory_p95_bytes=850, successful_rps=120, cpu_seconds_per_1000_ops=8
    )
    assert measure.compare(baseline, candidate)["passed"] is True
    candidate["cpu_seconds_per_1000_ops"] = 8.01
    assert measure.compare(baseline, candidate)["passed"] is False


def test_missing_cpu_measurement_cannot_pass(measure, baseline):
    candidate = copy.deepcopy(baseline)
    candidate.update(memory_p95_bytes=500, successful_rps=200)
    del candidate["cpu_seconds_per_1000_ops"]
    with pytest.raises(ValueError, match="measurement"):
        measure.compare(baseline, candidate)


@pytest.mark.parametrize("side", ["baseline", "candidate"])
def test_cpu_from_a_different_load_cannot_qualify(measure, baseline, side):
    candidate = copy.deepcopy(baseline)
    candidate.update(
        memory_p95_bytes=500, successful_rps=200, cpu_seconds_per_1000_ops=5
    )
    report = baseline if side == "baseline" else candidate
    report["cpu_successful_rps"] = 200
    with pytest.raises(ValueError, match="CPU load"):
        measure.compare(baseline, candidate)


def test_cpu_load_must_be_recorded(measure, baseline):
    candidate = copy.deepcopy(baseline)
    candidate.update(
        memory_p95_bytes=500, successful_rps=200, cpu_seconds_per_1000_ops=5
    )
    del candidate["cpu_successful_rps"]
    with pytest.raises(ValueError, match="measurement"):
        measure.compare(baseline, candidate)


@pytest.mark.parametrize("validity", [False, None, "true"])
def test_invalid_or_unqualified_runs_cannot_pass_comparison(
    measure, baseline, validity
):
    candidate = copy.deepcopy(baseline)
    candidate.update(
        memory_p95_bytes=500,
        successful_rps=200,
        cpu_seconds_per_1000_ops=5,
        valid_run=validity,
    )
    with pytest.raises(ValueError, match="qualification"):
        measure.compare(baseline, candidate)


@pytest.mark.parametrize("field,value", [("fixture", "other"), ("cpu_limit", 4)])
def test_mismatched_conditions_cannot_pass(measure, baseline, field, value):
    candidate = copy.deepcopy(baseline)
    candidate["context"][field] = value
    with pytest.raises(ValueError, match="context"):
        measure.compare(baseline, candidate)


@pytest.mark.parametrize(
    "field,value",
    [("error_rate", 0.1), ("dropped_iterations", 1), ("latency_p99_ms", 201)],
)
def test_fast_errors_dropped_load_and_tail_regressions_fail(
    measure, baseline, field, value
):
    candidate = copy.deepcopy(baseline)
    candidate.update(
        memory_p95_bytes=500, successful_rps=200, cpu_seconds_per_1000_ops=5
    )
    candidate[field] = value
    assert measure.compare(baseline, candidate)["passed"] is False


def test_missing_resource_samples_cannot_pass(measure, baseline):
    candidate = copy.deepcopy(baseline)
    candidate["samples"] = 0
    with pytest.raises(ValueError, match="samples"):
        measure.compare(baseline, candidate)


def test_memory_and_capacity_are_measured_at_distinct_loads(measure, baseline):
    candidate = copy.deepcopy(baseline)
    candidate.update(
        memory_p95_bytes=500, successful_rps=200, memory_successful_rps=200
    )
    with pytest.raises(ValueError, match="memory load"):
        measure.compare(baseline, candidate)


def test_an_incomplete_context_is_not_comparable(measure, baseline):
    del baseline["context"]["fixture"]
    with pytest.raises(ValueError, match="context"):
        measure.compare(baseline, baseline)
