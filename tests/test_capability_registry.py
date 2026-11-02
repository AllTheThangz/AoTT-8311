"""Source-only, privilege-free capability registry contract.

This test never contacts a deployed ONU or changes boot-environment/UCI,
certificate material, network interfaces or firmware banks.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"
sys.path.insert(0, str(TOOLS))
import audit_configurability as inventory
import build_capability_registry as registry

OFFLINE_VENDOR = Path(os.environ.get("AOTT_VENDOR_ROOTFS",
                                    "/not-mounted/offline-vendor"))


class CapabilityRegistryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.report = registry.build(
            ROOT,
            OFFLINE_VENDOR if os.environ.get("AOTT_VENDOR_ROOTFS") else None,
        )
        cls.fields = {row["id"]: row
                      for row in cls.report["firmware_environment_gui_fields"]}
        cls.missing = {row["id"]: row
                       for row in cls.report["missing_or_hidden_environment_candidates"]}

    def test_canonical_gui_schema_is_not_a_separate_handwritten_duplicate(self):
        original = inventory.inspect(ROOT)
        self.assertEqual(len(self.fields), 54)
        self.assertEqual(set(self.fields), {x["id"] for x in original["gui_fields"]})
        self.assertEqual(self.report["summary"]["by_gui_group"], {
            "pon":22, "isp":3, "device":13, "sfp":7, "manage":9,
        })
        for r in original["gui_fields"]:
            self.assertEqual(self.fields[r["id"]]["schema_type"], r["schema_type"])
            self.assertEqual(self.fields[r["id"]]["category"], r["category"])

    def test_every_gui_field_has_a_safe_backend_and_actual_schema_location(self):
        controller = (ROOT/registry.GUI_PATH).read_text().splitlines()
        for field in self.fields.values():
            source = field["gui_source"]
            self.assertEqual(source["path"], registry.GUI_PATH)
            lineno = source["line"]
            self.assertTrue(1 <= lineno <= len(controller))
            self.assertIn('id="' + field["id"] + '"', controller[lineno-1])
            self.assertFalse(controller[lineno-1].lstrip().startswith("--"))
            backend = field["backend"]
            self.assertEqual(backend["source_path"], registry.COMMON_BACKEND)
            self.assertEqual(backend["stored_key"],
                field["id"] if field["id"] in registry.BASE_ENV_KEYS
                else "8311_" + field["id"])
            self.assertEqual(backend["source_write_readback_contract"],
                             "8311.config.apply")

    def test_base_boot_environment_distinguished_from_prefixed_environment(self):
        self.assertEqual(self.fields["bootdelay"]["backend"]["kind"],
                         "uboot_environment")
        self.assertEqual(self.fields["uart_select"]["backend"]["stored_key"],
                         "uart_select")
        self.assertEqual(self.fields["gpon_sn"]["backend"]["stored_key"],
                         "8311_gpon_sn")
        self.assertEqual(self.fields["internet_vlan"]["backend"]["kind"],
                         "prefixed_8311_environment")

    def test_no_static_reference_implies_effective_or_recovery_verified(self):
        self.assertEqual(
            self.report["summary"]["complete_A_to_Z_hardware_test_receipts"],0)
        self.assertEqual(
            self.report["summary"]["native_firmware_support_for_other_boards"],0)
        for field in self.fields.values():
            self.assertEqual(field["evidence_level"],
                             registry.STATIC_STATUS)
            self.assertFalse(field["hardware_qualified"])
            self.assertFalse(field["enabled_on_additional_boards"])
            self.assertTrue(all(
                field["static_source_checks"][item] is False for item in
                ("runtime_effect_verified","durable_write_hardware_verified",
                 "effective_value_hardware_verified",
                 "reboot_persistence_hardware_verified",
                 "recovery_hardware_verified")))
        self.assertTrue(self.report["source_only"])
        self.assertFalse(self.report["live_device_queried"])
        self.assertFalse(self.report["firmware_modified"])

    def test_native_consumer_evidence_is_file_and_line_with_no_source_values(self):
        self.assertGreaterEqual(
            self.report["summary"]["gui_fields_with_native_reference"],40)
        self.assertLess(
            self.report["summary"]["gui_fields_with_native_reference"],54)
        for item in list(self.fields.values())+list(self.missing.values()):
            for ref in item["static_native_references"]:
                path=ROOT/ref["path"]
                self.assertTrue(path.is_file(),str(path))
                self.assertFalse(path.is_symlink())
                self.assertTrue(ref["path"].startswith("overlay/"))
                self.assertIn("line",ref)
                self.assertNotIn("source_text",ref)
                self.assertGreater(ref["line"],0)
                self.assertLessEqual(ref["line"],len(path.read_text().splitlines()))

    def test_trace_real_startup_consumer_paths(self):
        for key in ("mib_file","ipaddr","ethtool_speed"):
            item=self.fields[key]
            self.assertTrue(item["static_source_checks"]["startup_script_reference_found"])
            self.assertTrue(any(
                x["kind"]=="native_getter_reference"
                and x["path"].startswith("overlay/etc/init.d/")
                for x in item["static_native_references"]),key)
        self.assertTrue(
            any(x["path"].endswith("/_8311-poninit.sh") for x in
                self.missing["tx_en_mode"]["static_native_references"]))
        self.assertFalse(self.missing["tx_en_mode"]["hardware_qualified"])

    def test_unproven_paths_are_not_silently_marked_functional(self):
        for key in ("fw_match_b64","fw_match_num","override_commit",
                    "bootdelay","uart_select","failsafe_delay"):
            self.assertEqual(self.fields[key]["static_native_references"],[])
            self.assertFalse(self.fields[key]["static_source_checks"]["runtime_effect_verified"])
            self.assertFalse(self.fields[key]["static_source_checks"]["static_getter_found"])

    def test_missing_fields_are_distinguished_from_legacy_fallbacks(self):
        self.assertEqual(set(self.missing),{
            "device_sn","factory_mode","lct_vlan","tx_en_mode"})
        self.assertEqual(self.missing["lct_vlan"]["reason"],
                         "GUI_DISABLED_AS_BROKEN")
        self.assertEqual(self.missing["factory_mode"]["candidate_backend"],
                         "unconfirmed_vendor_option")
        self.assertEqual(self.missing["tx_en_mode"]["reason"],
                         "SOURCE_REFERENCED_NOT_IN_GUI")
        self.assertTrue(all(not v["exposed_gui_control"] and
                            not v["safe_to_enable_without_hardware_tests"]
                            for v in self.missing.values()))
        aliases = {x["id"]:x for x in
            self.report["upstream_aliases_must_not_count_as_extra_controls"]}
        self.assertEqual(set(aliases),{"reg_id","sw_ver"})
        self.assertEqual(aliases["reg_id"]["existing_schema_relation"]["field"],
                         "reg_id_hex")
        self.assertFalse(aliases["sw_ver"]["independent_control_proven"])

    def test_sensitivity_classification_is_value_free(self):
        for key in registry.SECRET_FIELDS:
            self.assertEqual(self.fields[key]["sensitivity"],"secret")
        for key in ("gpon_sn","lct_mac","iphost_mac","sfp_serial"):
            self.assertEqual(self.fields[key]["sensitivity"],
                             "potential_device_identity")
        data=json.dumps(self.report,sort_keys=True)
        self.assertNotIn("/var/tmp/",data)
        self.assertNotIn("/var/lib/",data)
        self.assertNotIn("BEGIN PRIVATE KEY",data)
        self.assertNotRegex(data,r"\b(?:[0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2}\b")
        self.assertFalse(self.report["contains_runtime_values_or_credentials"])

    def test_vendor_config_option_names_have_no_implicit_writable_claim(self):
        if os.environ.get("AOTT_VENDOR_ROOTFS"):
            self.assertEqual(self.report["summary"]["vendor_uci_config_files"],13)
            self.assertEqual(self.report["summary"]["vendor_uci_option_names"],89)
            domains={x["domain"] for x in self.report["offline_uci_domains"]}
            self.assertIn("optic",domains)
            self.assertEqual(len(domains),13)
            self.assertEqual(sum(x["option_name_count"]
                                 for x in self.report["offline_uci_domains"]),89)
            self.assertTrue(all(not x["device_functional_support_qualified"]
                                for x in self.report["offline_uci_domains"]))
        for option in self.report["offline_uci_option_candidates"]:
            self.assertFalse(option["editable"])
            self.assertFalse(option["hardware_qualified"])
            self.assertEqual(option["evidence_level"],
                             "DISCOVERED_READ_ONLY_SOURCE_NAME")
            self.assertEqual(set(option),{
                "id","config_domain","option_name","section_types",
                "source_kind","evidence_level","editable",
                "runtime_backend_proven","hardware_qualified",
            })

    def test_repeated_build_is_identical_no_timestamp_or_randomness(self):
        fresh=registry.build(
            ROOT,OFFLINE_VENDOR if os.environ.get("AOTT_VENDOR_ROOTFS") else None)
        self.assertEqual(json.dumps(fresh,sort_keys=True),
                         json.dumps(self.report,sort_keys=True))

    def test_json_snapshot_matches_clean_source(self):
        p=ROOT/"docs/CAPABILITY-REGISTRY-vNext-2026-11-02-r2.json"
        if p.is_file() and os.environ.get("AOTT_VENDOR_ROOTFS"):
            parsed=json.loads(p.read_text())
            self.assertEqual(parsed,self.report)
            self.assertEqual(parsed["summary"]["exposed_gui_environment_fields"],54)
        else:
            # Public source-only checkouts do not ship the proprietary
            # vendor rootfs or need the private r8 audit snapshot.
            self.assertEqual(len(self.fields),54)
            self.assertEqual(self.report["summary"]["complete_A_to_Z_hardware_test_receipts"],0)

    def test_comment_only_fake_source_reference_not_counted(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            artifact=root/"overlay/etc/init.d/ignore_shell_comments"
            artifact.parent.mkdir(parents=True)
            artifact.write_text(
                "#!/bin/sh\n# get_8311_fabricated_setting\n"
                "-- get_8311_fabricated_setting\n"
                "echo OK\n")
            names=[r for r in registry.safe_code_lines(root)]
            self.assertFalse(any("fabricated_setting" in line
                                 for _,_,line in names))

    def test_gui_schema_duplicate_fails_closed(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            p=root/registry.GUI_PATH
            p.parent.mkdir(parents=True)
            real=(ROOT/registry.GUI_PATH).read_text()
            self.assertIn('id="gpon_sn"',real)
            p.write_text(real.replace('id="gpon_sn"','id="hostname"',1))
            config=root/registry.COMMON_BACKEND
            config.parent.mkdir(parents=True)
            config.write_text((ROOT/registry.COMMON_BACKEND).read_text())
            with self.assertRaises(inventory.AuditError):
                inventory.parse_fwenv_form(p)

    def test_static_uci_and_source_scan_cannot_run_network_commands(self):
        source=(TOOLS/"build_capability_registry.py").read_text()
        self.assertNotIn("subprocess.run(",source)
        self.assertNotIn("urllib.request",source)
        self.assertNotIn("os.system(",source)
        self.assertNotIn("requests.get(",source)
        self.assertNotIn("paramiko",source)
        self.assertNotIn("ssh ",source)

    def test_cli_rejects_overwrite_of_evidence_json(self):
        p=ROOT/"docs/PROJECT-STATE-CHECKPOINT-2026-11-02.json"
        old=hashlib.sha256(p.read_bytes()).hexdigest()
        call=subprocess.run(
            [sys.executable,"-B",str(TOOLS/"build_capability_registry.py"),
             "--source-root",str(ROOT),"--output",str(p)],
             capture_output=True,text=True,timeout=20)
        self.assertNotEqual(call.returncode,0)
        self.assertIn("REFUSE_TO_OVERWRITE_PREVIOUS_REGISTRY",call.stderr)
        self.assertEqual(hashlib.sha256(p.read_bytes()).hexdigest(),old)

if __name__=="__main__":
    unittest.main()
