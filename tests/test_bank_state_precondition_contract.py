"""Read-only static contracts for bound firmware-bank operation requests.

No test calls a device, a firmware updater, or any boot-changing command.
"""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


class BankStatePreconditionContracts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bank = (ROOT / "overlay/usr/sbin/8311-bankctl.sh").read_text()
        cls.library = (ROOT / "overlay/lib/8311-upgrade-lib.sh").read_text()
        cls.controller = (ROOT / "overlay/usr/lib/lua/luci/controller/8311.lua").read_text()
        cls.jobs = (ROOT / "overlay/usr/lib/lua/8311/jobs.lua").read_text()
        cls.browser = (ROOT / "overlay/www/luci-static/resources/view/8311.js").read_text()

    def test_native_state_boot_identity_and_short_window_are_hashed(self):
        self.assertIn('print_bank_status > "$WORKDIR/state-snapshot"', self.library)
        self.assertIn('cat /proc/sys/kernel/random/boot_id', self.library)
        self.assertIn('epoch=$(date +%s)', self.library)
        self.assertIn('bucket=$((epoch / 300))', self.library)
        self.assertIn('aott-8311-bank-state-guard-v2', self.library)
        self.assertIn('boot-id=%s', self.library)
        self.assertIn('five-minute-window=%s', self.library)
        self.assertIn('sha_file "$WORKDIR/state-precondition"', self.library)
        self.assertIn('state_guard', self.bank)
        self.assertIn('NR == 1', self.bank)
        self.assertEqual(self.library.count("bank_state_fingerprint() {"), 1)
        self.assertNotIn("bank_state_fingerprint() {", self.bank)

    def test_both_locks_precede_guard_and_command_dispatch(self):
        code = self.bank
        firmware = code.index("\nlock_upgrade\n")
        environment = code.index("lock_environment || fail")
        boot = code.index("load_environment && check_boot_contract")
        check = code.index('if [ -n "$EXPECT_STATE_GUARD" ]; then')
        dispatch = code.index('case "$COMMAND" in', boot)
        self.assertLess(firmware, environment)
        self.assertLess(environment, boot)
        self.assertLess(boot, check)
        self.assertLess(check, dispatch)
        self.assertIn('Bank state changed since approval. No operation was performed.', code)

    def test_guard_only_accepts_bounded_lowercase_hex_and_known_actions(self):
        self.assertIn('EXPECT_STATE_GUARD}" -eq 64', self.bank)
        self.assertIn('case "$EXPECT_STATE_GUARD" in *[!0-9a-f]*) exit 2', self.bank)
        self.assertIn('trial|check-json|commit|cancel-trial|rollback|reboot', self.bank)
        self.assertNotIn('eval "$EXPECT_STATE_GUARD"', self.bank)

    def test_controller_rejects_missing_guard_and_disables_caching(self):
        code = self.controller
        self.assertIn('state_guard=true', code)
        self.assertIn('type(values.state_guard) ~= "string"', code)
        self.assertIn('values.state_guard:find("[^0-9a-f]")', code)
        self.assertIn('args.state_guard=values.state_guard', code)
        self.assertIn('http.header("Cache-Control","no-store, private")', code)
        self.assertIn('type(state.state_guard) == "string"', code)

    def test_queued_worker_receives_exact_guarded_action(self):
        code = self.jobs
        self.assertIn('state_guard=args.state_guard', code)
        self.assertIn('request.args.state_guard', code)
        self.assertIn('guard:find("[^0-9a-f]")', code)
        self.assertIn('"/usr/sbin/8311-bankctl.sh", "guarded"', code)
        self.assertIn('bank_actions[request.args.action], guard', code)
        self.assertNotIn('argv = {"/usr/sbin/8311-bankctl.sh", bank_actions[request.args.action]}', code)

    def test_browser_requires_fresh_guard_but_cannot_authorize_server(self):
        code = self.browser
        self.assertIn("state.state_guard, parts", code)
        self.assertIn("state_guard: current.state_guard", code)
        self.assertIn("request8311('bank_status')", code)
        self.assertIn("if (currentSignature !== observed)", code)
        self.assertIn('/^[0-9a-f]{64}$/.test(state.state_guard)', code)

    def test_guarded_runtime_has_manifest_pins(self):
        import json
        import hashlib
        manifest = json.loads((ROOT / "MANIFEST.json").read_text())
        records = {record["path"]: record for record in manifest["overlay_files"]}
        for name in ("lib/8311-upgrade-lib.sh", "usr/sbin/8311-bankctl.sh",
                     "usr/sbin/8311-firmware-upgrade.sh",
                     "usr/lib/lua/8311/jobs.lua"):
            record = records[name]
            artifact = ROOT / "overlay" / name
            self.assertEqual(record["bytes"], artifact.stat().st_size)
            self.assertEqual(record["sha256"],
                             hashlib.sha256(artifact.read_bytes()).hexdigest())

    def test_firmware_assets_use_current_revision_cache_buster(self):
        template = (ROOT / "overlay/usr/lib/lua/luci/view/8311/firmware.htm").read_text()
        self.assertIn('8311.js?v=aott-8311-v3-r2', template)
        self.assertIn('8311.css?v=aott-8311-v3-r2', template)
        self.assertNotIn('8311.js?v=aott-8311-v1-r3', template)

    def test_original_local_cli_remains_available(self):
        self.assertIn('\tstatus)', self.bank)
        self.assertIn('status|check|commit|reboot|rollback|cancel-trial)', self.bank)


if __name__ == "__main__":
    unittest.main()
