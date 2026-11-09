from pathlib import Path
import os, subprocess, unittest

ROOT=Path(__file__).resolve().parents[1]
MODULE=ROOT/"overlay/usr/lib/lua/8311/management_uci.lua"
FIXTURE=ROOT/"tests/v3_management_uci_fixture.lua"
VENDOR=Path(os.getenv("AOTT_VENDOR_ROOTFS","/missing-vendor-rootfs"))

class V3ManagementUciTests(unittest.TestCase):
    def run_fixture(self,cmd):
        p=subprocess.run(cmd,cwd=ROOT,capture_output=True,text=True,timeout=30)
        self.assertEqual(p.returncode,0,p.stderr)
        self.assertIn("AOTT_V3_MANAGEMENT_UCI_PASS",p.stdout)

    def test_host_fixture(self):
        self.run_fixture(["lua5.1",str(FIXTURE),str(ROOT/"overlay/usr/lib/lua")])

    def test_vendor_mips_fixture(self):
        if not os.getenv("AOTT_VENDOR_ROOTFS"):
            self.skipTest("Vendor rootfs not supplied")
        self.run_fixture(["qemu-mips-static","-L",str(VENDOR),str(VENDOR/"usr/bin/lua"),
                          str(FIXTURE),str(ROOT/"overlay/usr/lib/lua")])

    def test_no_shell_and_fixed_restore_scope(self):
        s=MODULE.read_text()
        self.assertNotIn("os.execute",s)
        self.assertNotIn("io.popen",s)
        self.assertNotIn("/bin/sh",s)
        self.assertIn('local PACKAGES={network=true,firewall=true}',s)
        self.assertIn('/ptconf/8311/aott-recovery/v1/management/',s)
        self.assertIn('production_runtime=true',s)

    def test_native_export_is_reparsed_before_use(self):
        s=MODULE.read_text()
        self.assertIn('web.capture({"/sbin/uci","export",package}',s)
        self.assertIn('transition.parse_export(out,package)',s)
        self.assertIn('transition.verify_staged(handle,adapter,"production_runtime")',s)

if __name__=="__main__":
    unittest.main()
