from pathlib import Path
import os, secrets, shutil, subprocess, unittest

ROOT=Path(__file__).resolve().parents[1]
OVERLAY=ROOT/"overlay"
VENDOR=Path(os.getenv("AOTT_VENDOR_ROOTFS","/missing/vendor-rootfs"))
FIXTURE=ROOT/"tests/v3_tls_activation_fixture.lua"

class V3TlsActivationTests(unittest.TestCase):
    def run_vendor(self,mode):
        if os.geteuid()!=0:
            self.skipTest("root-owned TLS fixture requires root")
        if not shutil.which("qemu-mips-static") or not (VENDOR/"usr/bin/lua").is_file():
            self.skipTest("vendor MIPS runtime unavailable")
        root=Path("/var/tmp/aott-tls-activation-test-"+secrets.token_hex(8))
        (root/"ptconf/8311/uhttpd").mkdir(parents=True,mode=0o700)
        (root/"tmp/aott-tls-candidate").mkdir(parents=True,mode=0o700)
        (root/"job").mkdir(mode=0o700)
        try:
            p=subprocess.run([
                "qemu-mips-static","-L",str(VENDOR),str(VENDOR/"usr/bin/lua"),
                str(FIXTURE),str(VENDOR),str(OVERLAY/"usr/lib/lua"),str(root),mode
            ],cwd=ROOT,capture_output=True,text=True,timeout=30)
            self.assertEqual(p.returncode,0,p.stderr)
            return p.stdout
        finally:
            shutil.rmtree(root,ignore_errors=True)

    def test_confirmed_activation(self):
        self.assertIn("AOTT_TLS_ACTIVATION_CONFIRM_PASS",self.run_vendor("confirm"))

    def test_timeout_restores_previous_pair(self):
        self.assertIn("AOTT_TLS_ACTIVATION_TIMEOUT_ROLLBACK_PASS",self.run_vendor("timeout"))

    def test_restart_failure_restores_previous_pair(self):
        self.assertIn("AOTT_TLS_ACTIVATION_RESTART_ROLLBACK_PASS",self.run_vendor("restart_fail"))

    def test_secondary_recovery_is_required_before_mutation(self):
        self.assertIn("AOTT_TLS_ACTIVATION_RECOVERY_GATE_PASS",self.run_vendor("no_recovery"))

    def test_crash_is_recovered_before_https_boot(self):
        self.assertIn("AOTT_TLS_ACTIVATION_BOOT_RECOVERY_PASS",self.run_vendor("crash"))

    def test_controller_routes_are_https_root_authenticated(self):
        c=(OVERLAY/"usr/lib/lua/luci/controller/8311.lua").read_text()
        for route in ("tls_activate","tls_confirm"):
            self.assertIn(f'entry({{"admin", "8311", "{route}"}}',c)
        self.assertIn('error="HTTPS is required for TLS activation"',c)
        self.assertIn('error="HTTPS is required to confirm TLS activation"',c)
        self.assertIn('dispatcher.context.authuser~="root"',c)
        self.assertIn('jobs.start("tls_activate"',c)
        self.assertIn('jobs.confirm_tls(values.job_id)',c)

    def test_job_confirmation_cannot_precede_persistent_pending_marker(self):
        s=(OVERLAY/"usr/lib/lua/8311/jobs.lua").read_text()
        self.assertIn('tls_activate=true',s)
        self.assertIn('require("8311.tls_activation").pending()',s)
        self.assertIn('pending.job_id ~= id',s)
        self.assertIn('"AOTT-TLS-CONFIRM-1\\n"',s)
        self.assertIn('"/usr/libexec/8311-tls-activate.lua"',s)

    def test_boot_recovery_precedes_uhttpd_startup(self):
        sysinit=(OVERLAY/"etc/init.d/_8311-sysinit.sh").read_text()
        self.assertIn("/usr/libexec/8311-tls-recover-pending",sysinit)
        self.assertIn("pending HTTPS certificate recovery failed",sysinit)
        self.assertNotIn("uhttpd restart",sysinit)
        module=(OVERLAY/"usr/lib/lua/8311/tls_activation.lua").read_text()
        self.assertIn('WAIT_TICKS=90',module)
        self.assertIn('M.WAIT_SECONDS=WAIT_TICKS*2',module)
        self.assertIn('"/usr/libexec/8311-root-credential-ready"',module)
        self.assertIn('{"/bin/pidof","dropbear"}',module)

    def test_ui_explains_real_browser_confirmation_and_rollback(self):
        view=(OVERLAY/"usr/lib/lua/luci/view/8311/tls.htm").read_text()
        self.assertIn("Activate candidate with rollback",view)
        self.assertIn("Confirm this HTTPS certificate",view)
        self.assertIn("180 seconds",view)
        self.assertIn("window.location.reload()",view)
        self.assertIn("Import operator-owned certificate",view)
        self.assertIn("Generated and imported candidates use the same guarded activation",view)

if __name__=="__main__":
    unittest.main()
