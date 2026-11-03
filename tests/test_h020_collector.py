"""H-020 single-owner source-only collector integration regressions.

Runs the real H-011 fixed native parser, H-012 event sampler and H-016
history projector under injected fake kernel/native outputs.
No live host, ONU, network, file I/O or service is contacted.
"""
import os
from pathlib import Path
import shutil
import subprocess
import unittest

ROOT=Path(__file__).resolve().parents[1]
LIB=ROOT/"prototypes/history"
COLLECTOR=LIB/"8311/history_collector.lua"
SAMPLER=LIB/"8311/history_sampler.lua"
FIXTURE=ROOT/"tests/h020_collector_fixture.lua"
OVERLAY=ROOT/"overlay/usr/lib/lua"
VENDOR=Path(os.environ.get("AOTT_VENDOR_ROOTFS",
                           "/missing/extracted-offline-rootfs"))


class H020CollectorIntegrationTests(unittest.TestCase):
    def run_fixture(self,command):
        p=subprocess.run(
            command+[str(FIXTURE),str(LIB),str(OVERLAY)],
            capture_output=True,text=True,cwd=ROOT,timeout=35,
        )
        self.assertEqual(p.returncode,0,p.stderr)
        self.assertIn(
            "AOTT_H020_SINGLE_COLLECTOR_FIXTURE_PASS checks=1181",
            p.stdout,
        )

    def test_host_lua_collector(self):
        if not shutil.which("lua5.1"):
            self.skipTest("Host Lua 5.1 unavailable")
        self.run_fixture(["lua5.1"])

    def test_extracted_vendor_mips_collector(self):
        if not os.environ.get("AOTT_VENDOR_ROOTFS"):
            self.skipTest("Offline vendor MIPS rootfs not supplied")
        self.assertTrue((VENDOR/"usr/bin/lua").is_file())
        self.assertIsNotNone(shutil.which("qemu-mips-static"))
        self.run_fixture([
            "qemu-mips-static","-L",str(VENDOR),str(VENDOR/"usr/bin/lua"),
        ])

    def test_lua51_syntax(self):
        if not shutil.which("luac5.1"):
            self.skipTest("Host Lua compiler unavailable")
        for path in (COLLECTOR,SAMPLER,FIXTURE):
            with self.subTest(path=path.name):
                p=subprocess.run(["luac5.1","-p",str(path)],
                    capture_output=True,text=True,timeout=10)
                self.assertEqual(p.returncode,0,p.stderr)

    def test_single_instance_and_hardware_gate(self):
        code=COLLECTOR.read_text()
        for required in (
            'local ACTIVE=setmetatable({}, {__mode="v"})',
            '"collector_owner_exists"',
            'mode~="offline_synthetic"',
            '"hardware_not_directly_qualified"',
            '"independent_channel_cadences_not_yet_implemented"',
            '"collector_interval_not_qualified"',
            '"native_probe_already_in_flight"',
            'function M.close(handle)',
            'function M.tick(handle,now,provider)',
            'function M.status(handle)',
            'function M.view(handle,range,limit)',
            'function M.export_json(handle,range,limit)',
            'function M.export_csv(handle,range,limit)',
            '"collector_clock_regressed"',
            '"snapshot_clock_mismatch"',
            '"no_valid_native_measurement"',
        ):
            with self.subTest(marker=required):
                self.assertIn(required,code)

    def test_bounded_retry_and_no_untrusted_external_source(self):
        code=COLLECTOR.read_text()
        for required in (
            "local RETRY_SECONDS={15,30,60,120,300}",
            'retry_after_seconds=RETRY_SECONDS[p.failures]',
            'p.next_due=now+RETRY_SECONDS[p.failures]',
            "local ok,snapshot,availability=pcall(probe.read_once,provider)",
            "sampler.ingest,p.history,snapshot",
            'no_isp_availability_proof=true',
            'no_timer_or_background_process=true',
            'no_live_firmware_integration=true',
            'source_only_not_live=true',
            'no_device_write=true',
            'no_flash_write=true',
        ):
            with self.subTest(marker=required):
                self.assertIn(required,code)

    def test_unavailable_event_de_duplication(self):
        text=SAMPLER.read_text()
        for required in (
            'last_unavailable_channels=nil',
            'absent~=state.last_unavailable_channels',
            'state.last_unavailable_channels=absent',
            'if valid_status then state.last_unavailable_channels=nil end',
        ):
            with self.subTest(marker=required):
                self.assertIn(required,text)
        code=FIXTURE.read_text()
        self.assertIn("sustained_partial_one_event_only",code)
        self.assertIn("new_PON_probe_failure_once",code)
        self.assertIn("real_PON_change_recorded",code)

    def test_no_boot_autostart_flash_or_http_handler(self):
        self.assertFalse(
            (ROOT/"overlay/usr/lib/lua/8311/history_collector.lua").exists())
        self.assertNotIn(
            "history_collector.lua",(ROOT/"MANIFEST.json").read_text())
        source=COLLECTOR.read_text()
        active="\n".join(x for x in source.splitlines()
                         if x.strip() and not x.lstrip().startswith("--"))
        for forbidden in (
            "io.open(","io.popen(","os.execute(","socket.",
            "nixio.fs","uci:commit","luci.http","/dev/mtd",
            "setTimeout(","setInterval(","cron(","sleep(",
            "/etc/init.d/","sys.process.exec","fs.writefile(",
            "fwenv_set",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden,active)


if __name__=="__main__":
    unittest.main()
