"""H-021 offline independent PON/Ethernet sampling cadence tests.

Real Lua source modules and fixed native parsers are exercised with mock
read-only providers. Vendor MIPS tests use an extracted offline rootfs.
"""
import os
from pathlib import Path
import shutil
import subprocess
import unittest

ROOT=Path(__file__).resolve().parents[1]
LIB=ROOT/"prototypes/history"
OVERLAY=ROOT/"overlay/usr/lib/lua"
FIXTURE=ROOT/"tests/h021_independent_cadence_fixture.lua"
MIPS=Path(os.environ.get("AOTT_VENDOR_ROOTFS",
                         "/missing/offline-mips-rootfs"))


class H021IndependentSamplingTests(unittest.TestCase):
    def run_case(self,exec_prefix):
        command=[*exec_prefix,str(FIXTURE),str(LIB),str(OVERLAY)]
        r=subprocess.run(command,cwd=ROOT,capture_output=True,text=True,
                         timeout=35)
        self.assertEqual(r.returncode,0,r.stderr)
        self.assertIn(
            "AOTT_H021_INDEPENDENT_CADENCE_FIXTURE_PASS checks=324",
            r.stdout
        )

    def test_host_lua_independent_cadences(self):
        if not shutil.which("lua5.1"):
            self.skipTest("Host Lua unavailable")
        self.run_case(["lua5.1"])

    def test_offline_vendor_mips_independent_cadences(self):
        if not os.environ.get("AOTT_VENDOR_ROOTFS"):
            self.skipTest("Vendor rootfs not supplied")
        self.assertIsNotNone(shutil.which("qemu-mips-static"))
        self.assertTrue((MIPS/"usr/bin/lua").is_file())
        self.run_case(["qemu-mips-static","-L",str(MIPS),
                       str(MIPS/"usr/bin/lua")])

    def test_lua_syntax(self):
        if not shutil.which("luac5.1"):
            self.skipTest("Lua compiler unavailable")
        for path in (FIXTURE,LIB/"8311/history_collector.lua",
                     LIB/"8311/history_sampler.lua",
                     LIB/"8311/history_native_probe.lua"):
            with self.subTest(path=path.name):
                x=subprocess.run(["luac5.1","-p",str(path)],
                                 capture_output=True,text=True,timeout=10)
                self.assertEqual(x.returncode,0,x.stderr)

    def test_selection_and_sample_semantics(self):
        reader=(LIB/"8311/history_native_probe.lua").read_text()
        sampler=(LIB/"8311/history_sampler.lua").read_text()
        for line in (
            "function M.read_selected(provider, selected)",
            '"invalid_probe_selection"',
            'not selected.pon and "not_sampled"',
            'not selected.host and "not_sampled"',
            'observed={pon=selected.pon,host=selected.host}',
        ):
            self.assertIn(line,reader)
        for line in (
            "function M.ingest_selected(state,input)",
            '"unscheduled_channel_supplied_data"',
            'state.selected_rate_previous',
            'pon_due=input.observed.pon',
            'host_due=input.observed.host',
            '"partial_interval"',
            '"not_sampled"',
            'math_model.eth_rates(old,current)',
        ):
            self.assertIn(line,sampler)

    def test_due_scheduling_and_proven_reboot(self):
        source=(LIB/"8311/history_collector.lua").read_text()
        for marker in (
            "function M.new_independent(preferences,capability,mode)",
            "function M.tick_independent(handle,now,provider)",
            "probe.read_selected,provider,selection",
            "sampler.ingest_selected,p.history,snapshot",
            "p.next_pon_due=now+p.pon_interval",
            "p.next_host_due=now+p.host_interval",
            '"reboot_identity_unverified"',
            'snapshot.boot==p.last_boot',
            '"collector_clock_regressed"',
            'p.last_boot=snapshot.boot',
            '"collector_interval_not_qualified"',
            '"optical_cadence_not_implemented"',
            "independent_channel_cadences_implemented=p.mode==\"independent\"",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker,source)

    def test_browser_projection_supports_not_sampled_distinct_from_failed(self):
        ui=(LIB/"ui/history.js").read_text()
        exporter=(LIB/"8311/history_export.lua").read_text()
        aggregate=(LIB/"8311/history_aggregate.lua").read_text()
        for source in (ui,exporter,aggregate):
            self.assertIn("not_sampled",source)
            self.assertIn("partial_interval",source)
        self.assertIn("Not sampled this interval",ui)
        self.assertIn('record.pon_observation=="unavailable"',aggregate)
        self.assertIn('record.host_link_observation=="unavailable"',aggregate)

    def test_not_deployed_or_connected_to_isp(self):
        for source in ("history_collector.lua","history_native_probe.lua"):
            self.assertFalse((ROOT/"overlay/usr/lib/lua/8311"/source).exists())
            self.assertNotIn(source,(ROOT/"MANIFEST.json").read_text())
        self.assertNotIn("/etc/init.d",
                         (LIB/"8311/history_collector.lua").read_text())
        self.assertNotIn("socket.",
                         (LIB/"8311/history_collector.lua").read_text())


if __name__=="__main__":
    unittest.main()
