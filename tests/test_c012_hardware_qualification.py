"""C-012 source-derived PRX126 hardware qualification matrix tests."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"
MATRIX_PATH = ROOT / "docs/C-012-HARDWARE-QUALIFICATION-MATRIX.json"
BASELINE_PATH = ROOT / "docs/C-012-PRX126-READONLY-BASELINE.json"

sys.path.insert(0, str(TOOLS))
import build_capability_registry as registry  # noqa: E402

spec = importlib.util.spec_from_file_location(
    "c012_hardware_matrix", TOOLS / "build_c012_hardware_qualification.py")
matrix = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(matrix)


class C012HardwareQualificationMatrixTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.report = matrix.build(ROOT)
        cls.registry = registry.build(ROOT)
        cls.rows = {row["id"]: row for row in cls.report["fields"]}
        cls.source_ids = {
            row["id"] for row in
            cls.registry["firmware_environment_gui_fields"]
        }

    def test_exactly_all_54_registry_fields_once(self):
        self.assertEqual(len(self.report["fields"]), 54)
        self.assertEqual(len(self.rows), 54)
        self.assertEqual(set(self.rows), self.source_ids)
        self.assertEqual(self.report["summary"]["fields"], 54)
        self.assertEqual(self.report["summary"]["read_only_baseline_first"], 54)

    def test_readback_groups_are_complete_and_nonoverlapping(self):
        mapped = matrix.group_map()
        self.assertEqual(set(mapped), self.source_ids)
        self.assertEqual(sum(
            self.report["summary"]["readback_groups"].values()), 54)
        self.assertEqual(
            self.report["summary"]["readback_groups"],
            {
                "advanced_hardware": 8,
                "device_and_virtual_sfp": 11,
                "isp_vlan": 3,
                "management": 9,
                "omci_reporting": 10,
                "pon_omci_noncredential": 4,
                "sensitive_identity": 9,
            },
        )

    def test_mutation_lanes_are_conservative_and_exhaustive(self):
        self.assertEqual(
            self.report["summary"]["mutation_lanes"],
            {
                "RECOVERY_PATH_REQUIRED": 25,
                "SAFE_LIVE_APPLY_CANDIDATE": 4,
                "TEST_OLT_OR_SPARE_REQUIRED": 25,
            },
        )
        safe = {
            field_id for field_id, row in self.rows.items()
            if row["mutation_lane"] == "SAFE_LIVE_APPLY_CANDIDATE"
        }
        self.assertEqual(safe, {"lang", "hostname", "timezone", "ntp_servers"})
        for field_id in matrix.READBACK_GROUPS["management"]["ids"]:
            self.assertEqual(
                self.rows[field_id]["mutation_lane"],
                "RECOVERY_PATH_REQUIRED",
            )
        for field_id in matrix.READBACK_GROUPS["isp_vlan"]["ids"]:
            self.assertEqual(
                self.rows[field_id]["mutation_lane"],
                "TEST_OLT_OR_SPARE_REQUIRED",
            )

    def test_no_source_evidence_becomes_a_hardware_claim(self):
        self.assertEqual(
            self.report["summary"]["hardware_qualified_fields"], 0)
        for row in self.rows.values():
            self.assertFalse(row["hardware_qualified"])
            self.assertEqual(
                row["qualification_status"],
                "PLANNED_NOT_HARDWARE_QUALIFIED",
            )
            self.assertEqual(row["first_hardware_action"],
                             "READ_ONLY_BASELINE")
            self.assertTrue(row["read_only_baseline_permitted"])
            self.assertFalse(row["mutation_permitted_by_this_artifact"])
            self.assertTrue(row["requires_explicit_live_authorization"])
            self.assertTrue(all(
                value is False for value in row["proof_stages"].values()))

    def test_secrets_and_identity_fields_never_become_safe_by_validation(self):
        protected_ids = {
            row["id"] for row in self.rows.values()
            if row["secret_handling_required"]
        }
        self.assertEqual(protected_ids, {"reg_id_hex", "lpwd", "root_pwhash"})
        for field_id in protected_ids:
            self.assertNotEqual(
                self.rows[field_id]["mutation_lane"],
                "SAFE_LIVE_APPLY_CANDIDATE",
            )
        self.assertEqual(
            self.rows["reg_id_hex"]["mutation_lane"],
            "TEST_OLT_OR_SPARE_REQUIRED",
        )
        self.assertEqual(
            self.rows["lpwd"]["mutation_lane"],
            "TEST_OLT_OR_SPARE_REQUIRED",
        )
        self.assertEqual(
            self.rows["root_pwhash"]["mutation_lane"],
            "RECOVERY_PATH_REQUIRED",
        )

    def test_pon_reporting_and_service_fields_require_controlled_hardware(self):
        protected = (
            matrix.READBACK_GROUPS["pon_omci_noncredential"]["ids"]
            | matrix.READBACK_GROUPS["omci_reporting"]["ids"]
            | (matrix.READBACK_GROUPS["sensitive_identity"]["ids"]
               - {"root_pwhash"})
            | matrix.READBACK_GROUPS["isp_vlan"]["ids"]
        )
        self.assertEqual(len(protected), 25)
        for field_id in protected:
            self.assertEqual(
                self.rows[field_id]["mutation_lane"],
                "TEST_OLT_OR_SPARE_REQUIRED",
            )
            self.assertIn(
                "spare or explicitly recoverable test ONU",
                self.rows[field_id]["mutation_prerequisites"],
            )

    def test_committed_json_is_deterministic_and_source_only(self):
        committed = json.loads(MATRIX_PATH.read_text())
        current = dict(self.report)
        current["source_gui_sha256"] = committed["source_gui_sha256"]
        self.assertEqual(committed, current)
        self.assertEqual(committed["baseline_release"], "AoTT-8311-v2r9")
        self.assertFalse(committed["live_device_queried"])
        self.assertFalse(committed["device_configuration_modified"])
        self.assertFalse(committed["firmware_modified"])
        self.assertFalse(committed["contains_runtime_values_or_credentials"])
        self.assertFalse(
            committed["policy"]["generic_continue_authorizes_live_mutation"])

    def test_public_readonly_baseline_is_value_free_and_bounded(self):
        baseline = json.loads(BASELINE_PATH.read_text())
        self.assertEqual(
            baseline["status"], "C012_PRX126_READONLY_BASELINE_PUBLIC_SAFE")
        self.assertEqual(baseline["summary"]["fields_accounted"], 54)
        self.assertEqual(
            baseline["summary"]["read_only_baselines_observed"], 54)
        self.assertEqual(
            baseline["summary"]["runtime_effect_proven_ids"],
            ["gateway", "hostname", "ipaddr", "lct_mac", "netmask"],
        )
        self.assertEqual(
            baseline["summary"]["fully_hardware_qualified_fields"], 0)
        self.assertEqual(
            {row["id"] for row in baseline["fields"]}, self.source_ids)
        self.assertTrue(all(
            row["hardware_qualified"] is False
            for row in baseline["fields"]))
        safety = baseline["safety"]
        for key in (
            "raw_setting_values_included",
            "subscriber_identity_values_included",
            "credential_values_or_hashes_included",
            "private_network_addresses_included",
            "mac_addresses_included",
            "boot_id_included",
            "device_writes",
            "firmware_writes",
            "reboot",
            "bank_state_changed",
        ):
            self.assertFalse(safety[key])
        self.assertTrue(safety["before_after_device_state_identical"])

    def test_tool_has_no_device_transport_or_mutation_dispatch(self):
        source = (TOOLS / "build_c012_hardware_qualification.py").read_text()
        for forbidden in (
            "subprocess.", "socket.", "paramiko", "ssh ", "curl ",
            "fw_setenv", "ubiupdatevol", "8311-bankctl.sh",
        ):
            self.assertNotIn(forbidden, source)


if __name__ == "__main__":
    unittest.main()
