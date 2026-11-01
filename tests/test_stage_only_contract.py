"""Fail-closed, text-only regression tests for inactive-bank installer semantics."""
from pathlib import Path
import importlib.util
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
AUDIT = ROOT / "tools/audit_stage_only_contract.py"
INSTALLER = ROOT / "overlay/usr/sbin/8311-firmware-upgrade.sh"

spec = importlib.util.spec_from_file_location("aott_staging_audit", AUDIT)
audit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)


class InactiveBankInstallContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = INSTALLER.read_text(encoding="utf-8")

    def assert_rejected(self, text, expected_check):
        report = audit.inspect(text)
        self.assertEqual(report["status"], "SOURCE_STAGE_ONLY_CONTRACT_REJECTED")
        self.assertFalse(report["checks"][expected_check], expected_check)

    def test_reviewed_source_passes_without_execution(self):
        report = audit.inspect(self.source)
        self.assertEqual(report["status"], "SOURCE_STAGE_ONLY_CONTRACT_PASS")
        self.assertTrue(report["device_operations_performed"] is False)
        self.assertTrue(report["runtime_execution_performed"] is False)
        self.assertTrue(all(report["checks"].values()))

    def test_inactive_bank_selection_cannot_be_removed(self):
        needle = 'if [ "$ACTIVE" = A ]; then INSTALL_BANK=B; else INSTALL_BANK=A; fi'
        self.assert_rejected(self.source.replace(needle, "", 1),
                             "inactive_bank_selected")

    def test_active_bank_validation_cannot_be_removed(self):
        self.assert_rejected(self.source.replace('check_bank "$ACTIVE"', "", 1),
                             "live_bank_checked")

    def test_incomplete_receipt_cannot_be_removed(self):
        self.assert_rejected(
            self.source.replace('persist_receipt "$INSTALL_BANK" incomplete', "", 1),
            "incomplete_receipt_first")

    def test_flash_hash_readback_cannot_be_removed(self):
        self.assert_rejected(
            self.source.replace('actual=$(checked_stream_sha "$size" "$device")',
                                "", 1),
            "hash_flash_readback")

    def test_rootfs_runtime_qualification_cannot_be_removed(self):
        self.assert_rejected(
            self.source.replace('qualify_rootfs "$INSTALL_BANK" candidate', "", 1),
            "verify_mounted_candidate")

    def test_candidate_validity_cannot_precede_runtime_verification(self):
        pattern = 'qualify_rootfs "$INSTALL_BANK" candidate'
        edited = self.source.replace(
            'set_environment "img_valid$INSTALL_BANK" true',
            'set_environment "img_valid$INSTALL_BANK" false', 1)
        edited = edited.replace(pattern,
                                'set_environment "img_valid$INSTALL_BANK" true', 1)
        self.assert_rejected(edited, "ordered_transitions")

    def test_reboot_must_remain_explicit(self):
        self.assert_rejected(self.source.replace("if $REBOOT; then",
                                                "if true; then", 1),
                             "reboot_opt_in")

    def test_trial_selection_must_remain_explicit(self):
        self.assert_rejected(self.source.replace("if $TRIAL; then",
                                                "if true; then", 1),
                             "trial_selection_opt_in")

    def test_commit_selector_not_part_of_stage_install(self):
        self.assert_rejected(self.source +
                             '\nset_environment commit_bank "$INSTALL_BANK"\n',
                             "no_commit_bank_write")

    def test_additional_ubi_writer_rejected(self):
        edited = self.source + '\nubiupdatevol -s "$size" "$device" -\n'
        self.assert_rejected(edited, "one_ubiupdatevol")

    def test_source_only_script_rejects_nonregular_input(self):
        with tempfile.TemporaryDirectory() as temp:
            alias = Path(temp) / "alias"
            alias.symlink_to(INSTALLER)
            result = subprocess.run(
                [sys.executable, str(AUDIT), str(alias)],
                capture_output=True, text=True, timeout=10)
            self.assertNotEqual(result.returncode, 0)

    def test_staging_does_not_require_running_mips_code(self):
        self.assertEqual(audit.inspect(self.source)["status"],
                         "SOURCE_STAGE_ONLY_CONTRACT_PASS")


if __name__ == "__main__":
    unittest.main()
