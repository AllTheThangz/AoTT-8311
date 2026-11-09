from pathlib import Path
import os, subprocess, unittest

ROOT=Path(__file__).resolve().parents[1]
MODULE=ROOT/"overlay/usr/lib/lua/8311/management_transaction.lua"
FIXTURE=ROOT/"tests/v3_management_transaction_fixture.lua"
ENV=ROOT/"overlay/usr/lib/lua/8311/management_environment.lua"
VENDOR=Path(os.getenv("AOTT_VENDOR_ROOTFS","/missing-vendor-rootfs"))

class V3ManagementTransactionTests(unittest.TestCase):
    def run_fixture(self,cmd):
        p=subprocess.run(cmd,cwd=ROOT,capture_output=True,text=True,timeout=30)
        self.assertEqual(p.returncode,0,p.stderr)
        self.assertIn("AOTT_V3_MANAGEMENT_TRANSACTION_PASS",p.stdout)

    def test_host_fixture(self):
        self.run_fixture(["lua5.1",str(FIXTURE),str(ROOT/"overlay/usr/lib/lua")])

    def test_vendor_mips_fixture(self):
        if not os.getenv("AOTT_VENDOR_ROOTFS"):
            self.skipTest("Vendor rootfs not supplied")
        self.run_fixture([
            "qemu-mips-static","-L",str(VENDOR),str(VENDOR/"usr/bin/lua"),
            str(FIXTURE),str(ROOT/"overlay/usr/lib/lua")
        ])

    def test_modules_compile(self):
        for path in (MODULE,ENV):
            with self.subTest(path=path.name):
                p=subprocess.run(["luac5.1","-p",str(path)],
                                 capture_output=True,text=True,timeout=10)
                self.assertEqual(p.returncode,0,p.stderr)

    def test_persistent_recovery_precedes_mutation(self):
        s=MODULE.read_text()
        arm=s.index("provider.arm")
        env=s.index("provider.apply_environment",arm)
        uci=s.index("provider.apply_uci",env)
        reload=s.index("provider.reload",uci)
        verify=s.index("provider.verify",reload)
        self.assertLess(arm,env)
        self.assertLess(env,uci)
        self.assertLess(uci,reload)
        self.assertLess(reload,verify)

    def test_timeout_and_failure_paths_restore(self):
        s=MODULE.read_text()
        self.assertIn("management_confirmation_timeout",s)
        self.assertIn("management_runtime_convergence_failed",s)
        self.assertIn("management_rollback_failed",s)
        self.assertIn("provider.restore",s)
        self.assertIn("rollback_verified=true",s)

    def test_production_sources_are_fixed_and_private(self):
        s=MODULE.read_text()
        self.assertIn('"/etc/init.d/network","reload"',s)
        self.assertIn('"/etc/init.d/firewall","reload"',s)
        self.assertIn('"/ptconf/8311/aott-recovery/v1"',s)
        self.assertIn('contains_configuration_values=false',s)
        self.assertNotIn("os.execute",s)
        self.assertNotIn("io.popen",s)
        self.assertNotIn('"/bin/sh"',s)

    def test_boot_recovery_entrypoint_and_complete_restore_tuple(self):
        s=MODULE.read_text()
        self.assertIn("function M.recover_pending()",s)
        self.assertIn("environment.request_from_snapshot",s)
        env=ENV.read_text()
        self.assertIn("function M.request_from_snapshot(raw)",env)
        for field in ("vlan","ipaddr","netmask","gateway","dns_server","lct_mac"):
            self.assertIn(field,env)

if __name__=="__main__":
    unittest.main()
