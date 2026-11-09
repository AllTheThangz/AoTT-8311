from pathlib import Path
import os, subprocess, unittest

ROOT=Path(__file__).resolve().parents[1]
FIXTURE=ROOT/"tests/v3_runtime_helpers_fixture.lua"
ADVANCED=ROOT/"overlay/usr/lib/lua/8311/advanced_runtime.lua"
SFP=ROOT/"overlay/usr/lib/lua/8311/sfp_runtime.lua"
VENDOR=Path(os.getenv("AOTT_VENDOR_ROOTFS","/missing-vendor-rootfs"))

class V3RuntimeHelperTests(unittest.TestCase):
    def run_fixture(self,command):
        p=subprocess.run(command,cwd=ROOT,capture_output=True,text=True,timeout=30)
        self.assertEqual(p.returncode,0,p.stderr)
        self.assertIn("AOTT_V3_RUNTIME_HELPERS_PASS",p.stdout)

    def test_host_fixture(self):
        self.run_fixture(["lua5.1",str(FIXTURE),str(ROOT/"overlay/usr/lib/lua")])

    def test_vendor_mips_fixture(self):
        if not os.getenv("AOTT_VENDOR_ROOTFS"):
            self.skipTest("No offline vendor rootfs configured")
        self.run_fixture([
            "qemu-mips-static","-L",str(VENDOR),str(VENDOR/"usr/bin/lua"),
            str(FIXTURE),str(ROOT/"overlay/usr/lib/lua")
        ])

    def test_modules_compile(self):
        for path in (ADVANCED,SFP):
            p=subprocess.run(["luac5.1","-p",str(path)],capture_output=True,text=True,timeout=10)
            self.assertEqual(p.returncode,0,p.stderr)

    def test_fixed_paths_and_no_dynamic_shell(self):
        a=ADVANCED.read_text()
        s=SFP.read_text()
        self.assertIn('"/usr/sbin/ethtool","-s","eth0_0"',a)
        self.assertIn('"/sys/class/gpio/gpio510"',a)
        self.assertIn('"/sys/class/gpio/gpio508"',a)
        self.assertIn('"/dev/sfp_eeprom0"',s)
        for source in (a,s):
            self.assertNotIn("os.execute",source)
            self.assertNotIn("io.popen",source)
            self.assertNotIn("shellquote",source)

    def test_sfp_scope_is_exact_seven_fields(self):
        s=SFP.read_text()
        expected=("sfp_vendor","sfp_oui","sfp_partno","sfp_rev",
                  "sfp_serial","sfp_date","sfp_vendordata")
        for field in expected:
            self.assertIn(field+"={",s)
        self.assertNotIn("gpon_sn={",s)
        self.assertNotIn("reg_id_hex={",s)

if __name__=="__main__":
    unittest.main()
