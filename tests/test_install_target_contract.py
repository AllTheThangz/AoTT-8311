"""Source-only checks for confirmed inactive-bank upload destinations.

These tests inspect the reviewed installer, controller and worker. They do
not execute any firmware installer, boot-selection command or device I/O.
"""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


class InstallTargetContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.installer = (ROOT / "overlay/usr/sbin/8311-firmware-upgrade.sh").read_text()
        cls.controller = (ROOT / "overlay/usr/lib/lua/luci/controller/8311.lua").read_text()
        cls.jobs = (ROOT / "overlay/usr/lib/lua/8311/jobs.lua").read_text()
        cls.browser = (ROOT / "overlay/www/luci-static/resources/view/8311.js").read_text()

    def test_explicit_target_pair_must_be_opposite_banks(self):
        script = self.installer
        self.assertIn("--expect-active)", script)
        self.assertIn("--expect-target)", script)
        self.assertIn('case "$EXPECT_ACTIVE:$EXPECT_TARGET" in A:B|B:A)', script)
        self.assertIn('EXPECT_ACTIVE=$2; shift', script)
        self.assertIn('EXPECT_TARGET=$2; shift', script)

    def test_target_checks_run_after_firmware_locks_before_first_write(self):
        code = self.installer
        first_lock = code.index("\nlock_upgrade\n")
        second_lock = code.index("lock_environment || fail")
        load = code.index("load_environment && check_boot_contract")
        select = code.index("if [ \"$ACTIVE\" = A ]; then INSTALL_BANK=B;")
        guarded = code.index('[ -z "$EXPECT_ACTIVE" ] || [ "$ACTIVE" = "$EXPECT_ACTIVE" ]')
        target = code.index('[ -z "$EXPECT_TARGET" ] || [ "$INSTALL_BANK" = "$EXPECT_TARGET" ]')
        mutation = code.index('persist_receipt "$INSTALL_BANK" incomplete')
        self.assertLess(first_lock, second_lock)
        self.assertLess(second_lock, load)
        self.assertLess(load, select)
        self.assertLess(select, guarded)
        self.assertLess(guarded, target)
        self.assertLess(target, mutation)
        self.assertIn("No image was written", code)

    def test_validate_only_does_not_accept_install_expectations(self):
        code = self.installer
        self.assertIn(
            'Inactive-bank expectations are only supported for installation.', code)
        self.assertIn('[ -n "$EXPECT_ACTIVE$EXPECT_TARGET" ]', code)
        self.assertIn('case "$EXPECT_ACTIVE:$EXPECT_TARGET" in A:B|B:A)', code)

    def test_controller_requires_and_binds_expected_target(self):
        code = self.controller
        self.assertIn("expected_active=true,expected_target=true", code)
        self.assertIn('values.expected_active == "A"', code)
        self.assertIn('values.expected_target == "B"', code)
        self.assertIn("args.expected_active=values.expected_active", code)
        self.assertIn("args.expected_target=values.expected_target", code)
        self.assertIn('if values.bank then', code)
        self.assertIn('type(values.state_guard) ~= "string"', code)
        self.assertIn('args.state_guard=values.state_guard', code)

    def test_job_worker_persists_exact_target_and_rechecks_request(self):
        code = self.jobs
        self.assertIn('kind == "firmware_install"', code)
        self.assertIn("request_args.expected_active=args.expected_active", code)
        self.assertIn("request_args.expected_target=args.expected_target", code)
        self.assertIn('request.args.expected_active, request.args.expected_target', code)
        self.assertIn('Stored firmware overwrite destination is invalid', code)
        self.assertIn('"--expect-active", active, "--expect-target", target', code)
        self.assertIn('request_args.state_guard=args.state_guard', code)
        self.assertIn('request.args.state_guard', code)
        self.assertIn('"--expect-state-guard", guard', code)

    def test_browser_upload_review_includes_target_confirmation(self):
        code = self.browser
        self.assertIn("expected_active: fresh.active, expected_target: consequence.target", code)
        self.assertIn("state_guard: fresh.state_guard", code)
        self.assertIn("submitCheckedFirmwareInstall", code)
        self.assertIn("consequence.target !== preview.target", code)
        self.assertIn("Make and independently verify fresh, off-device full-bank backups", code)

    def test_native_installer_preserves_explicit_optional_reboot(self):
        code = self.installer
        self.assertIn('if $REBOOT; then', code)
        self.assertIn('if [ "$ACTIVE" = A ]; then INSTALL_BANK=B;', code)
        self.assertIn('check_bank "$ACTIVE"', code)
        self.assertIn('load_environment && check_boot_contract', code)
        self.assertIn('[ "$ACTIVE" = "$OLD_ACTIVE" ]', code)


if __name__ == "__main__":
    unittest.main()
