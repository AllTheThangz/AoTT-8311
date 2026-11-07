#!/usr/bin/env python3
"""Build the C-012 source-only contract for the four lower-risk candidates.

The contract prevents a lower-risk test lane from being mistaken for readiness
to mutate the committed ONU. It inspects the shipped r9 source and the public
read-only hardware baseline. It performs no device or network I/O.
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
DEVICE_STATE = Path("overlay/usr/lib/lua/8311/effective_device_state.lua")
DEVICE_PROBE = Path("overlay/usr/lib/lua/8311/effective_device_probe.lua")
BASELINE = Path("docs/C-012-PRX126-READONLY-BASELINE.json")

EXPECTED = {
    "lang": {
        "schema_type": "select_named",
        "activation": "LIVE_UCI_APPLY_AFTER_SAVE",
        "current_effect_evidence": "CONFIGURED_UCI_ONLY",
        "partial_no_reboot_apply_test_ready": True,
        "full_end_to_end_ready": False,
        "requires_reboot_for_current_source_path": False,
        "blockers": [
            "independent authenticated active-session language verifier",
            "bounded automatic revert verification",
        ],
    },
    "hostname": {
        "schema_type": "text",
        "activation": "NEXT_STARTUP_REQUIRED",
        "current_effect_evidence": "KERNEL_HOSTNAME_READBACK_AVAILABLE",
        "partial_no_reboot_apply_test_ready": True,
        "full_end_to_end_ready": False,
        "requires_reboot_for_current_source_path": True,
        "blockers": [
            "authorized reboot persistence test",
            "postboot effective readback and bounded revert",
        ],
    },
    "timezone": {
        "schema_type": "select",
        "activation": "NEXT_STARTUP_REQUIRED",
        "current_effect_evidence": "CONFIGURED_UCI_ONLY",
        "partial_no_reboot_apply_test_ready": True,
        "full_end_to_end_ready": False,
        "requires_reboot_for_current_source_path": True,
        "blockers": [
            "independent active local-time/timezone verifier",
            "authorized reboot persistence test",
            "postboot revert verification",
        ],
    },
    "ntp_servers": {
        "schema_type": "text",
        "activation": "NEXT_STARTUP_REQUIRED",
        "current_effect_evidence": "CONFIGURED_UCI_ONLY",
        "partial_no_reboot_apply_test_ready": True,
        "full_end_to_end_ready": False,
        "requires_reboot_for_current_source_path": True,
        "blockers": [
            "independent running NTP configuration verifier",
            "bounded synchronization evidence that does not expose server values",
            "authorized reboot persistence test",
            "postboot revert verification",
        ],
    },
}


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def source_facts(root: Path) -> dict:
    config = (root / CONFIG).read_text()
    state = (root / DEVICE_STATE).read_text()
    probe = (root / DEVICE_PROBE).read_text()

    facts = {
        "generic_diff_marks_only_lang_live": (
            'item.id == "lang" and "Web interface after save" or '
            '"Next startup; live consumers may also re-read it"' in config
        ),
        "lang_has_explicit_live_uci_set": (
            'if change.item.id == "lang" then' in config and
            'luci.main.lang=' in config and
            'commit", "luci"' in config
        ),
        "hostname_has_kernel_effect_probe": (
            'set_observed(fields.hostname,actual_hostname,'
            '"kernel_proc_hostname")' in state and
            'fs.readfile("/proc/sys/kernel/hostname",128)' in probe
        ),
        "lang_explicitly_not_active_session_proof": (
            "luci_config_not_active_session_language_proof" in state
        ),
        "timezone_explicitly_not_active_localtime_proof": (
            "uci_zonename_not_active_localtime_proof" in state
        ),
        "ntp_explicitly_not_sync_proof": (
            "configured_servers_do_not_prove_ntp_sync" in state
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
    require(baseline["status"] ==
            "C012_PRX126_READONLY_BASELINE_PUBLIC_SAFE",
            "READONLY_BASELINE_STATUS_CHANGED")
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
        if field_id == "hostname":
            require(observed_effect is True,
                    "HOSTNAME_BASELINE_EFFECT_PROOF_MISSING")
        else:
            require(observed_effect is False,
                    "UNEXPECTED_SAFE_CANDIDATE_EFFECT_" + field_id)

        rows.append({
            "id": field_id,
            "schema_type": expected["schema_type"],
            "activation": expected["activation"],
            "current_effect_evidence": expected["current_effect_evidence"],
            "read_only_baseline_observed": True,
            "runtime_effect_proven_on_current_baseline": observed_effect,
            "partial_no_reboot_apply_test_ready":
                expected["partial_no_reboot_apply_test_ready"],
            "full_end_to_end_ready": expected["full_end_to_end_ready"],
            "requires_reboot_for_current_source_path":
                expected["requires_reboot_for_current_source_path"],
            "blockers": expected["blockers"],
            "mutation_permitted_by_this_artifact": False,
            "requires_explicit_live_authorization": True,
            "hardware_qualified": False,
        })

    require(sum(x["full_end_to_end_ready"] for x in rows) == 0,
            "SAFE_CANDIDATE_PREMATURELY_READY")
    return {
        "schema": 1,
        "contract_kind": "C012_SAFE_CANDIDATE_SOURCE_READINESS_ONLY",
        "hardware_profile": qualification.BOARD_PROFILE,
        "baseline_release": "AoTT-8311-v2r9",
        "source_facts": facts,
        "candidates": rows,
        "summary": {
            "candidate_fields": 4,
            "live_apply_paths_present": 1,
            "next_startup_paths": 3,
            "current_runtime_effect_proven": 1,
            "partial_no_reboot_apply_test_ready": 4,
            "full_end_to_end_ready": 0,
            "hardware_qualified": 0,
        },
        "policy": {
            "lower_risk_lane_is_not_live_mutation_approval": True,
            "generic_continue_authorizes_mutation": False,
            "full_test_requires_effect_persistence_and_recovery_evidence": True,
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
