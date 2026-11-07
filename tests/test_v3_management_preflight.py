from pathlib import Path
import os, shutil, subprocess, unittest

ROOT=Path(__file__).resolve().parents[1]
OVERLAY=ROOT/"overlay"
LUA=OVERLAY/"usr/lib/lua"
FIXTURE=ROOT/"tests/v3_management_preflight_fixture.lua"
VENDOR=Path(os.getenv("AOTT_VENDOR_ROOTFS","/missing/vendor-rootfs"))

class V3ManagementPreflightTests(unittest.TestCase):
    def run_fixture(self,argv):
        p=subprocess.run(argv+[str(FIXTURE),str(LUA)],cwd=ROOT,
                         capture_output=True,text=True,timeout=20)
        self.assertEqual(p.returncode,0,p.stderr)
        self.assertIn("AOTT_V3_MANAGEMENT_PREFLIGHT_PASS",p.stdout)

    def test_host_lua_preflight(self):
        if not shutil.which("lua5.1"): self.skipTest("Lua 5.1 unavailable")
        self.run_fixture(["lua5.1"])

    def test_vendor_mips_preflight(self):
        if not shutil.which("qemu-mips-static") or not (VENDOR/"usr/bin/lua").is_file():
            self.skipTest("Vendor MIPS runtime unavailable")
        self.run_fixture(["qemu-mips-static","-L",str(VENDOR),str(VENDOR/"usr/bin/lua")])

    def test_runtime_modules_ship_without_production_writer(self):
        for name in ("native_management_reader.lua","recovery_storage.lua",
                     "vlan_transition.lua","management_preflight.lua"):
            self.assertTrue((LUA/"8311"/name).is_file(),name)
        pre=(LUA/"8311/management_preflight.lua").read_text()
        for forbidden in ("fw_setenv","fwenv_set","uci:commit","fs.mkdir",
                          "os.execute","io.popen","ubiupdatevol","/dev/mtd"):
            self.assertNotIn(forbidden,pre)
        transition=(LUA/"8311/vlan_transition.lua").read_text()
        self.assertIn('mode~="offline_synthetic"',transition)
        self.assertIn('production_write_allowed=false',transition)

    def test_controller_has_preview_but_no_apply_route(self):
        ctl=(OVERLAY/"usr/lib/lua/luci/controller/8311.lua").read_text()
        self.assertIn('entry({"admin", "8311", "management_preflight"}',ctl)
        self.assertIn('entry({"admin", "8311", "management_vlan_preview"}',ctl)
        self.assertNotIn('"management_vlan_apply"',ctl)
        self.assertIn("management_preflight.preview(values.vlan)",ctl)
        self.assertIn("production_write_allowed=false",ctl)

    def test_view_is_explicitly_preview_only(self):
        view=(OVERLAY/"usr/lib/lua/luci/view/8311/management_preflight.htm").read_text()
        self.assertIn("Preview only",view)
        self.assertIn("Apply is intentionally unavailable",view)
        self.assertIn("No IP address, DNS value, MAC address",view)

if __name__=="__main__":
    unittest.main()
