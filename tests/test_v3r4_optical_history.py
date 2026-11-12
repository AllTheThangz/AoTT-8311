"""V3r4 opt-in PRX126 optical/thermal history tests.

All Lua tests are memory-only. Host and QEMU vendor MIPS execute the same
DDM decoder, selective sampler, export-shape and epoch-boundary fixture.
"""
import os
from pathlib import Path
import shutil
import subprocess
import unittest

ROOT=Path(__file__).resolve().parents[1]
FIXTURE=ROOT/"tests/v3r4_optical_history_fixture.lua"
VENDOR=Path(os.getenv("AOTT_VENDOR_ROOTFS","/missing-vendor-rootfs"))


class OpticalHistoryTests(unittest.TestCase):
    def run_fixture(self,argv):
        p=subprocess.run([*argv,str(FIXTURE),
                          str(ROOT/"overlay/usr/lib/lua")],
                         capture_output=True,text=True,cwd=ROOT,timeout=40)
        self.assertEqual(p.returncode,0,p.stderr)
        self.assertIn("AOTT_V3R4_OPTICAL_RAM_HISTORY_PASS assertions=63",p.stdout)

    def test_host_lua_optical_reboot_and_redaction(self):
        if not shutil.which("lua5.1"):self.skipTest("Lua 5.1 unavailable")
        self.run_fixture(["lua5.1"])

    def test_vendor_mips_lua_optical_reboot_and_redaction(self):
        if not os.getenv("AOTT_VENDOR_ROOTFS"):
            self.skipTest("Offline vendor rootfs unavailable")
        lua=VENDOR/"usr/bin/lua"
        self.assertTrue(lua.is_file())
        self.run_fixture(["qemu-mips-static","-L",str(VENDOR),str(lua)])

    def test_fixed_read_only_source_and_independent_worker_cadence(self):
        native=(ROOT/"overlay/usr/lib/lua/8311/history_native_probe.lua").read_text()
        optic=(ROOT/"overlay/usr/lib/lua/8311/history_optical_probe.lua").read_text()
        worker=(ROOT/"overlay/usr/libexec/8311-history-worker.lua").read_text()
        cfg=(ROOT/"overlay/usr/lib/lua/8311/history_config.lua").read_text()
        self.assertIn('selected.optical',native)
        self.assertIn('"/sys/class/pon_mbox/pon_mbox0/device/eeprom51"',optic)
        self.assertIn('"optical_ddm_unavailable"',optic)
        self.assertIn("no_raw_eeprom_export=true",optic)
        self.assertIn("next_optical=0",worker)
        self.assertIn("runtime.optical_enabled",worker)
        self.assertIn("runtime.optical_interval_seconds",worker)
        self.assertIn('optical_enabled="0"',cfg)
        self.assertIn('optical_interval_seconds="120"',cfg)
        self.assertNotIn("os.execute",optic)
        self.assertNotIn("io.popen",optic)
        self.assertNotIn("fw_setenv",optic)
        for name in (
            "history_optical_probe.lua","history_native_probe.lua",
            "history_config.lua","history_sampler.lua",
            "history_export.lua","history_snapshot_shape.lua"
        ):
            file=ROOT/"overlay/usr/lib/lua/8311"/name
            p=subprocess.run(["luac5.1","-p",str(file)],
                             capture_output=True,text=True,timeout=10)
            self.assertEqual(p.returncode,0,p.stderr)


if __name__=="__main__":
    unittest.main()
