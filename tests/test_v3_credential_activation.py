from pathlib import Path
import os, subprocess, unittest

ROOT=Path(__file__).resolve().parents[1]
MODULE=ROOT/"overlay/usr/lib/lua/8311/credential_activation.lua"
CONFIG=ROOT/"overlay/usr/lib/lua/8311/config.lua"
FIXTURE=ROOT/"tests/v3_credential_activation_fixture.lua"
VENDOR=Path(os.getenv("AOTT_VENDOR_ROOTFS","/missing"))

class V3CredentialActivationTests(unittest.TestCase):
    def run_fixture(self,command):
        p=subprocess.run(command,cwd=ROOT,capture_output=True,text=True,timeout=30)
        self.assertEqual(p.returncode,0,p.stderr)
        self.assertIn("AOTT_V3_CREDENTIAL_ACTIVATION_PASS",p.stdout)

    def test_host_fixture(self):
        self.run_fixture(["lua5.1",str(FIXTURE),str(ROOT/"overlay/usr/lib/lua")])

    def test_vendor_mips_fixture(self):
        if not os.getenv("AOTT_VENDOR_ROOTFS"): self.skipTest("No vendor rootfs")
        self.run_fixture([
            "qemu-mips-static","-L",str(VENDOR),str(VENDOR/"usr/bin/lua"),
            str(FIXTURE),str(ROOT/"overlay/usr/lib/lua")
        ])

    def test_fixed_shadow_path_atomic_private_write_and_no_shell(self):
        s=MODULE.read_text()
        self.assertIn('local SHADOW="/etc/shadow"',s)
        self.assertIn('"/etc/.shadow.aott."',s)
        self.assertIn('nixio.open_flags("wronly","creat","excl")',s)
        self.assertIn("fd:sync()",s)
        self.assertIn('nixio.getsp("root")',s)
        for forbidden in ("os.execute","io.popen","shellquote","logger","to_console"):
            self.assertNotIn(forbidden,s)

    def test_config_result_is_explicitly_redacted(self):
        s=CONFIG.read_text()
        self.assertIn('prepared.route=="credential"',s)
        self.assertIn('contains_credential_material=false',s)
        self.assertIn('observed_source=receipt.observed_source',s)
        self.assertNotIn('desired=prepared.changes[1].effective',s)

    def test_lua_syntax(self):
        for p in (MODULE,CONFIG):
            r=subprocess.run(["luac5.1","-p",str(p)],capture_output=True,text=True)
            self.assertEqual(r.returncode,0,r.stderr)

if __name__=="__main__":
    unittest.main()
