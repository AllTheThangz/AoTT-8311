#!/usr/bin/env python3
"""Offline-only AoTT-8311 history CPU and memory budget experiment.

Runs ONLY synthetic mocked telemetry through the existing prototype on the
host Lua 5.1 interpreter and optionally the extracted vendor MIPS Lua under
QEMU. Never accepts a device target, SSH host, URL or arbitrary executable.
Results are host-process measurements, NOT real ONU resource qualification.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import shutil
import statistics
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "tests/h019_synthetic_benchmark.lua"
PROTOTYPE = ROOT / "prototypes/history"
PON_MODEL = ROOT / "overlay/usr/lib/lua/8311/effective_pon_state.lua"

SUMMARY = re.compile(
    r"^AOTT_H019_SYNTHETIC_BENCH_PASS "
    r"iterations=(\d+) cpu_seconds=([0-9.]+) "
    r"heap_retained_kib=([0-9.]+) heap_peak_kib=([0-9.]+) "
    r"reads=(\d+) commands=(\d+) samples=(\d+) events=(\d+)$",
)
RESOURCE = re.compile(
    r"^AOTT_BENCH_PROCESS_RSS_KIB=(\d+) WALL_SECONDS=([0-9.]+)$",
)
MODES = ("host_lua51", "vendor_mips_qemu")


def require(condition: bool, reason: str) -> None:
    if not condition:
        raise ValueError(reason)


def paths():
    for path in (SCRIPT, PON_MODEL, PROTOTYPE / "8311/history_sampler.lua",
                 PROTOTYPE / "8311/history_native_probe.lua",
                 PROTOTYPE / "8311/history_model.lua"):
        require(path.is_file() and not path.is_symlink(),
                "OFFLINE_SOURCE_MISSING_" + path.name)


def runtime(mode: str, vendor_rootfs: Path | None):
    require(mode in MODES, "UNKNOWN_SYNTHETIC_RUNTIME")
    if mode == "host_lua51":
        exe = shutil.which("lua5.1")
        require(exe is not None, "HOST_LUA51_UNAVAILABLE")
        return [exe]
    require(vendor_rootfs is not None, "OFFLINE_VENDOR_ROOTFS_REQUIRED")
    qemu = shutil.which("qemu-mips-static")
    require(qemu is not None, "MIPS_EMULATOR_UNAVAILABLE")
    require(vendor_rootfs.is_dir() and not vendor_rootfs.is_symlink(),
            "UNTRUSTED_VENDOR_DIRECTORY")
    exe = vendor_rootfs / "usr/bin/lua"
    require(exe.is_file() and not exe.is_symlink(),
            "OFFLINE_VENDOR_LUA_UNAVAILABLE")
    return [qemu, "-L", str(vendor_rootfs), str(exe)]


def run_one(mode: str, n: int, vendor_rootfs: Path | None) -> dict:
    require(100 <= n <= 20000, "ITERATIONS_OUT_OF_BOUNDS")
    paths()
    args = [*runtime(mode, vendor_rootfs), str(SCRIPT), str(PROTOTYPE),
            str(n), str(PON_MODEL)]
    gnu_time = Path("/usr/bin/time")
    if gnu_time.is_file():
        args = [str(gnu_time), "-f",
                "AOTT_BENCH_PROCESS_RSS_KIB=%M WALL_SECONDS=%e", *args]

    started = time.perf_counter()
    process = subprocess.run(args, capture_output=True, text=True,
                             check=False, timeout=90, cwd=str(ROOT))
    observed_wall = time.perf_counter() - started
    require(process.returncode == 0, "OFFLINE_BENCH_PROCESS_FAILED")
    lines = [line.strip() for line in process.stdout.splitlines()]
    matches = [m for line in lines if (m := SUMMARY.fullmatch(line))]
    require(len(matches) == 1, "OFFLINE_BENCH_SUMMARY_MISSING_OR_MULTIPLE")

    m = matches[0]
    i, lua_cpu_s, retained, peak_heap, reads, calls, samples, events = m.groups()
    require(int(i) == n and int(reads) == n * 5 and int(calls) == n * 2,
            "OFFLINE_NATIVE_READ_COUNT_MISMATCH")
    require(int(samples) == 120 and 0 <= int(events) <= 128,
            "OFFLINE_RAM_RING_UNBOUNDED")
    require(0 <= float(retained) < 256 and float(peak_heap) > 0,
            "OFFLINE_LUA_HEAP_BUDGET_EXCEEDED")

    resource_rows = [
        match for line in process.stderr.splitlines()
        if (match := RESOURCE.fullmatch(line.strip()))
    ]
    require(len(resource_rows) <= 1,
            "OFFLINE_PROCESS_RESOURCE_REPORT_AMBIGUOUS")
    result = {
        "mode": mode,
        "iterations": n,
        "source": "offline_mocked_observations_only",
        "device_queried": False,
        "native_command_executed": False,
        "firmware_modified": False,
        "internet_availability_measured": False,
        "lua_cpu_seconds": round(float(lua_cpu_s), 6),
        "lua_cpu_ms_per_synthetic_cycle": round(1000 * float(lua_cpu_s) / n, 6),
        "lua_heap_retained_kib": float(retained),
        "lua_heap_peak_observed_kib": float(peak_heap),
        "host_elapsed_wall_seconds": round(observed_wall, 4),
        "host_process_peak_rss_kib": (
            int(resource_rows[0].group(1)) if resource_rows else None
        ),
        "samples_retained": int(samples),
        "events_retained": int(events),
        "mock_kernel_reads": int(reads),
        "mock_native_invocations": int(calls),
    }
    return result


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--iterations", type=int, default=2500)
    parser.add_argument("--repeats", type=int, default=1)
    parser.add_argument("--vendor-rootfs", type=Path, default=None)
    args = parser.parse_args(argv)
    try:
        require(100 <= args.iterations <= 20000, "ITERATIONS_OUT_OF_BOUNDS")
        require(1 <= args.repeats <= 5, "REPEATS_OUT_OF_BOUNDS")
        modes = ["host_lua51"]
        if args.vendor_rootfs is not None:
            modes.append("vendor_mips_qemu")

        trials = [run_one(mode, args.iterations, args.vendor_rootfs)
                  for mode in modes for _ in range(args.repeats)]
        aggregated = {}
        for mode in modes:
            selected = [entry for entry in trials if entry["mode"] == mode]
            aggregated[mode] = {
                "runs": len(selected),
                "median_lua_cpu_ms_per_cycle": round(statistics.median(
                    entry["lua_cpu_ms_per_synthetic_cycle"]
                    for entry in selected), 6),
                "max_lua_heap_retained_kib": max(
                    entry["lua_heap_retained_kib"] for entry in selected),
                "max_host_process_rss_kib": max(
                    (entry["host_process_peak_rss_kib"] or 0)
                    for entry in selected) or None,
            }
        print(json.dumps({
            "schema": 1,
            "qualification": "OFFLINE_SIMULATED_ONLY",
            "on_device_cpu_ram_qualified": False,
            "live_wan_qualified": False,
            "rootfs_overlay_modified": False,
            "iterations_per_run": args.iterations,
            "runs": trials,
            "summary": aggregated,
        }, sort_keys=True))
    except (ValueError, subprocess.TimeoutExpired, OSError) as exc:
        # Never emit arbitrary stderr from a native process or a rootfs path.
        print("AOTT_H019_BENCH_FAIL:" + type(exc).__name__,
              file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
