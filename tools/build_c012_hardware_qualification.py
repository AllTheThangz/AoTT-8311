#!/usr/bin/env python3
"""Build the source-only C-012 PRX126 hardware qualification matrix.

This tool consumes the canonical 55-field capability registry. It assigns
conservative hardware-test lanes and required proof stages. It never reads a
live ONU, never changes firmware, and never upgrades source evidence into a
hardware-qualified claim.
"""
from __future__ import annotations

import argparse
from collections import Counter
import json
import os
from pathlib import Path
import sys

import build_capability_registry as registry


BOARD_PROFILE = "potron-prx126-aott-v1"
MATRIX_STATUS = "SOURCE_DERIVED_HARDWARE_QUALIFICATION_PLAN_ONLY"

READBACK_GROUPS = {
    "management": {
        "module": "overlay/usr/lib/lua/8311/effective_state.lua",
        "ids": {
            "lct_vlan", "ipaddr", "netmask", "gateway", "dns_server", "pingd",
            "ping_ip", "lct_mac", "reverse_arp", "https_redirect",
        },
    },
    "device_and_virtual_sfp": {
        "module": "overlay/usr/lib/lua/8311/effective_device_state.lua",
        "ids": {
            "hostname", "lang", "timezone", "ntp_servers",
            "sfp_vendor", "sfp_oui", "sfp_partno", "sfp_rev",
            "sfp_serial", "sfp_date", "sfp_vendordata",
        },
    },
    "advanced_hardware": {
        "module": "overlay/usr/lib/lua/8311/effective_hardware_state.lua",
        "ids": {
            "bootdelay", "uart_select", "console_en", "dying_gasp_en",
            "rx_los", "ethtool_speed", "failsafe_delay", "persist_root",
        },
    },
    "sensitive_identity": {
        "module": "overlay/usr/lib/lua/8311/effective_identity_state.lua",
        "ids": {
            "gpon_sn", "vendor_id", "reg_id_hex", "loid", "lpwd",
            "iphost_mac", "iphost_hostname", "iphost_domain", "root_pwhash",
        },
    },
    "pon_omci_noncredential": {
        "module": "overlay/usr/lib/lua/8311/effective_pon_state.lua",
        "ids": {"pon_mode", "omcc_version", "iop_mask", "mib_file"},
    },
    "omci_reporting": {
        "module": "overlay/usr/lib/lua/8311/effective_reporting_state.lua",
        "ids": {
            "equipment_id", "hw_ver", "cp_hw_ver_sync", "sw_verA",
            "sw_verB", "fw_match_b64", "fw_match_num", "override_active",
            "override_commit", "pon_slot",
        },
    },
    "isp_vlan": {
        "module": "overlay/usr/lib/lua/8311/effective_vlan_state.lua",
        "ids": {"fix_vlans", "internet_vlan", "services_vlan"},
    },
}

SAFE_LIVE_APPLY_CANDIDATE = {
    "lang", "hostname", "timezone", "ntp_servers",
}

TEST_OLT_OR_SPARE_REQUIRED = (
    READBACK_GROUPS["sensitive_identity"]["ids"] - {"root_pwhash"}
    | READBACK_GROUPS["pon_omci_noncredential"]["ids"]
    | READBACK_GROUPS["omci_reporting"]["ids"]
    | READBACK_GROUPS["isp_vlan"]["ids"]
)

RECOVERY_PATH_REQUIRED = (
    READBACK_GROUPS["management"]["ids"]
    | READBACK_GROUPS["advanced_hardware"]["ids"]
    | (READBACK_GROUPS["device_and_virtual_sfp"]["ids"]
       - SAFE_LIVE_APPLY_CANDIDATE)
    | {"root_pwhash"}
)

PROOF_STAGES = (
    "saved_value_readback",
    "read_only_effective_baseline",
    "validated_preview",
    "native_apply",
    "durable_readback",
    "effective_readback",
    "service_consequence",
    "restart_or_reload_behavior",
    "reboot_persistence",
    "recovery_or_revert",
    "negative_and_failure_cases",
)


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def group_map() -> dict[str, tuple[str, str]]:
    result: dict[str, tuple[str, str]] = {}
    for group, record in READBACK_GROUPS.items():
        for field_id in record["ids"]:
            require(field_id not in result, "DUPLICATE_READBACK_GROUP_" + field_id)
            result[field_id] = (group, record["module"])
    return result


def mutation_lane(field_id: str) -> str:
    lanes = []
    if field_id in SAFE_LIVE_APPLY_CANDIDATE:
        lanes.append("SAFE_LIVE_APPLY_CANDIDATE")
    if field_id in RECOVERY_PATH_REQUIRED:
        lanes.append("RECOVERY_PATH_REQUIRED")
    if field_id in TEST_OLT_OR_SPARE_REQUIRED:
        lanes.append("TEST_OLT_OR_SPARE_REQUIRED")
    require(len(lanes) == 1, "MUTATION_LANE_NOT_EXACT_" + field_id)
    return lanes[0]


def lane_prerequisites(lane: str) -> list[str]:
    if lane == "SAFE_LIVE_APPLY_CANDIDATE":
        return [
            "fresh read-only baseline",
            "explicit per-operation authorization",
            "known original value and bounded revert",
        ]
    if lane == "RECOVERY_PATH_REQUIRED":
        return [
            "fresh read-only baseline",
            "independent alternate recovery path",
            "explicit per-operation authorization",
            "bounded revert verified before mutation",
        ]
    if lane == "TEST_OLT_OR_SPARE_REQUIRED":
        return [
            "fresh read-only baseline",
            "spare or explicitly recoverable test ONU",
            "compatible test OLT or controlled service profile where applicable",
            "explicit per-operation authorization",
            "known-good identity/service restore path",
        ]
    raise ValueError("UNKNOWN_LANE_" + lane)


