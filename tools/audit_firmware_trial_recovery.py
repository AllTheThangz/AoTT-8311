#!/usr/bin/env python3
"""Offline, read-only admission for PRX126 firmware-trial rollback components.

Checks extracted candidate rootfs, never contacts an ONU or changes a bank.
Static presence and path checks are not evidence of power-loss or boot success.
"""
import argparse
import json
import os
from pathlib import Path
import re
import stat
import sys

FILES = {
    "usr/libexec/8311-firmware-trial-watchdog": 0o755,
    "usr/libexec/8311-firmware-trial-confirm": 0o755,
    "usr/lib/lua/8311/firmware_trial_watchdog.lua": 0o644,
    "etc/init.d/_8311-sysinit.sh": 0o755,
    "usr/sbin/8311-bankctl.sh": 0o755,
}

class AdmissionError(ValueError):
    pass

def safe(root, relative, mode):
    root = Path(root).resolve(strict=True)
    if not root.is_dir():
        raise AdmissionError("invalid_offline_rootfs")
    candidate = root
    for segment in Path(relative).parts:
        candidate /= segment
        if candidate.is_symlink():
            raise AdmissionError("symlink_in_recovery_path")
    if not candidate.is_file():
        raise AdmissionError("required_recovery_component_absent")
    file_stat = candidate.stat()
    if (not stat.S_ISREG(file_stat.st_mode)
            or stat.S_IMODE(file_stat.st_mode) != mode
            or file_stat.st_size < 30
            or file_stat.st_size > 200000):
        raise AdmissionError("unsafe_recovery_component_mode_or_size")
    text = candidate.read_bytes()
    if b"\0" in text:
        raise AdmissionError("binary_recovery_component")
    try:
        return text.decode("utf-8")
    except UnicodeDecodeError as error:
        raise AdmissionError("non_utf8_recovery_source") from error

def verify(rootfs):
    contents = {name: safe(rootfs,name,mode) for name,mode in FILES.items()}
    watchdog = contents["usr/lib/lua/8311/firmware_trial_watchdog.lua"]
    hook = contents["etc/init.d/_8311-sysinit.sh"]
    bankctl = contents["usr/sbin/8311-bankctl.sh"]
    launcher = contents["usr/libexec/8311-firmware-trial-watchdog"]
    confirm = contents["usr/libexec/8311-firmware-trial-confirm"]
    required = (
        'local WAIT_SECONDS=180',
        'local STEP_SECONDS=2',
        'function M.run(provider,wait_seconds)',
        '{"/usr/sbin/8311-bankctl.sh","rollback"}',
        'provider.monotonic()',
        'provider.read_confirmed()',
        'provider.rollback()',
        'FIRMWARE_TRIAL_WATCHDOG_ROLLBACK_REQUESTED',
    )
    if any(item not in watchdog for item in required):
        raise AdmissionError("missing_local_watchdog_contract")
    if re.search(r"(?i)\b(curl|wget|nslookup|ping|ssh)\b", watchdog):
        raise AdmissionError("network_dependent_watchdog")
    if ('-x /usr/bin/lua -- /usr/libexec/8311-firmware-trial-watchdog' not in hook
            or 'start "$@"' not in hook
            or hook.index('start "$@"') >
            hook.index('/usr/libexec/8311-firmware-trial-watchdog')):
        raise AdmissionError("missing_boot_watchdog_admission")
    if ('require "8311.firmware_trial_watchdog"' not in launcher
            or 'watchdog.run()' not in launcher
            or 'require "8311.firmware_trial_watchdog"' not in confirm
            or 'watchdog.confirm()' not in confirm):
        raise AdmissionError("missing_fixed_watchdog_launcher")
    if ('rollback|reboot)' not in bankctl
            or 'if [ "$COMMAND" = rollback ]; then TARGET=$COMMITTED' not in bankctl
            or 'check_bank "$TARGET"' not in bankctl
            or 'reboot ||' not in bankctl):
        raise AdmissionError("bankctl_committed_recovery_contract_missing")
    return {
        "status": "OFFLINE_FIRMWARE_TRIAL_RECOVERY_STRUCTURE_PASS",
        "components": len(FILES),
        "trial_timeout_seconds": 180,
        "watchdog_requires_network": False,
        "boot_hook_present": True,
        "committed_bank_reboot_path_present": True,
        "hardware_rollback_qualified": False,
        "power_loss_qualified": False,
        "safe_for_live_install": False,
    }

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rootfs",required=True,
                        help="Existing private extracted rootfs; read-only")
    args=parser.parse_args()
    try:
        print(json.dumps(verify(args.rootfs),sort_keys=True,indent=2))
    except (AdmissionError,OSError) as err:
        parser.exit(2,"Offline watchdog admission denied: "+
                    type(err).__name__+"\n")
if __name__=="__main__":
    main()
