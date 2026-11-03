#!/usr/bin/env python3
"""H-025 offline admission screening for sanitized resource observations.

The output NEVER authorizes a live collector, even when all supplied values
are in range. Origin is synthetic/unattested and actual PRX126 measurements
require separately approved target access, native load tests and review.
Does not accept a URL, device target, credentials, shell command or host.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import sys

MAX_INPUT_BYTES = 600_000
MAX_ROWS_PER_PHASE = 120
PHASES = {"idle": 5, "load": 10, "recovery": 3}
SOURCE = "h025_injected_readonly_provider"
ORIGIN = "offline_synthetic_unattested"
REQUIRED_FALSE = (
    "hardware_qualified", "approved_for_service_start",
    "direct_management_authorization_verified", "device_modified",
    "firmware_bank_modified", "network_reachability_proven",
    "subscriber_wan_throughput_proven", "boot_epoch_identity_exported",
    "raw_eth_counters_exported", "raw_shell_output_exported",
    "measured_on_production_board",
)
NUMERIC_LIMITS = {
    "native_observation_window_seconds": (0, 12),
    "cpu_busy_fraction": (0, 1),
    "mem_total_kib": (16384, 4194304),
    "mem_available_kib": (0, 4194304),
    "current_process_rss_kib": (0, 4194304),
    "load_average_1min": (0, 1000),
    "thermal_zone0_millidegc": (0, 125000),
    "actual_pon_state": (0, 255),
    "observed_host_link_mbps": (0, 100000),
}
NULLABLE = {
    "cpu_busy_fraction", "mem_total_kib", "mem_available_kib",
    "current_process_rss_kib", "load_average_1min",
    "thermal_zone0_millidegc", "actual_pon_state",
    "observed_host_link_mbps",
}
SOURCE_STATES = {"observed", "unavailable"}
FIELD_KEYS = {
    "schema", "source", "provenance", "source_interface",
    "pon_observation", "host_link_observation",
    "host_counters_observation", "cpu_sample_status",
    "memory_sample_status", "process_memory_status",
    "temperature_sample_status", *REQUIRED_FALSE, *NUMERIC_LIMITS,
}
OBSERVATION_FIELDS = {
    "pon_observation", "host_link_observation", "host_counters_observation",
    "cpu_sample_status", "memory_sample_status", "process_memory_status",
    "temperature_sample_status",
}
# Source-only risk-screening hypotheses, never actual board acceptance.
MIN_AVAILABLE_KIB = 16384
MAX_PROCESS_RSS_KIB = 8192
MAX_OBS_WINDOW_SECONDS = 11
MAX_CPU_BUSY = .85
MAX_THERMAL_MILLIC = 85000


def ensure(condition: bool, reason: str) -> None:
    if not condition:
        raise ValueError(reason)


def numeric(value, name: str):
    ensure(type(value) in (int, float) and math.isfinite(value),
           "invalid_numeric_" + name)
    minimum, maximum = NUMERIC_LIMITS[name]
    ensure(minimum <= value <= maximum, "out_of_schema_range_" + name)
    return value


def validate_row(row: object) -> dict:
    ensure(type(row) is dict, "invalid_sample_shape")
    # Lua omits nil optional fields from its table; JSON cannot carry
    # them unless an encoder explicitly materializes null. Both mean
    # unavailable, NEVER an observed zero or a green qualification.
    ensure(set(row).issubset(FIELD_KEYS) and
           (FIELD_KEYS-set(row)).issubset(NULLABLE),
           "unexpected_sample_fields")
    ensure(type(row["schema"]) is int and row["schema"] == 1,
           "unsupported_sample_version")
    ensure(row["source"] == SOURCE and row["provenance"] == ORIGIN,
           "unattested_source_required")
    ensure(row["source_interface"] == "eth0_0",
           "unexpected_counter_source")
    for field in REQUIRED_FALSE:
        ensure(row[field] is False, "forbidden_qualification_assertion_" + field)
    for field in OBSERVATION_FIELDS:
        ensure(row[field] in SOURCE_STATES, "bad_observation_" + field)
    out = {}
    for field in NUMERIC_LIMITS:
        val = row.get(field)
        if val is None:
            ensure(field in NULLABLE, "required_numeric_missing_" + field)
            out[field] = None
        else:
            out[field] = numeric(val, field)
    for status, metric in (
        ("cpu_sample_status", "cpu_busy_fraction"),
        ("memory_sample_status", "mem_total_kib"),
        ("memory_sample_status", "mem_available_kib"),
        ("process_memory_status", "current_process_rss_kib"),
        ("temperature_sample_status", "thermal_zone0_millidegc"),
        ("pon_observation", "actual_pon_state"),
        ("host_link_observation", "observed_host_link_mbps"),
    ):
        ensure((row[status] == "observed") == (out[metric] is not None),
               "observation_value_mismatch_" + metric)
    if out["mem_total_kib"] is not None:
        ensure(out["mem_available_kib"] <= out["mem_total_kib"],
               "memory_available_exceeds_total")
    return {
        **out,
        "pon_observation": row["pon_observation"],
        "host_link_observation": row["host_link_observation"],
        "host_counters_observation": row["host_counters_observation"],
    }


def screen(payload: object) -> dict:
    ensure(type(payload) is dict, "invalid_input_object")
    ensure(set(payload) == {"schema", "evidence_origin", "phase_samples"},
           "unexpected_input_fields")
    ensure(payload["schema"] == 1 and type(payload["schema"]) is int,
           "unsupported_input_version")
    ensure(payload["evidence_origin"] == ORIGIN, "only_unattested_evidence")
    samples = payload["phase_samples"]
    ensure(type(samples) is dict and set(samples) == set(PHASES),
           "missing_or_unknown_workload_phase")
    failures = set()
    phase_report = {}
    for phase, minimum in PHASES.items():
        rows = samples[phase]
        ensure(type(rows) is list and len(rows) <= MAX_ROWS_PER_PHASE,
               "invalid_phase_sample_count_" + phase)
        if len(rows) < minimum:
            failures.add("insufficient_samples_" + phase)
        values = [validate_row(row) for row in rows]
        absent = [key for key in (
            "cpu_busy_fraction", "mem_total_kib", "mem_available_kib",
            "current_process_rss_kib", "thermal_zone0_millidegc"
        ) if any(v[key] is None for v in values)]
        for key in absent:
            failures.add("unavailable_" + key + "_" + phase)
        if any(v["pon_observation"] != "observed" for v in values):
            failures.add("pon_status_unavailable_" + phase)
        if any(v["host_link_observation"] != "observed" or
               v["host_counters_observation"] != "observed"
               for v in values):
            failures.add("host_measurement_unavailable_" + phase)
        if any(v["actual_pon_state"] != 51 for v in values):
            failures.add("pon_not_associated_in_sample_" + phase)
        if any(v["observed_host_link_mbps"] is None or
               v["observed_host_link_mbps"] == 0 for v in values):
            failures.add("host_link_not_observed_up_" + phase)
        checks = (
            ("observation_duration_exceeds_candidate",
             "native_observation_window_seconds", MAX_OBS_WINDOW_SECONDS),
            ("cpu_load_exceeds_candidate",
             "cpu_busy_fraction", MAX_CPU_BUSY),
            ("process_rss_exceeds_candidate",
             "current_process_rss_kib", MAX_PROCESS_RSS_KIB),
            ("thermal_exceeds_candidate",
             "thermal_zone0_millidegc", MAX_THERMAL_MILLIC),
        )
        for reason, key, maximum in checks:
            if any(v[key] is not None and v[key] > maximum for v in values):
                failures.add(reason + "_" + phase)
        if any(v["mem_available_kib"] is not None and
               v["mem_available_kib"] < MIN_AVAILABLE_KIB
               for v in values):
            failures.add("memory_headroom_below_candidate_" + phase)
        phase_report[phase] = {
            "sample_count": len(values),
            "required_minimum": minimum,
            "observed_pon_samples": sum(
                v["pon_observation"] == "observed" for v in values),
            "observed_host_counter_samples": sum(
                v["host_counters_observation"] == "observed"
                for v in values),
            "worst_reported_observation_seconds": max(
                (v["native_observation_window_seconds"] for v in values),
                default=None),
            "highest_reported_cpu_busy_fraction": max(
                (v["cpu_busy_fraction"] for v in values
                 if v["cpu_busy_fraction"] is not None), default=None),
            "lowest_reported_available_memory_kib": min(
                (v["mem_available_kib"] for v in values
                 if v["mem_available_kib"] is not None), default=None),
            "highest_reported_process_rss_kib": max(
                (v["current_process_rss_kib"] for v in values
                 if v["current_process_rss_kib"] is not None), default=None),
            "highest_reported_temperature_millidegc": max(
                (v["thermal_zone0_millidegc"] for v in values
                 if v["thermal_zone0_millidegc"] is not None), default=None),
        }
    return {
        "schema": 1,
        "qualification": "CANDIDATE_NUMERIC_SCREEN_ONLY",
        "screen_status": (
            "reported_values_in_hypothetical_range" if not failures
            else "missing_or_out_of_hypothetical_range"
        ),
        "candidate_numeric_in_range": not failures,
        "issues": sorted(failures),
        "phases": phase_report,
        "direct_hardware_authorized": False,
        "hardware_qualified": False,
        "production_activation_approved": False,
        "native_cpu_ram_thermal_qualified": False,
        "forwarding_and_isp_availability_qualified": False,
        "real_power_and_reboot_recovery_qualified": False,
        "user_supplied_data_is_not_hardware_attestation": True,
        "requires_separately_authorized_direct_target_readback": True,
        "requires_recoverable_live_soak_and_traffic_comparison": True,
    }


def reject_duplicates(pairs):
    output = {}
    for key, value in pairs:
        ensure(key not in output, "duplicate_evidence_field")
        output[key] = value
    return output


def reject_json_constant(value):
    raise ValueError("nonfinite_evidence_constant")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        ensure(args.input.is_file() and not args.input.is_symlink(),
               "untrusted_or_missing_input")
        ensure(args.input.stat().st_size <= MAX_INPUT_BYTES,
               "evidence_input_too_large")
        evidence = json.loads(
            args.input.read_text(encoding="utf-8"),
            object_pairs_hook=reject_duplicates,
            parse_constant=reject_json_constant,
        )
        result = screen(evidence)
    except (ValueError, UnicodeError, OSError, json.JSONDecodeError) as exc:
        print(json.dumps({
            "schema": 1, "screen_status": "invalid_evidence",
            "reason": str(exc)[:100],
            "hardware_qualified": False,
            "production_activation_approved": False,
        }, sort_keys=True))
        return 2
    print(json.dumps(result, sort_keys=True, allow_nan=False,
                     separators=(",", ":")))
    return 0


if __name__ == "__main__":
    sys.exit(main())
