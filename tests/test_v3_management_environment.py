from pathlib import Path
import os, subprocess, unittest

ROOT=Path(__file__).resolve().parents[1]
MODULE=ROOT/"overlay/usr/lib/lua/8311/management_environment.lua"
FIXTURE=ROOT/"tests/v3_management_environment_fixture.lua"
VENDOR=Path(os.getenv("AOTT_VENDOR_ROOTFS","/missing-vendor-rootfs"))

class V3ManagementEnvironmentTests(unittest.TestCase):
    def run_fixture(self,cmd):
        p=subprocess.run(cmd,cwd=ROOT,capture_output=True,text=True,timeout=30)
        self.assertEqual(p.returncode,0,p.stderr)
        self.assertIn("AOTT_V3_MANAGEMENT_ENVIRONMENT_PASS",p.stdout)

    def test_host_fixture(self):
        self.run_fixture(["lua5.1",str(FIXTURE),str(ROOT/"overlay/usr/lib/lua")])

    def test_vendor_mips_fixture(self):
        if not os.getenv("AOTT_VENDOR_ROOTFS"):
            self.skipTest("Vendor rootfs not supplied")
        self.run_fixture(["qemu-mips-static","-L",str(VENDOR),str(VENDOR/"usr/bin/lua"),
                          str(FIXTURE),str(ROOT/"overlay/usr/lib/lua")])

    def test_scope_is_exact_six_management_keys(self):
        s=MODULE.read_text()
        self.assertIn('local KEYS={"ipaddr","netmask","gateway","dns_server","lct_mac","lct_vlan"}',s)
        self.assertIn("present-empty",s.lower())
        self.assertNotIn("fw_printenv",s)
        self.assertNotIn("os.execute",s)
        self.assertNotIn("io.popen",s)

    def test_apply_and_restore_verify_authoritative_snapshot(self):
        s=MODULE.read_text()
        self.assertIn("tools.fw_setenv_8311",s)
        self.assertIn("management_environment_apply_readback_failed",s)
        self.assertIn("management_environment_restore_readback_failed",s)
        self.assertIn("M.restore(before)",s)

if __name__=="__main__":
    unittest.main()
