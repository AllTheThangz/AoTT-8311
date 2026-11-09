from pathlib import Path
import os, subprocess, unittest

ROOT=Path(__file__).resolve().parents[1]
FIXTURE=ROOT/"tests/v3_management_tuple_planner_fixture.lua"
MODULE=ROOT/"overlay/usr/lib/lua/8311/vlan_transition.lua"
VENDOR=Path(os.getenv("AOTT_VENDOR_ROOTFS","/missing-vendor-rootfs"))

class V3ManagementTuplePlannerTests(unittest.TestCase):
    def run_fixture(self,cmd):
        p=subprocess.run(cmd,cwd=ROOT,capture_output=True,text=True,timeout=30)
        self.assertEqual(p.returncode,0,p.stderr)
        self.assertIn("AOTT_V3_MANAGEMENT_TUPLE_PLANNER_PASS",p.stdout)

    def test_host_fixture(self):
        self.run_fixture(["lua5.1",str(FIXTURE),str(ROOT/"overlay/usr/lib/lua")])

    def test_vendor_mips_fixture(self):
        if not os.getenv("AOTT_VENDOR_ROOTFS"):
            self.skipTest("Vendor rootfs not supplied")
        self.run_fixture(["qemu-mips-static","-L",str(VENDOR),str(VENDOR/"usr/bin/lua"),
                          str(FIXTURE),str(ROOT/"overlay/usr/lib/lua")])

    def test_full_management_request_is_private_and_redacted(self):
        s=MODULE.read_text()
        self.assertIn("function M.prepare_management",s)
        self.assertIn("management_request(request)",s)
        self.assertIn("contains_configuration_values=false",s)
        self.assertIn("production_write_allowed=false",s)
        self.assertNotIn("request.ipaddr",s[s.index("function M.redacted_summary"):])

    def test_existing_vlan_only_entrypoint_remains(self):
        s=MODULE.read_text()
        self.assertIn("function M.prepare(snapshot,vlan,parent,zone)",s)
        self.assertIn("return safe(prepare_management,snapshot,{vlan=vlan},parent,zone)",s.replace("\n",""))

if __name__=="__main__":
    unittest.main()
