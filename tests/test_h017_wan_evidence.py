"""H-017: purely synthetic independent router/WAN reachability evidence tests.

The model has no network transport, shell process, periodic service or ONU
read. The real router-side probe adapter and provenance authentication
remain release blockers.
"""
import os
from pathlib import Path
import shutil
import subprocess
import unittest

ROOT=Path(__file__).resolve().parents[1]
PROTOTYPE=ROOT/"prototypes/history"
MODULE=PROTOTYPE/"8311/wan_evidence.lua"
FIXTURE=ROOT/"tests/h017_wan_evidence_fixture.lua"
VENDOR=Path(os.environ.get("AOTT_VENDOR_ROOTFS",
                           "/unavailable/offline-vendor-rootfs"))


class WanEvidenceSourceTests(unittest.TestCase):
    def run_fixture(self,cmd):
        proc=subprocess.run(
            cmd+[str(FIXTURE),str(PROTOTYPE)],
            cwd=ROOT,capture_output=True,text=True,timeout=35,
        )
        self.assertEqual(proc.returncode,0,proc.stderr)
        self.assertIn("AOTT_H017_WAN_EVIDENCE_FIXTURE_PASS checks=1127",
                      proc.stdout)

    def test_host_lua_synthetic_router_evidence(self):
        if not shutil.which("lua5.1"):
            self.skipTest("Lua 5.1 is not installed")
        self.run_fixture(["lua5.1"])

    def test_real_vendor_mips_lua_synthetic_router_evidence(self):
        if not os.environ.get("AOTT_VENDOR_ROOTFS"):
            self.skipTest("Offline vendor MIPS rootfs not supplied")
        native=VENDOR/"usr/bin/lua"
        self.assertTrue(native.is_file())
        self.assertIsNotNone(shutil.which("qemu-mips-static"))
        self.run_fixture(["qemu-mips-static","-L",str(VENDOR),str(native)])

    def test_lua_51_source_compilation(self):
        if not shutil.which("luac5.1"):
            self.skipTest("No Lua compiler")
        for file in (MODULE,FIXTURE):
            with self.subTest(file=file.name):
                proc=subprocess.run(["luac5.1","-p",str(file)],
                                    capture_output=True,text=True,timeout=10)
                self.assertEqual(proc.returncode,0,proc.stderr)

    def test_no_network_or_device_processes(self):
        self.assertTrue(MODULE.is_file())
        self.assertFalse((ROOT/"overlay/usr/lib/lua/8311/wan_evidence.lua").exists())
        self.assertNotIn("wan_evidence.lua",(ROOT/"MANIFEST.json").read_text())
        src=MODULE.read_text()
        active="\n".join(x for x in src.splitlines()
                         if x.strip() and not x.lstrip().startswith("--"))
        for forbidden in ("io.open","io.popen","os.execute","socket.",
                          "require \"nixio\"","require \"luci\"","fwenv_set",
                          "fwenv_get","curl ","wget ","/bin/sh",
                          "uci:commit","ssh ","cron(","sleep(","reboot("):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden,active)
        self.assertIn("no_network_or_device_action=true",src)
        self.assertIn("declared_source_is_not_authenticated=true",src)

    def test_separate_three_layers_and_refuse_false_isp_fault_claim(self):
        src=MODULE.read_text()
        for required in (
            'raw.origin~="router_wan"',
            'raw.clock_domain~="router_monotonic"',
            'ALLOWED={dns=true,https=true,tcp=true,icmp=true}',
            'local MAX_PROBES=4',
            'status="one_or_more_targets_reached"',
            'status="all_submitted_probes_failed"',
            'status="inconclusive"',
            'status="unavailable"',
            'add("router_reboot_observed")',
            'add("router_probe_sampling_gap"',
            'and "router_probe_result_change"',
            'or "router_probe_evidence_change"',
            'proves_isp_fault=false',
            'proves_full_internet_reachability=false',
            'simultaneous_measurement_unverified=true',
            'router_source_authenticated=false',
            'latency_ms_min=current.latency_ms_min',
        ):
            with self.subTest(required=required):
                self.assertIn(required,src)

    def test_bounded_retention_and_no_target_or_credentials_export(self):
        src=MODULE.read_text()
        for required in (
            'local MAX_QUERY=100',
            'local MAX_GAP=3600',
            'max_events=cap(options.max_events,64,256)',
            'max_samples=cap(options.max_samples,120,720)',
            'return nil,"invalid_probe_latency"',
            'return nil,"nonmonotonic_router_time"',
            'source="declared_router_wan_probes"',
        ):
            self.assertIn(required,src)
        for forbidden in (
            'target_label=probe.target_label',
            'destination=raw.destination',
            'raw_output=raw.raw_output',
            'device_identifier=raw.device_identifier',
            'http.request',
            'dns.query',
        ):
            self.assertNotIn(forbidden,src)


if __name__=="__main__":
    unittest.main()
