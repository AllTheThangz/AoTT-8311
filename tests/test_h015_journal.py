"""H-015 source-only, bounded flash-history journal safety tests.

The journal library has no real filesystem operations. It uses an injected
fake storage adapter, including injected truncation and power-cut faults.
Vendor-MIPS tests use a previously extracted offline rootfs in QEMU.
"""
import os
from pathlib import Path
import shutil
import subprocess
import unittest

ROOT=Path(__file__).resolve().parents[1]
MODEL=ROOT/"prototypes/history/8311/history_journal.lua"
FIXTURE=ROOT/"tests/h015_journal_fixture.lua"
VENDOR=Path(os.getenv("AOTT_VENDOR_ROOTFS",
                     "/not_connected/offline_mips_rootfs"))


class DurableJournalSourceTests(unittest.TestCase):
    def fixture(self,runtime):
        p=subprocess.run(
            runtime+[str(FIXTURE),str(MODEL)],
            capture_output=True,text=True,cwd=ROOT,timeout=100,
        )
        self.assertEqual(p.returncode,0,p.stderr)
        self.assertIn("AOTT_H015_JOURNAL_FIXTURE_PASS checks=2604",
                      p.stdout)
        self.assertIn(
            "AOTT_H015_CALENDAR_AND_STAGE_FIXTURE_PASS checks=2624",
            p.stdout)

    def test_host_lua_51_power_cut_and_90day_fixture(self):
        if not shutil.which("lua5.1"):
            self.skipTest("Host Lua 5.1 unavailable")
        self.fixture(["lua5.1"])

    def test_offline_vendor_mips_power_cut_and_90day_fixture(self):
        if not os.getenv("AOTT_VENDOR_ROOTFS"):
            self.skipTest("Extracted offline vendor rootfs not supplied")
        self.assertTrue((VENDOR/"usr/bin/lua").is_file())
        self.assertIsNotNone(shutil.which("qemu-mips-static"))
        self.fixture(["qemu-mips-static","-L",str(VENDOR),
                      str(VENDOR/"usr/bin/lua")])

    def test_lua51_compilation(self):
        if not shutil.which("luac5.1"):
            self.skipTest("Lua 5.1 compiler unavailable")
        for path in (MODEL,FIXTURE):
            with self.subTest(file=path.name):
                p=subprocess.run(["luac5.1","-p",str(path)],
                                 capture_output=True,text=True,timeout=15)
                self.assertEqual(p.returncode,0,p.stderr)

    def test_no_real_storage_network_or_firmware_operations(self):
        code=MODEL.read_text()
        self.assertFalse(
            (ROOT/"overlay/usr/lib/lua/8311/history_journal.lua").exists()
        )
        self.assertNotIn("history_journal.lua",
                         (ROOT/"MANIFEST.json").read_text())
        active="\n".join(
            line for line in code.splitlines()
            if line.strip() and not line.lstrip().startswith("--"))
        for forbidden in (
            "io.open(","io.popen(","os.execute(","socket.",
            "require \"nixio\"","require \"luci\"","fwenv_set","fw_printenv",
            "uci:commit","luci.http","/dev/mtd","/usr/bin/pon",
            "setInterval(","cron(","reboot(","fwrite(","rename(",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden,active)
        self.assertIn("function M.recover(adapter)",code)
        self.assertIn("function M.flush(state,adapter,current_epoch,now_uptime)",code)

    def test_cadence_two_slot_integrity_and_privacy_contract(self):
        code=MODEL.read_text()
        for marker in (
            "local MAX_SLOT_BYTES=160*1024",
            "local MAX_EVENTS=256",
            "local MAX_HOURS=2160",
            "local MIN_FLUSH_MS=900000",
            "MAX_SLOT_BYTES=MAX_SLOT_BYTES",
            "MAX_LOGICAL_BYTES=3*MAX_SLOT_BYTES",
            'state.uncertain=true',
            'return nil,"journal_storage_unavailable"',
            'return nil,"ambiguous_history_generation"',
            'return nil,"no_valid_history_checkpoint"',
            'return nil,"routine_write_deferred"',
            'return nil,"checkpoint_readback_unverified"',
            'return nil,"invalid_staged_record"',
            "function M.calendar_counts(state,days)",
            'full_period_retention_proven=false',
            'continuous_collection_proven=false',
            'actual_isp_availability_proven=false',
            'verified_atomic_filesystem_semantics=false',
            'hardware_flash_wear_unverified=true',
            'source_only_not_deployed=true',
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker,code)
        self.assertNotIn("Md5",code)
        self.assertIn("Adler-32 detects accidental truncation/corruption",code)

    def test_synthetic_failure_recovery_matrix_is_exercised(self):
        fixture=FIXTURE.read_text()
        for marker in (
            "torn_B_falls_back_to_A",
            "both_corrupt_recovery_stops",
            "duplicate_generation_conflict",
            "torn_write_rejected",
            "frozen_writer_refuses_retry",
            "new_boot_minimum",
            "hourly_summary_",
            "300_event_capacity_",
            "7day_hourly_bounds",
            "30day_hourly_bounds",
            "90day_all_synthetic_hourly_rows",
            "missing_NTP_does_not_invent_calendar",
            "manually_corrupted_stage_rejected",
            "checkpoint_readback_unverified",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker,fixture)


if __name__=="__main__":
    unittest.main()
