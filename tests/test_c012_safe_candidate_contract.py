"""Tests for C-012 lower-risk A-to-Z source readiness."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"
OUTPUT = ROOT / "docs/C-012-SAFE-CANDIDATE-CONTRACT.json"

sys.path.insert(0, str(TOOLS))
spec = importlib.util.spec_from_file_location(
    "c012_safe_contract", TOOLS / "build_c012_safe_candidate_contract.py")
contract = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(contract)


class C012SafeCandidateContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.report = contract.build(ROOT)
        cls.rows = {row["id"]: row for row in cls.report["candidates"]}

    def test_exact_candidate_set_and_live_activation_modes(self):
        self.assertEqual(
            set(self.rows), {"lang", "hostname", "timezone", "ntp_servers"})
        self.assertEqual(
            self.rows["lang"]["activation"],
            "LIVE_UCI_NEW_AUTHENTICATED_REQUEST")
        self.assertEqual(
            self.rows["hostname"]["activation"], "LIVE_SYSTEM_RELOAD")
        self.assertEqual(
            self.rows["timezone"]["activation"], "LIVE_SYSTEM_RELOAD")
        self.assertEqual(
            self.rows["ntp_servers"]["activation"], "LIVE_SYSNTPD_RELOAD")
        self.assertTrue(all(
            not row["requires_reboot_for_runtime_effect"]
            for row in self.rows.values()
        ))

    def test_all_four_have_source_activation_verifier_and_rollback(self):
        for row in self.rows.values():
            self.assertTrue(row["source_live_activation_present"])
            self.assertTrue(row["source_runtime_effect_verifier_present"])
            self.assertTrue(row["source_rollback_contract_present"])
            self.assertTrue(
                row["source_ready_for_bounded_live_qualification"])
        summary=self.report["summary"]
        self.assertEqual(summary["live_apply_paths_present"],4)
        self.assertEqual(summary["runtime_effect_verifiers_present"],4)
        self.assertEqual(summary["rollback_contracts_present"],4)
        self.assertEqual(
            summary["source_ready_for_bounded_live_qualification"],4)

    def test_existing_r9_baseline_is_not_rewritten_as_new_proof(self):
        proven = {
            field_id for field_id,row in self.rows.items()
            if row["runtime_effect_proven_on_current_r9_baseline"]
        }
        self.assertEqual(proven,{"hostname"})
        self.assertEqual(
            self.report["summary"]
            ["current_r9_baseline_runtime_effect_proven"],1)

    def test_source_ready_is_not_hardware_qualified_or_preapproved(self):
        self.assertEqual(
            self.report["summary"]["full_end_to_end_hardware_qualified"],0)
        self.assertEqual(self.report["summary"]["hardware_qualified"],0)
        for row in self.rows.values():
            self.assertFalse(row["full_end_to_end_hardware_qualified"])
            self.assertFalse(row["mutation_permitted_by_this_artifact"])
            self.assertTrue(row["requires_explicit_live_authorization"])
            self.assertFalse(row["hardware_qualified"])
            self.assertTrue(row["blockers"])

    def test_source_facts_fail_closed_on_missing_a_to_z_primitives(self):
        facts=self.report["source_facts"]
        for key,value in facts.items():
            with self.subTest(key=key):
                self.assertTrue(value)

    def test_generated_contract_matches_source(self):
        committed=json.loads(OUTPUT.read_text())
        self.assertEqual(committed,self.report)
        self.assertFalse(committed["live_device_queried"])
        self.assertFalse(committed["device_configuration_modified"])
        self.assertFalse(committed["firmware_modified"])
        self.assertFalse(committed["contains_runtime_values_or_credentials"])
        self.assertFalse(
            committed["policy"]["generic_continue_authorizes_mutation"])
        self.assertTrue(
            committed["policy"]["source_ready_is_not_live_mutation_approval"])

    def test_generator_has_no_device_transport_or_setter(self):
        source=(TOOLS/"build_c012_safe_candidate_contract.py").read_text()
        for forbidden in (
            "subprocess.","socket.","paramiko","curl ","ssh ",
            "fw_setenv","fw_setenv_8311","ubiupdatevol",
            "8311-bankctl.sh guarded","/sbin/reboot",
        ):
            self.assertNotIn(forbidden,source)


if __name__=="__main__":
    unittest.main()
