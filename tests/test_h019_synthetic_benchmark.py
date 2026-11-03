"""H-019 offline-only benchmark safety and bounded resource tests.

Runs mock telemetry under host Lua and, when provided, offline vendor MIPS
Lua via QEMU. Never opens a production device or executes native PON tools.
"""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
RUNNER = ROOT / "tools/bench_h019_offline.py"
FIXTURE = ROOT / "tests/h019_synthetic_benchmark.lua"
VENDOR = Path(os.getenv("AOTT_VENDOR_ROOTFS", "/offline/vendor/unavailable"))


class H019SyntheticBenchmarkTests(unittest.TestCase):
    def run_bench(self, *arguments):
        return subprocess.run(
            [sys.executable, str(RUNNER), *arguments],
            cwd=ROOT, capture_output=True, text=True, timeout=45,
        )

    def assert_offline_report(self, report, iterations, vendor=False):
        self.assertEqual(report["qualification"], "OFFLINE_SIMULATED_ONLY")
        self.assertFalse(report["on_device_cpu_ram_qualified"])
        self.assertFalse(report["live_wan_qualified"])
        self.assertFalse(report["rootfs_overlay_modified"])
        self.assertEqual(report["iterations_per_run"], iterations)
        modes = ["host_lua51"] + (["vendor_mips_qemu"] if vendor else [])
        self.assertEqual([run["mode"] for run in report["runs"]], modes)
        for record in report["runs"]:
            self.assertFalse(record["device_queried"])
            self.assertFalse(record["firmware_modified"])
            self.assertFalse(record["native_command_executed"])
            self.assertFalse(record["internet_availability_measured"])
            self.assertEqual(record["mock_kernel_reads"], 5 * iterations)
            self.assertEqual(record["mock_native_invocations"], 2 * iterations)
            self.assertEqual(record["samples_retained"], 120)
            self.assertLessEqual(record["events_retained"], 128)
            self.assertGreaterEqual(record["lua_cpu_seconds"], 0)
            self.assertLess(record["lua_heap_retained_kib"], 256)
            self.assertGreater(record["host_elapsed_wall_seconds"], 0)
            self.assertIn(record["source"], ["offline_mocked_observations_only"])

    def test_200_synthetic_iterations_on_host(self):
        if not shutil.which("lua5.1"):
            self.skipTest("Lua 5.1 unavailable on host")
        result = self.run_bench("--iterations", "200")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assert_offline_report(json.loads(result.stdout), 200)

    def test_optional_vendor_mips_benchmark(self):
        if not os.getenv("AOTT_VENDOR_ROOTFS"):
            self.skipTest("No extracted offline MIPS vendor rootfs")
        result = self.run_bench("--iterations", "200",
                                "--vendor-rootfs", str(VENDOR))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assert_offline_report(json.loads(result.stdout), 200, vendor=True)

    def test_invalid_benchmark_parameters_rejected(self):
        for args in (
            ("--iterations", "0"),
            ("--iterations", "99"),
            ("--iterations", "20001"),
            ("--iterations", "-1"),
            ("--iterations", "inf"),
            ("--repeats", "0"),
            ("--repeats", "6"),
            ("--no-such-option", "customer"),
        ):
            with self.subTest(args=args):
                result = self.run_bench(*args)
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse(result.stdout.strip())

    def test_lua_source_parses(self):
        if not shutil.which("luac5.1"):
            self.skipTest("Host Lua compiler unavailable")
        result = subprocess.run(
            ["luac5.1", "-p", str(FIXTURE)],
            capture_output=True, text=True, timeout=10,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_no_live_device_target_or_firmware_changes(self):
        source = RUNNER.read_text()
        self.assertIn("OFFLINE_SIMULATED_ONLY", source)
        self.assertIn("mock_native_invocations", source)
        self.assertIn("host_process_peak_rss_kib", source)
        self.assertIn('"on_device_cpu_ram_qualified": False', source)
        executable = "\n".join(line for line in source.splitlines()
                               if line.strip() and not line.lstrip().startswith(("#", '"""', "Runs", "host Lua", "QEMU.", "Results")))
        for pattern in ("ssh ", "scp ", "paramiko", "urllib",
                        "socket.", "requests."):
            self.assertNotIn(pattern, executable.lower())
        # Local offline Lua fixture is the only subprocess launch.
        self.assertIn("subprocess.run(", source)
        self.assertIn("capture_output=True", source)
        self.assertNotIn("shell=True", source)
        self.assertNotIn("firmware_upgrade", source.lower())
        self.assertFalse((ROOT / "overlay/usr/lib/lua/8311/h019_synthetic_benchmark.lua").exists())
        self.assertNotIn("h019_synthetic_benchmark.lua",
                         (ROOT / "MANIFEST.json").read_text())


if __name__ == "__main__":
    unittest.main()
