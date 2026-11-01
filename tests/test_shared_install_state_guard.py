"""Source-only verification of shared, lock-bound firmware-install preconditions.

No installer, bank-control script, device command, or firmware operation is run.
"""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


class SharedInstallFingerprintTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.library = (ROOT / "overlay/lib/8311-upgrade-lib.sh").read_text()
        cls.bank = (ROOT / "overlay/usr/sbin/8311-bankctl.sh").read_text()
        cls.installer = (ROOT / "overlay/usr/sbin/8311-firmware-upgrade.sh").read_text()
        cls.jobs = (ROOT / "overlay/usr/lib/lua/8311/jobs.lua").read_text()
        cls.controller = (ROOT / "overlay/usr/lib/lua/luci/controller/8311.lua").read_text()
        cls.client = (ROOT / "overlay/www/luci-static/resources/view/8311.js").read_text()

    def test_one_shared_fingerprint_implementation_not_two_drifting_copies(self):
        self.assertEqual(self.library.count("bank_state_fingerprint() {"), 1)
        self.assertNotIn("bank_state_fingerprint() {", self.bank)
        self.assertNotIn("bank_state_fingerprint() {", self.installer)
        self.assertIn('sha_file "$WORKDIR/state-precondition"', self.library)
        for phrase in ('cat /proc/sys/kernel/random/boot_id',
                       'bucket=$((epoch / 300))',
                       'print_bank_status > "$WORKDIR/state-snapshot"',
                       'aott-8311-bank-state-guard-v2'):
            self.assertIn(phrase, self.library)
        self.assertIn('ACTUAL_STATE_GUARD=$(bank_state_fingerprint)', self.bank)
        self.assertEqual(self.installer.count('ACTUAL_STATE_GUARD=$(bank_state_fingerprint)'), 2)

    def test_browser_install_binds_backend_fingerprint(self):
        self.assertIn("state_guard: fresh.state_guard", self.client)
        self.assertIn("expected_active: fresh.active", self.client)
        self.assertIn("expected_target: consequence.target", self.client)
        self.assertIn("fingerprint !== observed", self.client)
        self.assertIn("currentSelection.dataset.sha256 !== selectedSha256", self.client)

    def test_controller_requires_valid_fingerprint_only_for_installation(self):
        code = self.controller
        self.assertIn('if action == "install" then', code)
        self.assertIn('type(values.state_guard) ~= "string"', code)
        self.assertIn('#values.state_guard ~= 64', code)
        self.assertIn('values.state_guard:find("[^0-9a-f]")', code)
        self.assertIn('args.state_guard=values.state_guard', code)
        self.assertIn('elseif values.state_guard or values.expected_active or values.expected_target then', code)
        self.assertIn('dispatcher.test_post_security()', code)

    def test_queued_worker_checks_and_carries_same_fingerprint(self):
        code = self.jobs
        self.assertIn('Fresh live bank fingerprint required for installation', code)
        self.assertIn('request_args.state_guard=args.state_guard', code)
        self.assertIn('local guard = request.args.state_guard', code)
        self.assertIn('Stored firmware bank-state fingerprint is invalid', code)
        self.assertIn('"--expect-state-guard", guard,', code)
        self.assertIn('"--expect-active", active, "--expect-target", target', code)

    def test_installer_validates_bounded_guard_and_target_pair(self):
        code = self.installer
        self.assertIn('--expect-state-guard)', code)
        self.assertIn('EXPECT_STATE_GUARD=$2; shift', code)
        self.assertIn('[ "${#EXPECT_STATE_GUARD}" -eq 64 ]', code)
        self.assertIn('case "$EXPECT_STATE_GUARD" in *[!0-9a-f]*)', code)
        self.assertIn('case "$EXPECT_ACTIVE:$EXPECT_TARGET" in A:B|B:A)', code)
        self.assertIn('A bank-state fingerprint requires both exact A/B installation selectors.', code)
        self.assertIn('Inactive-bank expectations are only supported for installation.', code)

    def test_two_lock_bound_checks_precede_first_mutation(self):
        text = self.installer
        firmware_lock = text.index('\nlock_upgrade\n')
        environment_lock = text.index('lock_environment || fail')
        initial_load = text.index('load_environment && check_boot_contract')
        first_check = text.index('ACTUAL_STATE_GUARD=$(bank_state_fingerprint)')
        running_check = text.index('[ "$ACTIVE" = "$COMMITTED" ]')
        candidate_bank = text.index('if [ "$ACTIVE" = A ]; then INSTALL_BANK=B;')
        expected_active = text.index('[ -z "$EXPECT_ACTIVE" ] || [ "$ACTIVE" = "$EXPECT_ACTIVE" ]')
        reloaded = text.index('OLD_ACTIVE=$ACTIVE')
        second_check = text.index('ACTUAL_STATE_GUARD=$(bank_state_fingerprint)', first_check + 1)
        first_write = text.index('persist_receipt "$INSTALL_BANK" incomplete')
        for earlier, later in zip(
            (firmware_lock, environment_lock, initial_load, first_check,
             running_check, candidate_bank, expected_active, reloaded, second_check),
            (environment_lock, initial_load, first_check, running_check,
             candidate_bank, expected_active, reloaded, second_check, first_write),
        ):
            self.assertLess(earlier, later)
        self.assertIn('Bank state changed or confirmation expired before the first write.', text)

    def test_direct_console_install_preserves_existing_stage_flags(self):
        text = self.installer
        self.assertIn('if [ -n "$EXPECT_ACTIVE$EXPECT_TARGET" ]; then', text)
        self.assertIn('elif [ -n "$EXPECT_STATE_GUARD" ]; then', text)
        self.assertIn('if $TRIAL; then', text)
        self.assertIn('if $REBOOT; then', text)
        self.assertIn('check_bank "$ACTIVE"', text)
        self.assertIn('qualify_rootfs "$INSTALL_BANK" candidate', text)
        self.assertIn('actual=$(checked_stream_sha "$size" "$device")', text)


if __name__ == "__main__":
    unittest.main()