def build(source_root: Path) -> dict:
    source_root = source_root.resolve(strict=True)
    canonical = registry.build(source_root)
    fields = canonical["firmware_environment_gui_fields"]
    require(len(fields) == 55, "CANONICAL_FIELD_COUNT_CHANGED")

    mapped = group_map()
    source_ids = {row["id"] for row in fields}
    require(len(source_ids) == 55, "CANONICAL_FIELD_IDS_NOT_UNIQUE")
    require(set(mapped) == source_ids, "READBACK_GROUP_UNION_NOT_55_FIELDS")

    lane_union = (SAFE_LIVE_APPLY_CANDIDATE
                  | RECOVERY_PATH_REQUIRED
                  | TEST_OLT_OR_SPARE_REQUIRED)
    require(lane_union == source_ids, "MUTATION_LANE_UNION_NOT_55_FIELDS")
    require(not (SAFE_LIVE_APPLY_CANDIDATE & RECOVERY_PATH_REQUIRED),
            "SAFE_AND_RECOVERY_LANES_OVERLAP")
    require(not (SAFE_LIVE_APPLY_CANDIDATE & TEST_OLT_OR_SPARE_REQUIRED),
            "SAFE_AND_OLT_LANES_OVERLAP")
    require(not (RECOVERY_PATH_REQUIRED & TEST_OLT_OR_SPARE_REQUIRED),
            "RECOVERY_AND_OLT_LANES_OVERLAP")

    rows = []
    for source in fields:
        field_id = source["id"]
        group, module = mapped[field_id]
        lane = mutation_lane(field_id)
        protected_value = source["sensitivity"] == "secret"
        identity = source["sensitivity"] == "potential_device_identity"
        require(not (protected_value and lane == "SAFE_LIVE_APPLY_CANDIDATE"),
                "SECRET_FIELD_CLASSIFIED_SAFE_" + field_id)

        rows.append({
            "id": field_id,
            "category": source["category"],
            "schema_type": source["schema_type"],
            "readback_group": group,
            "effective_state_module": module,
            "source_evidence_level": source["evidence_level"],
            "static_getter_found":
                source["static_source_checks"]["static_getter_found"],
            "static_setter_found":
                source["static_source_checks"]["static_setter_found"],
            "startup_script_reference_found":
                source["static_source_checks"]["startup_script_reference_found"],
            "sensitivity": source["sensitivity"],
            "risk": source["risk"],
            "secret_handling_required": protected_value,
            "identity_handling_required": identity,
            "first_hardware_action": "READ_ONLY_BASELINE",
            "mutation_lane": lane,
            "mutation_prerequisites": lane_prerequisites(lane),
            "proof_stages": {stage: False for stage in PROOF_STAGES},
            "read_only_baseline_permitted": True,
            "mutation_permitted_by_this_artifact": False,
            "requires_explicit_live_authorization": True,
            "hardware_qualified": False,
            "qualification_status": "PLANNED_NOT_HARDWARE_QUALIFIED",
        })

    lane_counts = Counter(row["mutation_lane"] for row in rows)
    group_counts = Counter(row["readback_group"] for row in rows)
    require(lane_counts == Counter({
        "SAFE_LIVE_APPLY_CANDIDATE": 4,
        "RECOVERY_PATH_REQUIRED": 26,
        "TEST_OLT_OR_SPARE_REQUIRED": 25,
    }), "MUTATION_LANE_COUNTS_CHANGED")
    require(sum(group_counts.values()) == 55, "READBACK_GROUP_COUNT_CHANGED")

    return {
        "schema": 1,
        "matrix_kind": MATRIX_STATUS,
        "hardware_profile": BOARD_PROFILE,
        "baseline_release": "AoTT-8311-v2r9",
        "source_registry_kind": canonical["registry_kind"],
        "source_gui_sha256": canonical["source_gui_sha256"],
        "source_server_validator_sha256":
            canonical["source_server_validator_sha256"],
        "proof_stage_order": list(PROOF_STAGES),
        "fields": rows,
        "summary": {
            "fields": len(rows),
            "read_only_baseline_first": len(rows),
            "mutation_lanes": dict(sorted(lane_counts.items())),
            "readback_groups": dict(sorted(group_counts.items())),
            "secret_fields": sum(row["secret_handling_required"] for row in rows),
            "identity_fields":
                sum(row["identity_handling_required"] for row in rows),
            "hardware_qualified_fields": 0,
        },
        "policy": {
            "source_evidence_never_implies_hardware_qualification": True,
            "generic_continue_authorizes_live_mutation": False,
            "read_only_baseline_changes_device": False,
            "safe_live_candidate_means_preferred_test_order_not_preapproved":
                True,
            "test_olt_or_spare_lane_may_not_use_only_production_connection":
                True,
        },
        "contains_runtime_values_or_credentials": False,
        "live_device_queried": False,
        "device_configuration_modified": False,
        "firmware_modified": False,
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
                "REFUSE_TO_OVERWRITE_MATRIX")
        data = (json.dumps(report, indent=2, sort_keys=True) + "\n").encode()
        os.umask(0o077)
        fd = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL |
                     os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())

    print(json.dumps({
        "status": "C012_HARDWARE_QUALIFICATION_MATRIX_PASS",
        "fields": report["summary"]["fields"],
        "mutation_lanes": report["summary"]["mutation_lanes"],
        "hardware_qualified_fields": 0,
        "live_device_queried": False,
        "device_configuration_modified": False,
        "output": str(args.output) if args.output else None,
    }, sort_keys=True))


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print("C012_MATRIX_STOP:" + str(exc)[:180], file=sys.stderr)
        raise SystemExit(1)
