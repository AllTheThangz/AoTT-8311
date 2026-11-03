#!/usr/bin/env python3
"""H-025 offline ABI preflight against an already extracted firmware rootfs.

Checks only local file metadata and ELF machine IDs. Never executes PON,
ethtool, firmware or network commands, never opens /proc or a device.
A passing result is NOT approval to start a collector on real hardware.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import stat
import sys

REQUIRED_MIPS = (
    "usr/bin/pon", "usr/sbin/ethtool", "usr/bin/lua",
    "usr/lib/lua/nixio.so", "bin/busybox",
)
TIMEOUT_SYMLINK = "usr/bin/timeout"
TIMEOUT_TARGET = "../../bin/busybox"


def inspect_elf(path: Path):
    with path.open("rb") as fd:
        hdr = fd.read(20)
    if len(hdr) < 20 or hdr[:4] != b"\x7fELF":
        return False, "not_elf"
    if hdr[4] != 1:
        return False, "not_elf32"
    if hdr[5] != 2:
        return False, "not_big_endian"
    if int.from_bytes(hdr[18:20], "big") != 8:
        return False, "not_mips"
    return True, "mips32_be"


def preflight(root: Path) -> dict:
    if not root.is_dir() or root.is_symlink():
        raise ValueError("untrusted_offline_rootfs")
    reference = root.resolve()
    observed = []
    issues = []
    for relative in REQUIRED_MIPS:
        file = reference / relative
        if file.is_symlink() or not file.is_file():
            issues.append(relative.replace("/", "_") + "_missing_or_symlink")
            continue
        if file.stat().st_size == 0 or file.stat().st_size > 16_000_000:
            issues.append(relative.replace("/", "_") + "_unreasonable_size")
            continue
        if relative != "usr/lib/lua/nixio.so" and not (
            file.stat().st_mode & stat.S_IXUSR):
            issues.append(relative.replace("/", "_") + "_not_executable")
            continue
        compatible, status = inspect_elf(file)
        if not compatible:
            issues.append(relative.replace("/", "_") + "_" + status)
        observed.append({
            "relative_path": relative,
            "elf_abi": status,
            "elf_abi_check_passed": compatible,
        })
    timeout = reference / TIMEOUT_SYMLINK
    if not timeout.is_symlink() or os.readlink(timeout) != TIMEOUT_TARGET:
        issues.append("timeout_busybox_link_unexpected")
    else:
        target = (timeout.parent / os.readlink(timeout)).resolve()
        if target != (reference / "bin/busybox").resolve() or (
                not target.is_relative_to(reference)):
            issues.append("timeout_symlink_escapes_reference")
    return {
        "schema": 1,
        "scope": "h025_offline_extracted_vendor_binary_abi_only",
        "reference_abi": "mips32_big_endian",
        "all_required_binary_checks_passed": not issues,
        "issues": sorted(issues),
        "binary_checks": observed,
        "tested_kernel_driver": False,
        "executed_native_pon_or_ethtool": False,
        "queried_any_live_device": False,
        "approved_oni_management_target": False,
        "hardware_qualified": False,
        "production_activation_approved": False,
        "pon_olt_internet_proven": False,
        "actual_memory_cpu_thermal_measured": False,
        "firmware_modified": False,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--vendor-rootfs", type=Path, required=True)
    opts = parser.parse_args(argv)
    try:
        result = preflight(opts.vendor_rootfs)
    except (OSError, ValueError) as err:
        print(json.dumps({
            "schema": 1, "offline_abi_status": "invalid_reference",
            "error": str(err)[:100],
            "hardware_qualified": False,
            "production_activation_approved": False,
        }, sort_keys=True))
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0 if result["all_required_binary_checks_passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
