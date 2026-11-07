#!/usr/bin/env python3
"""Read-only PRX126 boot/storage audit of an explicitly supplied extracted rootfs.

Never executes an init script, reads configuration values, uses SSH, or claims
that a reference filesystem describes the currently running physical device.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import stat

MAX_SOURCE_BYTES = 131072


def source(root: Path, relative: str) -> tuple[str, dict]:
    path = root / relative
    info = {"path": relative, "available": False}
    try:
        st = path.lstat()
    except FileNotFoundError:
        return "", info
    if not stat.S_ISREG(st.st_mode) or st.st_size > MAX_SOURCE_BYTES:
        return "", {**info, "refused_type_or_size": True}
    raw = path.read_bytes()
    if len(raw) != st.st_size:
        raise ValueError("Reference source changed during read")
    info.update(available=True, sha256=hashlib.sha256(raw).hexdigest(), bytes=len(raw))
    return raw.decode("utf-8", errors="strict"), info


def line_of(text: str, token: str) -> list[int]:
    return [i for i, line in enumerate(text.splitlines(), 1) if token in line]


def shell_function(text: str, name: str) -> str:
    match = re.search(r"(?ms)^" + re.escape(name) + r"\(\) \{\n.*?^\}", text)
    return match.group() if match else ""


def backend_noop(text: str, name: str) -> bool:
    function = shell_function(text, name)
    if not function:
        return False
    lines = [line.strip() for line in function.splitlines()[1:-1]
             if line.strip() and not line.lstrip().startswith("#")]
    return lines == ["return 0"]


def audit(repository: Path, vendor: Path) -> dict:
    repository, vendor = repository.resolve(strict=True), vendor.resolve(strict=True)
    selected = {
        "boot": (vendor, "etc/init.d/boot"),
        "network": (vendor, "etc/init.d/network"),
        "uhttpd": (vendor, "etc/init.d/uhttpd"),
        "rc_common": (vendor, "etc/rc.common"),
        "procd": (vendor, "lib/functions/procd.sh"),
        "capture": (repository, "overlay/etc/init.d/8311-config-state"),
        "sysinit": (repository, "overlay/etc/init.d/_8311-sysinit.sh"),
        "netinit": (repository, "overlay/etc/init.d/_8311-netinit.sh"),
        "backend": (repository, "overlay/lib/8311_backend.sh"),
        "base_library": (repository, "overlay/lib/8311.sh"),
        "uci_defaults": (repository, "overlay/etc/uci-defaults/zzz-8311"),
    }
    texts, files, starts = {}, {}, {}
    for key, (root, relative) in selected.items():
        text, info = source(root, relative)
        info["source_kind"] = "private_extracted_reference" if root == vendor else "repository_source"
        texts[key], files[key] = text, info
        match = re.search(r"^START=(\d+)\s*$", text, flags=re.MULTILINE)
        if match:
            starts[key] = int(match.group(1))
    try:
        var_target = os.readlink(vendor / "var")
    except OSError:
        var_target = None
    # Emit only a known generic relationship, never arbitrary symlink targets.
    var_is_tmp = var_target in ("tmp", "/tmp", "../tmp")
    facts = {
        "var_is_tmp_symlink": var_is_tmp,
        "boot_executes_uci_defaults": "uci_apply_defaults" in texts["boot"],
        "defaults_configure_management": "network.lct" in texts["uci_defaults"],
        "persistence_flag_controls_rootfs_data": all(x in texts["base_library"] for x in
            ('fwenv_get_8311 "persist_root"', "ubi remove rootfs_data")),
        "netinit_calls_management_setters_and_ifup": all(x in texts["netinit"] for x in
            ("set_8311_ipaddr", 'ifup "lct"')),
        "backend_management_setters_are_noops": all(backend_noop(texts["backend"], name) for name in
            ("_set_8311_ipaddr", "_set_8311_netmask", "_set_8311_gateway", "_set_8311_lct_mac")),
        "management_value_getters_are_cached": all('/tmp/8311-' in shell_function(texts["base_library"], name)
            for name in ("get_8311_ipaddr", "get_8311_netmask", "get_8311_gateway", "get_8311_dns_server", "get_8311_lct_mac")),
        "management_vlan_getter_is_uncached": bool(shell_function(texts["base_library"], "get_8311_lct_vlan")) and
            '/tmp/' not in shell_function(texts["base_library"], "get_8311_lct_vlan"),
        "empty_dns_defaults_only_skip_assignment": '[ -n "$LCT_DNS" ] && uci set "network.lct.dns"="$LCT_DNS"' in texts["uci_defaults"] and
            not re.search(r'uci\s+(?:-q\s+)?(?:del|delete)\s+["\']?network\.(?:lct|mgmt)\.dns', texts["uci_defaults"]),
        "procd_supports_command_respawn_limits": all(x in texts["procd"] for x in
            ("respawn", "limits", "term_timeout", "procd_set_param")),
    }
    before_snapshot = bool(facts["boot_executes_uci_defaults"] and
        starts.get("boot", 999) < starts.get("capture", -1))
    risks = []
    if var_is_tmp:
        risks.append({"code": "VAR_TMP_NOT_DURABLE_BY_REFERENCE_LAYOUT", "blocking": True,
                      "evidence": {"path": "var", "relationship": "symlink_to_tmp"}})
    if facts["persistence_flag_controls_rootfs_data"]:
        risks.append({"code": "ROOT_OVERLAY_MAY_BE_DISCARDED_AT_BOOT", "blocking": True,
                      "evidence": {"source": "base_library", "lines": line_of(texts["base_library"], "ubi remove rootfs_data")}})
    if before_snapshot:
        risks.append({"code": "DEFAULTS_MUTATE_BEFORE_CURRENT_CONFIG_SNAPSHOT", "blocking": True,
                      "evidence": {"boot_start": starts["boot"], "snapshot_start": starts["capture"]}})
    if facts["management_value_getters_are_cached"]:
        risks.append({"code": "BOOT_CACHES_CAN_MASK_SAVED_ENVIRONMENT_CHANGES", "blocking": True,
                      "evidence": {"source": "base_library", "lines": line_of(texts["base_library"], "get_8311_ipaddr()")}})
    if facts["netinit_calls_management_setters_and_ifup"]:
        risks.append({"code": "LATE_INTERFACE_ACTIVATION_REQUIRES_REVALIDATION", "blocking": True,
                      "evidence": {"source": "netinit", "lines": line_of(texts["netinit"], 'ifup "lct"'),
                                   "backend_management_uci_writes": "none_in_qualified_functions" if facts["backend_management_setters_are_noops"] else "unclassified"}})
    if facts["empty_dns_defaults_only_skip_assignment"]:
        risks.append({"code": "EMPTY_DNS_SOURCE_DOES_NOT_DELETE_EXISTING_UCI_DNS", "blocking": True,
                      "evidence": {"source": "uci_defaults", "lines": line_of(texts["uci_defaults"], '[ -n "$LCT_DNS" ]')}})
    config_names = []
    config = vendor / "etc/config"
    if config.is_dir() and not config.is_symlink():
        for path in sorted(config.iterdir()):
            if re.fullmatch(r"[A-Za-z0-9_-]{1,48}", path.name):
                st = path.lstat()
                config_names.append({"name": path.name, "regular_file": stat.S_ISREG(st.st_mode),
                                     "mode": oct(stat.S_IMODE(st.st_mode))})
    return {
        "schema": 2, "basis": "EXTRACTED_REFERENCE_AND_SOURCE_ONLY",
        "live_device_examined": False, "config_values_read": False,
        "init_scripts_executed": False, "bank_selector_read": False,
        "source_files": files, "startup_priorities": starts,
        "reference_facts": facts, "blockers": risks, "config_inventory": config_names,
        "production_activation_allowed": False,
        "required_live_evidence": ["active_committed_bank_and_exact_build_hashes",
            "actual_mounts_readonly_flags_free_space_and_mount_order",
            "persistent_root_mode_and_environment_consumer_precedence",
            "management_interface_host_vlan_recovery_access",
            "pon_host_link_and_router_side_connectivity_baseline"],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("repository", type=Path)
    parser.add_argument("vendor_rootfs", type=Path)
    args = parser.parse_args()
    try:
        report = audit(args.repository, args.vendor_rootfs)
    except (OSError, ValueError, UnicodeError):
        raise SystemExit("Reference audit refused missing, unsafe, or changing input") from None
    print(json.dumps(report, sort_keys=True, indent=2))


if __name__ == "__main__":
    main()
