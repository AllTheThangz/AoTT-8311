from pathlib import Path
import os, subprocess, unittest

ROOT=Path(__file__).resolve().parents[1]
MODULE=ROOT/"overlay/usr/lib/lua/8311/management_access.lua"
TX=ROOT/"overlay/usr/lib/lua/8311/management_transaction.lua"
STORE=ROOT/"overlay/usr/lib/lua/8311/management_recovery_store.lua"
FIXTURE=ROOT/"tests/v3_management_access_fixture.lua"
VENDOR=Path(os.getenv("AOTT_VENDOR_ROOTFS","/missing"))

class V3ManagementAccessTests(unittest.TestCase):
    def run_fixture(self,cmd):
        p=subprocess.run(cmd,cwd=ROOT,capture_output=True,text=True,timeout=30)
        self.assertEqual(p.returncode,0,p.stderr)
        self.assertIn("AOTT_V3_MANAGEMENT_ACCESS_PASS",p.stdout)

    def test_host_fixture(self):
        self.run_fixture(["lua5.1",str(FIXTURE),str(ROOT/"overlay/usr/lib/lua")])

    def test_vendor_mips_fixture(self):
        if not os.getenv("AOTT_VENDOR_ROOTFS"): self.skipTest("No vendor rootfs")
        self.run_fixture([
            "qemu-mips-static","-L",str(VENDOR),str(VENDOR/"usr/bin/lua"),
            str(FIXTURE),str(ROOT/"overlay/usr/lib/lua")
        ])

    def test_modules_compile(self):
        for p in (MODULE,TX,STORE):
            r=subprocess.run(["luac5.1","-p",str(p)],capture_output=True,text=True)
            self.assertEqual(r.returncode,0,r.stderr)

    def test_transaction_backs_up_and_restores_dropbear(self):
        s=STORE.read_text()
        self.assertIn('local DROPBEAR=DIR.."/dropbear.before"',s)
        self.assertIn("AOTT-MANAGEMENT-PENDING-2",s)
        self.assertIn("dropbear_sha256",s)
        tx=TX.read_text()
        self.assertIn('local access=require "8311.management_access"',tx)
        self.assertIn("provider.apply_access",tx)
        self.assertIn("access.verify(request.vlan)",tx)
        self.assertIn("access.import_raw(DROPBEAR_BACKUP)",tx)
        self.assertLess(tx.index("provider.apply_access"),tx.index("provider.reload"))

    def test_access_scope_is_only_lct_or_mgmt_and_fixed_dropbear_paths(self):
        s=MODULE.read_text()
        self.assertIn("local ALLOWED={lct=true,mgmt=true}",s)
        self.assertIn('"/etc/init.d/dropbear","restart"',s)
        self.assertIn('"/bin/pidof","dropbear"',s)
        self.assertIn('raw:find("^/usr/sbin/dropbear%z")',s)
        self.assertIn('"/ptconf/8311/aott-recovery/v1/management/dropbear.before"',s)
        for forbidden in ("os.execute","io.popen","shellquote","eval("):
            self.assertNotIn(forbidden,s)

if __name__=="__main__":
    unittest.main()
