from pathlib import Path
import os, subprocess, unittest

ROOT=Path(__file__).resolve().parents[1]
MODULE=ROOT/"overlay/usr/lib/lua/8311/management_runtime.lua"
FIXTURE=ROOT/"tests/v3_management_runtime_fixture.lua"
VENDOR=Path(os.getenv("AOTT_VENDOR_ROOTFS","/missing-vendor-rootfs"))

class V3ManagementRuntimeTests(unittest.TestCase):
    def run_fixture(self,cmd):
        p=subprocess.run(cmd,cwd=ROOT,capture_output=True,text=True,timeout=30)
        self.assertEqual(p.returncode,0,p.stderr)
        self.assertIn("AOTT_V3_MANAGEMENT_RUNTIME_PASS",p.stdout)

    def test_host_fixture(self):
        self.run_fixture(["lua5.1",str(FIXTURE),str(ROOT/"overlay/usr/lib/lua")])

    def test_vendor_mips_fixture(self):
        if not os.getenv("AOTT_VENDOR_ROOTFS"):
            self.skipTest("Vendor rootfs not supplied")
        self.run_fixture([
            "qemu-mips-static","-L",str(VENDOR),str(VENDOR/"usr/bin/lua"),
            str(FIXTURE),str(ROOT/"overlay/usr/lib/lua")
        ])

    def test_module_compiles(self):
        p=subprocess.run(["luac5.1","-p",str(MODULE)],
                         capture_output=True,text=True,timeout=10)
        self.assertEqual(p.returncode,0,p.stderr)

    def test_fixed_runtime_sources_and_redacted_receipt(self):
        s=MODULE.read_text()
        self.assertIn('"/bin/ubus","call","network.interface."..section,"status"',s)
        self.assertIn('"/sys/class/net/"..device.."/address"',s)
        self.assertIn('contains_configuration_values=false',s)
        self.assertIn('dns_verified=true',s)
        self.assertIn('vlan_mode_verified=true',s)
        self.assertIn('vlan_id_verified=true',s)
        self.assertIn('"/sbin/ip","-d","link","show","dev","mgmt"',s)
        self.assertNotIn("os.execute",s)
        self.assertNotIn("io.popen",s)
        self.assertNotIn('"/bin/sh"',s)

    def test_request_scope_is_exact_management_tuple(self):
        s=MODULE.read_text()
        self.assertIn(
            "local allowed={vlan=true,ipaddr=true,netmask=true,gateway=true,dns_server=true,lct_mac=true}",
            s)
        for forbidden in ("gpon_sn","reg_id_hex","root_pwhash","internet_vlan"):
            self.assertNotIn(forbidden,s)

if __name__=="__main__":
    unittest.main()
