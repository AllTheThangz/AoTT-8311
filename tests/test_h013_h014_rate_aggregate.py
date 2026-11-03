"""H-013/H-014 bounded host-side rate window aggregation regressions.

No device target or native commands. Uses the actual source-only sampler and
aggregation model under host Lua and the offline extracted vendor MIPS Lua.
"""
import os
from pathlib import Path
import shutil
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "prototypes/history"
AGGREGATE = SOURCE / "8311/history_aggregate.lua"
SAMPLER = SOURCE / "8311/history_sampler.lua"
FIXTURE = ROOT / "tests/h013_h014_rate_aggregate_fixture.lua"
VENDOR = Path(os.environ.get("AOTT_VENDOR_ROOTFS",
                             "/unavailable/offline-vendor-rootfs"))


class HistoryAggregateSourceTests(unittest.TestCase):
    def run_fixture(self, command):
        result = subprocess.run(
            command + [str(FIXTURE), str(SOURCE)],
            capture_output=True, text=True, cwd=ROOT, timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(
            "AOTT_H013_H014_AGGREGATION_FIXTURE_PASS checks=674",
            result.stdout,
        )

    def test_host_lua_51_aggregation(self):
        if not shutil.which("lua5.1"):
            self.skipTest("Lua 5.1 unavailable")
        self.run_fixture(["lua5.1"])

    def test_offline_vendor_mips_aggregation(self):
        if not os.environ.get("AOTT_VENDOR_ROOTFS"):
            self.skipTest("Offline vendor MIPS rootfs not supplied")
        self.assertIsNotNone(shutil.which("qemu-mips-static"))
        native = VENDOR / "usr/bin/lua"
        self.assertTrue(native.is_file())
        self.run_fixture(["qemu-mips-static", "-L", str(VENDOR),
                          str(native)])

    def test_lua51_syntax(self):
        if not shutil.which("luac5.1"):
            self.skipTest("Lua 5.1 compiler unavailable")
        for path in (AGGREGATE, SAMPLER, FIXTURE):
            with self.subTest(file=path.name):
                result = subprocess.run(
                    ["luac5.1", "-p", str(path)],
                    capture_output=True, text=True, timeout=10,
                )
                self.assertEqual(result.returncode, 0, result.stderr)

    def test_window_aggregation_contract(self):
        source = AGGREGATE.read_text()
        for required in (
            "local MAX_SAMPLES = 720",
            "local MAX_WINDOW_SECONDS = 90 * 86400",
            "local MAX_INTERVAL_SECONDS = 3600",
            "function M.summarize(state,window_seconds)",
            "function M.presets(state)",
            "window_complete=false",
            "not STATUSES[record.status]",
            'record.rate_source~="hardware_ethernet_byte_counters"',
            'record.direction~="host_interface_rx_tx"',
            "when-elapsed >= cutoff",
            'result.excluded_cross_window_intervals=',
            "if BOUNDARIES[record.status] then",
            "channel.weighted_sum/channel.covered_seconds",
            "channel.coverage_fraction=",
            'rate_source="host_ethernet_byte_counters"',
            "customer_wan_throughput_proven=false",
            "full_internet_availability_proven=false",
            "cross_reboot_continuity_proven=false",
            "hardware_resource_qualified=false",
        ):
            with self.subTest(required=required):
                self.assertIn(required, source)

    def test_stable_history_api_and_five_read_only_windows(self):
        text = SAMPLER.read_text()
        self.assertIn("function M.summary(state,window_seconds)", text)
        self.assertIn("function M.history_windows(state)", text)
        src = AGGREGATE.read_text()
        for preset in (
            '{"hour",3600}', '{"day",86400}',
            '{"week",7*86400}', '{"month",30*86400}',
            '{"ninety_days",90*86400}',
        ):
            with self.subTest(preset=preset):
                self.assertIn(preset, src)

    def test_no_firmware_image_growth_or_automatic_collection(self):
        self.assertTrue(AGGREGATE.is_file())
        self.assertFalse(
            (ROOT / "overlay/usr/lib/lua/8311/history_aggregate.lua").exists()
        )
        self.assertNotIn(
            "history_aggregate.lua", (ROOT / "MANIFEST.json").read_text()
        )
        code = "\n".join(
            line for line in AGGREGATE.read_text().splitlines()
            if not line.lstrip().startswith("--")
        )
        for forbidden in (
            "os.execute(", "io.open(", "io.popen(", "socket.",
            "fwenv_set", "uci:commit", "http.request",
            "setTimeout(", "setInterval(", "while true",
            "cron(", "sleep(", "/dev/mtd", "/usr/bin/pon",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, code)

    def test_true_coverage_gaps_and_provenance_in_fixture(self):
        code = FIXTURE.read_text()
        for required in (
            "no_partial_rate_interval_inference",
            "no_fabricated_boundary_average",
            "90days_not_claimed_as_available",
            "no_fake_tx_interval",
            "no_cross_missing_rate",
            "gap_stops_previous_segments",
            "no_cross_reboot_average",
            "no_cross_source_traffic",
            "aggregate_beyond_100_raw_export_limit",
            "five_window_no_fake_history",
            "invalid_pon_state_cannot_leak",
            "invalid_host_speed_cannot_leak",
        ):
            self.assertIn(required, code)


if __name__ == "__main__":
    unittest.main()
