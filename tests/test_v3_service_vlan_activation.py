from pathlib import Path
import os, subprocess, unittest

ROOT=Path(__file__).resolve().parents[1]
MODULE=ROOT/"overlay/usr/lib/lua/8311/vlan_runtime.lua"
FIXTURE=ROOT/"tests/v3_vlan_runtime_fixture.lua"
FIXER=ROOT/"overlay/usr/sbin/8311-fix-vlans.sh"
DAEMON=ROOT/"overlay/usr/sbin/8311-vlansd.sh"
VENDOR=Path(os.getenv("AOTT_VENDOR_ROOTFS","/missing-vendor-rootfs"))

class V3ServiceVlanActivationTests(unittest.TestCase):
    def run_fixture(self,command):
        p=subprocess.run(command,cwd=ROOT,capture_output=True,text=True,timeout=30)
        self.assertEqual(p.returncode,0,p.stderr)
        self.assertIn("AOTT_V3_VLAN_RUNTIME_PASS",p.stdout)

    def test_host_fixture(self):
        self.run_fixture(["lua5.1",str(FIXTURE),str(ROOT/"overlay/usr/lib/lua")])

    def test_vendor_mips_fixture(self):
        if not os.getenv("AOTT_VENDOR_ROOTFS"):
            self.skipTest("No vendor rootfs")
        self.run_fixture([
            "qemu-mips-static","-L",str(VENDOR),str(VENDOR/"usr/bin/lua"),
            str(FIXTURE),str(ROOT/"overlay/usr/lib/lua")
        ])

    def test_module_compiles(self):
        p=subprocess.run(["luac5.1","-p",str(MODULE)],capture_output=True,text=True)
        self.assertEqual(p.returncode,0,p.stderr)

    def test_disable_and_hook_only_clear_only_owned_selectors(self):
        fixer=FIXER.read_text()
        daemon=DAEMON.read_text()
        self.assertIn('if [ "$1" = "--clear-owned" ]',fixer)
        self.assertIn("tc_flower_del $rule",fixer)
        self.assertIn("if tc_flower_matches $rule",fixer)
        self.assertIn("rm -f \"$CONFIG_FILE\"",fixer)
        self.assertNotIn("tc_flower_clear",fixer)
        self.assertIn("/usr/sbin/8311-fix-vlans.sh --clear-owned",daemon)
        self.assertIn('0)',daemon)
        self.assertIn('2)',daemon)

    def test_runtime_distinguishes_builtin_disabled_and_hook_only(self):
        s=MODULE.read_text()
        self.assertIn("builtin_vlan_reconciliation_receipt",s)
        self.assertIn("builtin_vlan_translation_disabled",s)
        self.assertIn("hook_only_runtime_effect_requires_hook_specific_proof",s)
        self.assertIn("vlan_builtin_reconciliation_unverified",s)
        self.assertNotIn("os.execute",s)
        self.assertNotIn("io.popen",s)

if __name__=="__main__":
    unittest.main()
