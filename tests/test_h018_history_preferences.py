"""H-018 offline residential history preference checks.

Host and vendor MIPS Lua execute the same synthetic fixture. No device access.
"""
import os
from pathlib import Path
import shutil
import subprocess
import unittest

ROOT=Path(__file__).resolve().parents[1]
SOURCE=ROOT/"prototypes/history/8311/history_preferences.lua"
FIXTURE=ROOT/"tests/h018_history_preferences_fixture.lua"
VENDOR=Path(os.environ.get("AOTT_VENDOR_ROOTFS","/unavailable/offline-rootfs"))

class HistoryPreferencesTests(unittest.TestCase):
    def run_fixture(self,command):
        result=subprocess.run(command+[str(FIXTURE),str(SOURCE)],
                              capture_output=True,text=True,cwd=ROOT,timeout=35)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertIn("AOTT_H018_SOURCE_PREFERENCES_FIXTURE_PASS checks=4338",
                      result.stdout)

    def test_host_lua(self):
        if not shutil.which("lua5.1"):
            self.skipTest("Lua unavailable")
        self.run_fixture(["lua5.1"])

    def test_offline_mips_lua(self):
        if not os.environ.get("AOTT_VENDOR_ROOTFS"):
            self.skipTest("Offline vendor runtime unavailable")
        self.assertIsNotNone(shutil.which("qemu-mips-static"))
        self.assertTrue((VENDOR/"usr/bin/lua").is_file())
        self.run_fixture(["qemu-mips-static","-L",str(VENDOR),
                          str(VENDOR/"usr/bin/lua")])

    def test_lua_syntax(self):
        if not shutil.which("luac5.1"):
            self.skipTest("Lua compiler unavailable")
        for file in (SOURCE,FIXTURE):
            result=subprocess.run(["luac5.1","-p",str(file)],
                                  capture_output=True,text=True,timeout=10)
            self.assertEqual(result.returncode,0,result.stderr)

    def test_source_only_and_defaults(self):
        model=SOURCE.read_text()
        for required in ("sampling_enabled=false","persist_enabled=false",
                         "remote_notifications=false","local_alerts_enabled=false",
                         "heavy_probe_seconds=0","ram_sample_limit=120",
                         "ram_event_limit=128","flush_interval_seconds=1800",
                         "if worst_seconds>720 then",
                         "function M.preview(","function M.simulate(",
                         "function M.describe(",
                         "no_real_setting_save=true"):
            with self.subTest(required=required):
                self.assertIn(required,model)
        self.assertTrue((ROOT/"overlay/usr/lib/lua/8311/history_preferences.lua").is_file())
        self.assertIn("history_preferences.lua",
                      (ROOT/"MANIFEST.json").read_text())

    def test_all_features_and_rejections_covered(self):
        source=FIXTURE.read_text()
        for expected in ("all_17_fields_discoverable",
                         "no_remote_alerts_by_default",
                         "unqualified_sampler","unqualified_storage",
                         "unqualified_optical_threshold",
                         "unsafe_fast_polling","flash_wear_guard",
                         "concurrent_stale_revision","unknown_key_injection",
                         "explicit_threshold_clear","no_op_staging_rejected",
                         "1000_memory_only_stages_"):
            self.assertIn(expected,source)

if __name__=="__main__":
    unittest.main()
