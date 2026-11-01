#!/usr/bin/env python3
"""Static release guard for the existing inactive-bank-only installer.

Checks source control flow and flag handling without invoking any shell,
firmware writer, boot control, UBI helper, SSH command, or device.
This is not a substitute for a complete isolated execution or live trial.
"""
from pathlib import Path
import argparse
import json
import re

EXPECTED = (
    ("default_stage_only", "INSTALL=false VALIDATE=false YES=false TRIAL=false NO_COMMIT=true REBOOT=false TAR="),
    ("explicit_trial_flag", "--trial) TRIAL=true; NO_COMMIT=true ;;"),
    ("explicit_no_commit_alias", "--no-commit) NO_COMMIT=true ;;"),
    ("explicit_reboot_flag", "-r|--reboot) REBOOT=true ;;"),
    ("reboot_requires_explicit_trial", "if $REBOOT && { ! $INSTALL || ! $TRIAL; }; then"),
    ("live_bank_equals_commit", '[ "$ACTIVE" = "$COMMITTED" ] || fail'),
    ("one_shot_pending_rejected", '[ -z "$ACTIVATE" ] || fail "A one-shot boot is pending;'),
    ("inactive_bank_selected", "if [ \"$ACTIVE\" = A ]; then INSTALL_BANK=B; else INSTALL_BANK=A; fi"),
    ("live_bank_checked", 'check_bank "$ACTIVE"'),
    ("write_targets_not_live", '[ "$DEVICE" != "$KERNEL_UBI" ] && [ "$DEVICE" != "$BOOTCORE_UBI" ] && [ "$DEVICE" != "$ROOTFS_UBI" ]'),
    ("recheck_before_first_mutation", '[ "$ACTIVE" = "$OLD_ACTIVE" ] && [ "$COMMITTED" = "$ACTIVE" ] && [ -z "$ACTIVATE" ]'),
    ("incomplete_receipt_first", 'persist_receipt "$INSTALL_BANK" incomplete'),
    ("invalidate_target_before_write", 'set_environment "img_valid$INSTALL_BANK" false'),
    ("one_flash_writer", 'ubiupdatevol -s "$size" "$device" - < "$WORKDIR/$file"'),
    ("hash_flash_readback", 'actual=$(checked_stream_sha "$size" "$device")'),
    ("compare_flash_hash", '[ "$actual" = "$expected" ] || fail "Readback mismatch: $file; inactive bank remains incomplete."'),
    ("verify_mounted_candidate", 'qualify_rootfs "$INSTALL_BANK" candidate'),
    ("complete_receipt_after_verify", 'persist_receipt "$INSTALL_BANK" complete'),
    ("enable_target_after_verify", 'set_environment "img_valid$INSTALL_BANK" true'),
    ("trial_selection_opt_in", "if $TRIAL; then"),
    ("reboot_opt_in", "if $REBOOT; then"),
    ("profile_path_override", 'MAINT_LIBDIR=${MAINT8311_LIBDIR:-"$SCRIPT_DIR/../../lib"}'),
)

ORDERED = (
    "live_bank_checked",
    "incomplete_receipt_first",
    "invalidate_target_before_write",
    "one_flash_writer",
    "hash_flash_readback",
    "compare_flash_hash",
    "verify_mounted_candidate",
    "complete_receipt_after_verify",
    "enable_target_after_verify",
    "trial_selection_opt_in",
    "reboot_opt_in",
)


def inspect(data: str) -> dict:
    """Fail closed on source drift and unexpected write/commit paths."""
    checks = {}
    positions = {}
    for label, exact in EXPECTED:
        occurrences = data.count(exact)
        checks[label] = occurrences == 1
        if occurrences == 1:
            positions[label] = data.index(exact)
    checks["ordered_transitions"] = all(
        a in positions and b in positions and positions[a] < positions[b]
        for a, b in zip(ORDERED, ORDERED[1:])
    )
    checks["one_ubiupdatevol"] = len(re.findall(r"(?m)^\s*ubiupdatevol\b", data)) == 1
    checks["no_commit_bank_write"] = not re.search(
        r"(?m)^\s*set_environment\s+commit_bank\b", data)
    checks["no_direct_bootloader_update"] = not re.search(
        r"(?m)^\s*(?:fw_setenv|flash_erase|nandwrite)\b", data)
    checks["no_extra_reboot_call"] = len(re.findall(
        r"(?m)^\s*(?:reboot|shutdown|poweroff)\b", data)) == 0
    checks["isolated_reboot_call"] = data.count(
        '"$MAINT_BINDIR/8311-bankctl.sh" reboot') == 1
    checks["no_automatic_stage_trial"] = (
        "TRIAL=false" in data and
        'set_environment img_activate "$INSTALL_BANK"' in data and
        positions.get("trial_selection_opt_in", 10**9) <
        data.find('set_environment img_activate "$INSTALL_BANK"') <
        positions.get("reboot_opt_in", -1)
    )
    return {
        "schema": 1,
        "status": "SOURCE_STAGE_ONLY_CONTRACT_PASS" if all(checks.values())
                  else "SOURCE_STAGE_ONLY_CONTRACT_REJECTED",
        "checks": checks,
        "passed": sum(checks.values()),
        "total": len(checks),
        "device_operations_performed": False,
        "runtime_execution_performed": False,
        "hardware_qualified": False,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("installer", type=Path)
    args = parser.parse_args()
    source = args.installer
    if source.is_symlink() or not source.is_file() or source.stat().st_size > 131072:
        parser.error("Must be a bounded regular text installer")
    data = source.read_text(encoding="utf-8")
    report = inspect(data)
    print(json.dumps(report, indent=2, sort_keys=True))
    raise SystemExit(0 if report["status"] == "SOURCE_STAGE_ONLY_CONTRACT_PASS" else 1)


if __name__ == "__main__":
    main()
