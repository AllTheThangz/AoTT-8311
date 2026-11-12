"""V3r4 RAM-only PRX126 Ethernet error/drop history.

Host Lua and extracted vendor MIPS Lua run the exact same injected
counter-reset, missing-sample, reboot and privacy fixture.
"""
import os
from pathlib import Path
import shutil
import subprocess
import unittest

ROOT=Path(__file__).resolve().parents[1]
FIXTURE=ROOT/"tests/v3r4_history_integrity_fixture.lua"
VENDOR=Path(os.getenv("AOTT_VENDOR_ROOTFS","/missing-vendor-rootfs"))


class V3R4HistoryIntegrityTests(unittest.TestCase):
    def test_host_lua_fixtures(self):
        if not shutil.which("lua5.1"):
            self.skipTest("Lua 5.1 unavailable")
        self.run_fixture(["lua5.1"])

    def test_vendor_mips_lua_fixtures(self):
        if not os.getenv("AOTT_VENDOR_ROOTFS"):
            self.skipTest("Vendor rootfs unavailable")
        native=VENDOR/"usr/bin/lua"
        self.assertTrue(native.is_file())
        self.run_fixture(["qemu-mips-static","-L",str(VENDOR),str(native)])

    def run_fixture(self,cmd):
        p=subprocess.run([*cmd,str(FIXTURE),str(ROOT/"overlay/usr/lib/lua")],
                         capture_output=True,text=True,cwd=ROOT,timeout=40)
        self.assertEqual(p.returncode,0,p.stderr)
        self.assertIn("AOTT_V3R4_RAM_ETH_INTEGRITY_PASS",p.stdout)
        self.assertIn("assertions=36",p.stdout)

    def test_lua_syntax_and_readonly_probe_contract(self):
        files=(
            "history_native_probe.lua","history_sampler.lua",
            "history_export.lua","history_snapshot_shape.lua",
        )
        for name in files:
            p=ROOT/"overlay/usr/lib/lua/8311"/name
            with self.subTest(module=name):
                r=subprocess.run(["luac5.1","-p",str(p)],
                                 capture_output=True,text=True,timeout=10)
                self.assertEqual(r.returncode,0,r.stderr)
        source=(ROOT/"overlay/usr/lib/lua/8311/history_native_probe.lua").read_text()
        self.assertIn('"/usr/sbin/ethtool","-S","eth0_0"',source)
        self.assertIn('"/usr/bin/pon","psg"',source)
        self.assertNotIn("setenv",source)
        self.assertNotIn("io.popen",source)
        self.assertNotIn("os.execute",source)


if __name__=="__main__":
    unittest.main()
