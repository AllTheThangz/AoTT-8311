from pathlib import Path
import os, subprocess, unittest

ROOT=Path(__file__).resolve().parents[1]
LUA=ROOT/"overlay/usr/lib/lua"
MODULE=LUA/"8311/remote_firewall.lua"
FIXTURE=ROOT/"tests/v3_remote_firewall_fixture.lua"
ACCESS=ROOT/"overlay/usr/lib/lua/8311/access_config.lua"
RECOVERY=ROOT/"overlay/usr/lib/lua/8311/access_recovery_store.lua"
VENDOR=Path(os.getenv("AOTT_VENDOR_ROOTFS","/missing-vendor-rootfs"))

class V3RemoteFirewallTests(unittest.TestCase):
    def run_fixture(self,argv):
        p=subprocess.run(argv+[str(FIXTURE),str(LUA)],cwd=ROOT,
                         capture_output=True,text=True,timeout=30)
        self.assertEqual(p.returncode,0,p.stderr)
        self.assertIn("AOTT_V3_REMOTE_FIREWALL_PASS",p.stdout)

    def test_host_fixture(self):
        self.run_fixture(["lua5.1"])

    def test_vendor_mips_fixture(self):
        if not os.getenv("AOTT_VENDOR_ROOTFS"):
            self.skipTest("No extracted vendor rootfs configured")
        self.run_fixture(["qemu-mips-static","-L",str(VENDOR),
                          str(VENDOR/"usr/bin/lua")])

    def test_fixed_residential_scope(self):
        s=MODULE.read_text()
        self.assertIn('local PREFIX="AoTT-Remote-HTTPS-"',s)
        self.assertIn('row.src~="wan"',s)
        self.assertIn('row.proto~="tcp"',s)
        self.assertIn('row.family~="ipv4"',s)
        self.assertIn('row.target~="ACCEPT"',s)
        self.assertIn('"/sbin/fw3","-4","print"',s)
        for forbidden in ("forward=","masq=","redirect","dnat","snat",
                          "os.execute","io.popen","shellquote"):
            self.assertNotIn(forbidden,s)

    def test_source_scope_is_bounded(self):
        s=MODULE.read_text()
        self.assertIn("prefix<24 or prefix>32",s)
        self.assertIn("too_many_remote_sources",s)
        self.assertIn("overlapping_remote_sources",s)
        self.assertIn("remote_source_cidr_not_network",s)
        self.assertIn("remote_source_scope_too_broad",s)

    def test_access_product_defaults_remote_off(self):
        s=ACCESS.read_text()
        self.assertIn('{id="remote_gui_enabled",type="bool",default="0"}',s)
        self.assertIn('{id="remote_gui_ipv4_sources",type="cidr4_list",default=""}',s)
        self.assertIn("Remote HTTPS requires at least one explicit IPv4 source CIDR",s)

    def test_firewall_backup_is_bound_to_pending_recovery(self):
        s=RECOVERY.read_text()
        self.assertIn('firewall={path=ROOT.."/firewall.before"',s)
        self.assertIn('"firewall="..hashes.firewall',s)
        self.assertIn("firewall_sha256",s)

    def test_module_compiles(self):
        p=subprocess.run(["luac5.1","-p",str(MODULE)],capture_output=True,text=True,timeout=10)
        self.assertEqual(p.returncode,0,p.stderr)

if __name__=="__main__":
    unittest.main()
