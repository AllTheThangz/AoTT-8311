#!/usr/bin/env python3
"""Build the C-012 source contract for the four lower-risk A-to-Z candidates.

This artifact distinguishes source readiness from hardware qualification.
It performs no device or network I/O and grants no mutation authorization.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys

import build_c012_hardware_qualification as qualification

CANDIDATES = ("lang", "hostname", "timezone", "ntp_servers")
CONFIG = Path("overlay/usr/lib/lua/8311/config.lua")
ACTIVATION = Path("overlay/usr/lib/lua/8311/config_activation.lua")
DEVICE_STATE = Path("overlay/usr/lib/lua/8311/effective_device_state.lua")
DEVICE_PROBE = Path("overlay/usr/lib/lua/8311/effective_device_probe.lua")
BASELINE = Path("docs/C-012-PRX126-READONLY-BASELINE.json")

EXPECTED = {
    "lang": {
        "schema_type": "select_named",
        "activation": "LIVE_UCI_NEW_AUTHENTICATED_REQUEST",
        "current_effect_evidence": "ACTIVE_LUCI_REQUEST_VERIFIER_AVAILABLE",
        "requires_reboot_for_runtime_effect": False,
        "blockers": [
            "authorized live apply and restore evidence",
            "reboot persistence and postboot restore evidence",
        ],
    },
    "hostname": {
        "schema_type": "text",
        "activation": "LIVE_SYSTEM_RELOAD",
        "current_effect_evidence": "KERNEL_HOSTNAME_VERIFIER_AVAILABLE",
        "requires_reboot_for_runtime_effect": False,
        "blockers": [
            "authorized live apply and restore evidence",
            "reboot persistence and postboot restore evidence",
        ],
    },
    "timezone": {
        "schema_type": "select",
        "activation": "LIVE_SYSTEM_RELOAD",
        "current_effect_evidence": "ACTIVE_LOCALTIME_VERIFIER_AVAILABLE",
        "requires_reboot_for_runtime_effect": False,
        "blockers": [
            "authorized live apply and restore evidence",
            "reboot persistence and postboot restore evidence",
        ],
    },
    "ntp_servers": {
        "schema_type": "text",
        "activation": "LIVE_SYSNTPD_RELOAD",
        "current_effect_evidence": "ACTIVE_NTP_PEER_ARGUMENT_VERIFIER_AVAILABLE",
        "requires_reboot_for_runtime_effect": False,
        "blockers": [
            "authorized live apply and restore evidence",
            "reboot persistence and postboot restore evidence",
            "clock synchronization remains separate from configured-peer proof",
        ],
    },
}


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def source_facts(root: Path) -> dict:
    config = (root / CONFIG).read_text()
    activation = (root / ACTIVATION).read_text()
    state = (root / DEVICE_STATE).read_text()
    probe = (root / DEVICE_PROBE).read_text()

    facts = {
        "config_delegates_to_live_activation_layer": (
            'pcall(require,"8311.config_activation")' in config and
            "activation.apply(prepared.changes)" in config
        ),
        "transaction_restores_saved_environment_on_failure": (
            "restore_environment(snapshot,prepared.changes)" in config and
            "saved_rollback_succeeded" in config
        ),
        "activation_scope_contains_all_four_candidates": all(
            token in activation for token in (
                "lang=true", "hostname=true", "timezone=true",
                "ntp_servers=true",
            )
        ),
        "hostname_live_reload_and_kernel_verifier": (
            '"/etc/init.d/system"' in activation and
            '"/proc/sys/kernel/hostname"' in activation
        ),
        "timezone_live_reload_and_localtime_verifier": (
            'fs.readlink("/tmp/localtime")' in activation and
            'timezone_file(desired)' in activation
        ),
        "ntp_live_reload_and_process_argument_verifier": (
            '"/etc/init.d/sysntpd"' in activation and
            '"/bin/pidof","ntpd"' in activation and
            '"active_ntpd_process_arguments"' in activation
        ),
        "language_requires_new_authenticated_request": (
            '"next_authenticated_luci_request"' in activation and
            "requires_new_authenticated_request" in activation
        ),
        "language_request_verifier_exists": (
            "active_luci_request_language" in state and
            "active_language=function()" in probe
        ),
        "device_probe_verifies_hostname_timezone_ntp": all(
            token in probe for token in (
                'fs.readfile("/proc/sys/kernel/hostname",128)',
                'fs.readlink("/tmp/localtime")',
                '"/bin/pidof","ntpd"',
            )
        ),
        "runtime_mismatch_rolls_back": (
            '"runtime_effect_mismatch"' in activation and
            "rollback_attempted" in activation and
            "rollback_succeeded" in activation
        ),
    }
    require(all(facts.values()), "SAFE_CANDIDATE_SOURCE_CONTRACT_DRIFT")
    return facts


def build(root: Path) -> dict:
    root = root.resolve(strict=True)
    plan = qualification.build(root)
    fields = {row["id"]: row for row in plan["fields"]}
    require(set(CANDIDATES) <= set(fields), "SAFE_CANDIDATE_MISSING_FROM_MATRIX")
    require(all(fields[x]["mutation_lane"] == "SAFE_LIVE_APPLY_CANDIDATE"
                for x in CANDIDATES), "SAFE_CANDIDATE_LANE_DRIFT")

    baseline = json.loads((root / BASELINE).read_text())
    require(
        baseline["status"] == "C012_PRX126_READONLY_BASELINE_PUBLIC_SAFE",
        "READONLY_BASELINE_STATUS_CHANGED",
    )
    baseline_rows = {row["id"]: row for row in baseline["fields"]}
    require(set(CANDIDATES) <= set(baseline_rows),
            "SAFE_CANDIDATE_BASELINE_MISSING")

    facts = source_facts(root)
    rows = []
    for field_id in CANDIDATES:
        expected = EXPECTED[field_id]
        require(fields[field_id]["schema_type"] == expected["schema_type"],
                "SAFE_CANDIDATE_SCHEMA_DRIFT_" + field_id)
        observed_effect = baseline_rows[field_id]["runtime_effect_proven"]
        rows.append({
            "id": field_id,
            "schema_type": expected["schema_type"],
            "activation": expected["activation"],
            "current_effect_evidence": expected["current_effect_evidence"],
            "read_only_baseline_observed": True,
            "runtime_effect_proven_on_current_r9_baseline": observed_effect,
            "source_live_activation_present": True,
            "source_runtime_effect_verifier_present": True,
            "source_rollback_contract_present": True,
            "source_ready_for_bounded_live_qualification": True,
            "requires_reboot_for_runtime_effect":
                expected["requires_reboot_for_runtime_effect"],
            "full_end_to_end_hardware_qualified": False,
            "blockers": expected["blockers"],
            "mutation_permitted_by_this_artifact": False,
            "requires_explicit_live_authorization": True,
            "hardware_qualified": False,
        })

    require(sum(x["source_ready_for_bounded_live_qualification"]
                for x in rows) == 4,
            "SAFE_CANDIDATE_SOURCE_READINESS_INCOMPLETE")
    require(sum(x["hardware_qualified"] for x in rows) == 0,
            "SAFE_CANDIDATE_PREMATURE_HARDWARE_QUALIFICATION")
    return {
        "schema": 2,
        "contract_kind":
            "C012_SAFE_CANDIDATE_SOURCE_READY_HARDWARE_UNQUALIFIED",
        "hardware_profile": qualification.BOARD_PROFILE,
        "baseline_release": "AoTT-8311-v2r9",
        "source_facts": facts,
        "candidates": rows,
        "summary": {
            "candidate_fields": 4,
            "live_apply_paths_present": 4,
            "runtime_effect_verifiers_present": 4,
            "rollback_contracts_present": 4,
            "source_ready_for_bounded_live_qualification": 4,
            "current_r9_baseline_runtime_effect_proven":
                sum(bool(baseline_rows[x]["runtime_effect_proven"])
                    for x in CANDIDATES),
            "full_end_to_end_hardware_qualified": 0,
            "hardware_qualified": 0,
        },
        "policy": {
            "source_ready_is_not_live_mutation_approval": True,
            "generic_continue_authorizes_mutation": False,
            "hardware_qualification_requires_apply_effect_persistence_recovery":
                True,
            "clock_sync_is_not_inferred_from_ntp_peer_configuration": True,
        },
        "live_device_queried": False,
        "device_configuration_modified": False,
        "firmware_modified": False,
        "contains_runtime_values_or_credentials": False,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path,
                        default=Path(__file__).resolve().parents[1])
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = build(args.source_root)

    if args.output is not None:
        root = args.source_root.resolve(strict=True)
        output = args.output
        require(output.is_absolute() and output.suffix == ".json",
                "OUTPUT_MUST_BE_ABSOLUTE_JSON")
        require(output.parent.resolve(strict=True) == root / "docs",
                "OUTPUT_MUST_BE_INSIDE_DOCS")
        require(not output.exists() and not output.is_symlink(),
                "REFUSE_TO_OVERWRITE_SAFE_CANDIDATE_CONTRACT")
        payload = (json.dumps(report, indent=2, sort_keys=True) + "\n").encode()
        os.umask(0o077)
        fd = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL |
                     os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())

    print(json.dumps({
        "status": "C012_SAFE_CANDIDATE_CONTRACT_PASS",
        **report["summary"],
        "live_device_queried": False,
        "device_configuration_modified": False,
        "output": str(args.output) if args.output else None,
    }, sort_keys=True))


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print("C012_SAFE_CONTRACT_STOP:" + str(exc)[:180], file=sys.stderr)
        raise SystemExit(1)
