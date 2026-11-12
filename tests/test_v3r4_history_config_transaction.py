"""V3r4 History settings: verified UCI and service rollback.

Runs the same isolated in-memory Lua fixture on host Lua 5.1
and extracted vendor MIPS Lua. No real UCI, network or service writes.
"""
import os
from pathlib import Path
import shutil
import subprocess
import unittest

ROOT=Path(__file__).resolve().parents[1]
FIXTURE=ROOT/"tests/v3r4_history_config_transaction_fixture.lua"
VENDOR=Path(os.getenv("AOTT_VENDOR_ROOTFS","/missing-vendor-rootfs"))


class V3R4HistoryConfigTransactionTests(unittest.TestCase):
    def run_fixture(self,cmd):
        proc=subprocess.run(
            [*cmd,str(FIXTURE),str(ROOT/"overlay/usr/lib/lua")],
            capture_output=True,text=True,cwd=ROOT,timeout=45
        )
        self.assertEqual(proc.returncode,0,proc.stderr)
        self.assertIn("AOTT_V3R4_HISTORY_SETTINGS_TRANSACTION_PASS",proc.stdout)
        self.assertIn("checks=116",proc.stdout)

    def test_host_lua_transaction_failures(self):
        if not shutil.which("lua5.1"):self.skipTest("Lua 5.1 unavailable")
        self.run_fixture(["lua5.1"])

    def test_vendor_mips_transaction_failures(self):
        if not os.getenv("AOTT_VENDOR_ROOTFS"):
            self.skipTest("Vendor rootfs missing")
        native=VENDOR/"usr/bin/lua"
        self.assertTrue(native.is_file())
        self.run_fixture(["qemu-mips-static","-L",str(VENDOR),str(native)])

    def test_no_generic_commands_or_unbounded_writes(self):
        source=(ROOT/"overlay/usr/lib/lua/8311/history_config.lua").read_text()
        self.assertIn('web.lock("/tmp/8311-history-config.lock")',source)
        self.assertIn("verified_readback",source)
        self.assertIn("equal_settings",source)
        self.assertIn("rollback unverified",source)
        self.assertNotIn("os.execute",source)
        self.assertNotIn("io.popen",source)
        for file in (FIXTURE,ROOT/"overlay/usr/lib/lua/8311/history_config.lua"):
            proc=subprocess.run(["luac5.1","-p",str(file)],
                                capture_output=True,text=True,timeout=10)
            self.assertEqual(proc.returncode,0,proc.stderr)


if __name__=="__main__":
    unittest.main()
