#!/usr/bin/env python3
"""Build an evidence-linked, source-only AoTT-8311 capability registry.

The real LuCI configuration schema is the canonical source of exposed
field IDs and types. This tool does not redefine their permissible values.
It indexes code references and *names* of offline vendor UCI options
without reading live ONU state, private settings or credentials.

Discovery and code references never establish that a setting actually
applies, persists, survives a reboot or works on another board.
Never generate a verified hardware claim from static source evidence.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import sys

import audit_configurability as auditor


BOARD_PROFILE = "potron-prx126-aott-v1"
GUI_PATH = "overlay/usr/lib/lua/luci/controller/8311.lua"
COMMON_BACKEND = "overlay/usr/lib/lua/8311/config.lua"
HELPER_PATH = "overlay/lib/8311.sh"
ALLOWED_SOURCE_GROUPS = (
    "overlay/lib/",
    "overlay/etc/init.d/",
    "overlay/etc/uci-defaults/",
    "overlay/usr/sbin/",
    "overlay/usr/libexec/",
)
LITERAL_FW_GET = re.compile(
    r"""\bfwenv_get_8311\s+["']([A-Za-z0-9_]+)["']"""
)
# An unquoted name is a field ID, not an arbitrary shell argument.
UNQUOTED_FW_GET = re.compile(
    r"""\bfwenv_get_8311\s+([A-Za-z_][A-Za-z0-9_]*)\b"""
)
FUNCTION = re.compile(r"(?m)^(get_8311_[A-Za-z0-9_]+)\s*\(\)\s*\{")
HELPER_REF = re.compile(r"\b(?:get|set|_set)_8311_([A-Za-z0-9_]+)\b")
ENV_NAME = re.compile(r"\b8311_([A-Za-z][A-Za-z0-9_]*)\b")
GUI_ID = re.compile(r'^\s*id\s*=\s*"([A-Za-z0-9_]+)"')
MAX_SOURCE_FILE_BYTES = 524288
MAX_REFERENCES_PER_FIELD = 18

# The secret classification concerns the CATEGORY OF DATA, not its value.
# Never copy the value into any audit artifact.
SECRET_FIELDS = {"reg_id_hex", "lpwd", "root_pwhash"}
IDENTITY_FIELDS = {
    "gpon_sn", "vendor_id", "device_sn", "loid", "sfp_serial",
    "iphost_mac", "lct_mac", "sfp_oui", "iphost_hostname",
    "iphost_domain", "sfp_vendordata",
}
SERVICE_RISK = {
    "gpon_sn", "vendor_id", "device_sn", "reg_id_hex", "loid", "lpwd",
    "pon_mode", "omcc_version", "iop_mask", "mib_file", "pon_slot",
    "ipaddr", "netmask", "gateway", "lct_mac", "lct_vlan", "ping_ip",
    "internet_vlan", "services_vlan", "fix_vlans", "ethtool_speed",
    "tx_en_mode", "console_en", "uart_select", "rx_los",
    "dying_gasp_en", "bootdelay", "persist_root", "root_pwhash",
    "override_active", "override_commit",
}
# Only the U-Boot keys below are explicitly described as base environment
# by the existing GUI schema. Others use the 8311_ prefix on this board.
BASE_ENV_KEYS = {"bootdelay", "uart_select"}
# These are compatibility/fallback readers in lib/8311.sh, NOT new fields.
EXPLAINED_ALIASES = {
    "reg_id": {
        "field": "reg_id_hex",
        "relation": "legacy_fallback_read",
        "source": HELPER_PATH,
    },
    "sw_ver": {
        "field": "sw_verA/sw_verB",
        "relation": "generic_software_image_fallback",
        "source": HELPER_PATH,
    },
}
UPSTREAM_DOCUMENTED = {
    "factory_mode": "UPSTREAM_DOCUMENTED_BOARD_SUPPORT_UNVERIFIED",
}
SPECIAL_HELPERS = {
    "sw_verA": "sw_ver",
    "sw_verB": "sw_ver",
    "ethtool_speed": "ethtool",
    "ping_ip": "ping_host",
}
STATIC_STATUS = "DISCOVERED_NOT_HARDWARE_QUALIFIED"


def require(condition: bool, message: str) -> None:
    if not condition:
        raise auditor.AuditError(message)


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def classify(name: str) -> dict[str, str]:
    return {
        "sensitivity": (
            "secret" if name in SECRET_FIELDS else
            "potential_device_identity" if name in IDENTITY_FIELDS else
            "no_special_classification_yet"
        ),
        "risk": "service_or_recovery_risk" if name in SERVICE_RISK else "review_required",
    }


def safe_code_lines(root: Path):
    """Only inspect local source paths known to be platform consumers.

    Exclude GUI schemas, CSS, documentation, browser JS, fixtures, and
    generic configuration helpers. Cited lines are positions, never
    source text or subscriber values.
    """
    overlay = root / "overlay"
    require(overlay.is_dir() and not overlay.is_symlink(), "OVERLAY_MISSING")
    for path in sorted(overlay.rglob("*")):
        if not path.is_file() or path.is_symlink():
            continue
        name = path.relative_to(root).as_posix()
        if not any(name.startswith(prefix) for prefix in ALLOWED_SOURCE_GROUPS):
            continue
        if name in (COMMON_BACKEND, GUI_PATH):
            continue
        if path.suffix not in (".sh", ".lua", ".htm", ".js") and not (
            name.startswith("overlay/etc/init.d/") or
            name.startswith("overlay/etc/uci-defaults/") or
            name.startswith("overlay/lib/")
        ):
            continue
        require(path.stat().st_size <= MAX_SOURCE_FILE_BYTES,
                "SOURCE_FILE_TOO_LARGE_TO_INDEX_" + path.name)
        try:
            source = path.read_text()
        except UnicodeError:
            continue
        for lineno, line in enumerate(source.splitlines(), 1):
            stripped = line.lstrip()
            if stripped.startswith(("#", "--", "//", "/*", "*")):
                continue
            yield name, lineno, line


def literal_reads(root: Path) -> dict[str, list[dict]]:
    found: dict[str, list[dict]] = {}
    for path, lineno, line in safe_code_lines(root):
        matches = list(LITERAL_FW_GET.finditer(line))
        matches.extend(m for m in UNQUOTED_FW_GET.finditer(line)
                       if m.group(1) not in ("fwenv_get",))
        for match in matches:
            key = match.group(1)
            # No keys or values containing shell expansions/commands allowed.
            if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", key):
                continue
            item = {"path": path, "line": lineno,
                    "evidence": "literal_8311_environment_getter"}
            if item not in found.setdefault(key, []):
                found[key].append(item)
    return found


def source_references(root: Path, id_name: str,
                      helper_name: str) -> list[dict]:
    refs = []
    getter = re.compile(r"\bget_8311_" + re.escape(helper_name) + r"\b")
    setter = re.compile(r"\b(?:set|_set)_8311_" +
                        re.escape(helper_name) + r"\b")
    direct_env = re.compile(r"\b8311_" + re.escape(id_name) + r"\b")
    literal_read = re.compile(
        r"\bfwenv_get_8311\s+[\"']" + re.escape(id_name) + r"[\"']")
    for path, lineno, line in safe_code_lines(root):
        kinds = []
        if getter.search(line):
            kinds.append("backend_getter_definition" if
                         path == HELPER_PATH and
                         line.lstrip().startswith("get_8311_")
                         else "native_getter_reference")
        if setter.search(line):
            kinds.append("backend_setter_definition" if
                         path == HELPER_PATH and
                         line.lstrip().startswith("set_8311_")
                         else "native_setter_reference")
        if literal_read.search(line):
            kinds.append("literal_env_read_reference")
        if direct_env.search(line):
            kinds.append("prefixed_env_name_reference")
        if id_name in ("sw_verA", "sw_verB") and (
            re.search(r"\bget_8311_sw_ver\s+" +
                      id_name[-1] + r"\b", line) or
            re.search(r"\bset_8311_sw_ver\s+[\"']" +
                      id_name[-1] + r"[\"']", line)
        ):
            kinds.append("reported_firmware_image_variant_reference")
        if not kinds:
            continue
        # Multiple ref kinds on the same line are recorded as distinct
        # static reasons, not separate test passes.
        for kind in sorted(set(kinds)):
            refs.append({"path": path, "line": lineno,
                         "kind": kind})
    return refs[:MAX_REFERENCES_PER_FIELD]


def schema_locations(root: Path, names: set[str]) -> dict[str, int]:
    text = (root / GUI_PATH).read_text()
    in_schema = False
    category = None
    locations: dict[str, int] = {}
    for lineno, line in enumerate(text.splitlines(), 1):
        if "function fwenvs_8311()" in line:
            in_schema = True
            continue
        if in_schema and line.startswith("function action_pontop("):
            break
        if not in_schema or line.lstrip().startswith("--"):
            continue
        found = GUI_ID.match(line)
        if not found:
            continue
        key = found.group(1)
        if key in auditor.CATEGORY_IDS and line.count("\t") <= 3:
            category = key
            continue
        if category is None:
            continue
        require(key not in locations, "DUPLICATE_GUI_ID_LOCATION_" + key)
        locations[key] = lineno
    require(set(locations) == names,
            "GUI_SCHEMA_SOURCE_LOCATION_DRIFT")
    return locations


def qualified_source_support(name: str, refs: list[dict]) -> dict:
    # A source reference is never proof of a physical effect.
    return {
        "static_getter_found": any(r["kind"] in (
            "backend_getter_definition", "native_getter_reference",
            "literal_env_read_reference",
        ) for r in refs),
        "static_setter_found": any(r["kind"] in (
            "backend_setter_definition", "native_setter_reference"
        ) for r in refs),
        "startup_script_reference_found": any(
            r["path"].startswith(("overlay/etc/init.d/",
                                  "overlay/etc/uci-defaults/"))
            for r in refs),
        "runtime_effect_verified": False,
        "durable_write_hardware_verified": False,
        "effective_value_hardware_verified": False,
        "reboot_persistence_hardware_verified": False,
        "recovery_hardware_verified": False,
    }


def build(root: Path, vendor_rootfs: Path | None = None) -> dict:
    root, controller, config = auditor.safe_source(root)
    audit = auditor.inspect(root, vendor_rootfs)
    rows = audit["gui_fields"]
    ids = {row["id"] for row in rows}
    require(len(ids) == len(rows), "DUPLICATE_GUI_FIELD")
    locations = schema_locations(root, ids)
    discovered = literal_reads(root)
    require(len(discovered) > 0, "NO_LITERAL_ENV_BACKEND_READS")
    settings = []
    for row in rows:
        name = row["id"]
        helper = SPECIAL_HELPERS.get(name, name)
        refs = source_references(root, name, helper)
        settings.append({
            "id": name,
            "category": row["category"],
            "schema_type": row["schema_type"],
            "gui_source": {"path": GUI_PATH,
                           "line": locations[name]},
            "backend": {
                "kind": "uboot_environment" if name in BASE_ENV_KEYS
                        else "prefixed_8311_environment",
                "stored_key": name if name in BASE_ENV_KEYS
                              else "8311_" + name,
                "source_read_contract": "8311.config.snapshot",
                "source_validation_contract": "8311.config.validate",
                "source_preview_contract": "8311.config.prepare",
                "source_write_readback_contract": "8311.config.apply",
                "source_path": COMMON_BACKEND,
            },
            **classify(name),
            "static_native_references": refs,
            "static_source_checks": qualified_source_support(name, refs),
            "evidence_level": STATIC_STATUS,
            "enabled_on_additional_boards": False,
            "hardware_qualified": False,
        })
    missing = []
    for name in sorted(set(audit["known_hidden_fields"]) |
                       set(audit["upstream_documented_not_in_gui"]) |
                       (set(discovered) - ids - set(EXPLAINED_ALIASES))):
        if name in ids:
            continue
        reason = (
            "GUI_DISABLED_AS_BROKEN" if name in audit["known_hidden_fields"]
            else UPSTREAM_DOCUMENTED.get(name, "SOURCE_REFERENCED_NOT_IN_GUI")
        )
        refs = source_references(root, name, name)
        missing.append({
            "id": name, "status": "NOT_AVAILABLE_AS_VERIFIED_GUI_CONTROL",
            "reason": reason,
            "candidate_backend": "prefixed_8311_environment"
                                  if name in discovered else
                                  "unconfirmed_vendor_option",
            "source_getter_references": discovered.get(name, [])[:8],
            "static_native_references": refs,
            **classify(name),
            "exposed_gui_control": False,
            "hardware_qualified": False,
            "safe_to_enable_without_hardware_tests": False,
        })
    aliases = [
        {"id": key, "existing_schema_relation": EXPLAINED_ALIASES[key],
         "static_getter_references": discovered.get(key, [])[:8],
         "independent_control_proven": False}
        for key in sorted(set(EXPLAINED_ALIASES) & set(discovered))
    ]
    uci = []
    uci_domains = []
    for domain, record in sorted(audit["offline_vendor_uci_sections"].items()):
        uci_domains.append({
            "domain": domain,
            "section_types": record["section_types"],
            "option_name_count": record["option_count"],
            "evidence_level": "OFFLINE_VENDOR_SOURCE_NAMES_ONLY",
            "device_functional_support_qualified": False,
        })
        # The UCI file values are never opened here; audit reads only their
        # named section types and option tokens from an OFFLINE rootfs.
        for option in record["option_names"]:
            uci.append({
                "id": "uci:" + domain + ":" + option,
                "config_domain": domain,
                "option_name": option,
                "section_types": record["section_types"],
                "source_kind": "offline_vendor_uci_key",
                "evidence_level": "DISCOVERED_READ_ONLY_SOURCE_NAME",
                "editable": False,
                "runtime_backend_proven": False,
                "hardware_qualified": False,
            })
    require(len(settings) == audit["gui_fwenv_count"],
            "SCHEMA_INVENTORY_COUNT_MISMATCH")
    names={item["id"] for item in missing}
    require({"device_sn", "factory_mode", "tx_en_mode"} <= names,
            "KNOWN_GAP_NOT_INVENTORIED")
    require("lct_vlan" in ids and "lct_vlan" not in names,
            "MANAGEMENT_VLAN_MUST_BE_EXPOSED_NOT_HIDDEN")
    require({"reg_id", "sw_ver"} <= {x["id"] for x in aliases},
            "LEGACY_ENV_FALLBACK_NOT_CLASSIFIED")
    require(all(not row["hardware_qualified"] for row in settings+missing),
            "UNSUPPORTED_AUTOMATIC_HARDWARE_CLAIM")
    return {
        "schema": 1,
        "registry_kind": "SOURCE_DERIVED_SETTINGS_INVENTORY_ONLY",
        "source_profile": BOARD_PROFILE,
        "source_gui_sha256": sha(controller),
        "source_server_validator_sha256": sha(config),
        "upstream_aliases_must_not_count_as_extra_controls": aliases,
        "firmware_environment_gui_fields": settings,
        "missing_or_hidden_environment_candidates": missing,
        "offline_uci_domains": uci_domains,
        "offline_uci_option_candidates": uci,
        "summary": {
            "exposed_gui_environment_fields": len(settings),
            "by_gui_group": dict(Counter(x["category"] for x in settings)),
            "hidden_or_missing_candidates": len(missing),
            "legacy_aliased_keys": len(aliases),
            "vendor_uci_config_files": audit["offline_vendor_uci_config_count"],
            "vendor_uci_option_names": len(uci),
            "gui_fields_with_native_reference": sum(bool(x["static_native_references"])
                                                    for x in settings),
            "complete_A_to_Z_hardware_test_receipts": 0,
            "native_firmware_support_for_other_boards": 0,
        },
        "reliability_notice": (
            "Code references are paths/lines, not executed settings or a "
            "guarantee of actual device behavior. Settings and UCI options "
            "are not declared supported across hardware until independent "
            "read, effect, persistence and recovery evidence is provided."
        ),
        "contains_runtime_values_or_credentials": False,
        "source_only": True,
        "live_device_queried": False,
        "firmware_modified": False,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path,
                        default=Path(__file__).resolve().parents[1])
    parser.add_argument("--vendor-rootfs", type=Path,
                        help="Offline extracted vendor rootfs, NEVER the live device")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    registry = build(args.source_root, args.vendor_rootfs)
    if args.output is not None:
        root = args.source_root.resolve(strict=True)
        output = args.output
        require(output.is_absolute() and output.suffix == ".json",
                "OUTPUT_MUST_BE_ABSOLUTE_JSON")
        require(output.parent.resolve(strict=True) == root / "docs",
                "OUTPUT_MUST_BE_INSIDE_SOURCE_DOCS_DIRECTORY")
        require(not output.exists() and not output.is_symlink(),
                "REFUSE_TO_OVERWRITE_PREVIOUS_REGISTRY")
        data = (json.dumps(registry, indent=2, sort_keys=True) + "\n").encode()
        os.umask(0o077)
        fd = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL |
                     os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, "wb") as dest:
            dest.write(data)
            dest.flush()
            os.fsync(dest.fileno())
    print(json.dumps({
        "status": "CANONICAL_SOURCE_DERIVED_CAPABILITY_REGISTRY_PASS",
        "fields": registry["summary"]["exposed_gui_environment_fields"],
        "missing_candidates": [
            item["id"] for item in registry["missing_or_hidden_environment_candidates"]
        ],
        "aliases": [
            item["id"] for item in registry["upstream_aliases_must_not_count_as_extra_controls"]
        ],
        "uci_names": registry["summary"]["vendor_uci_option_names"],
        "consumer_reference_fields":
            registry["summary"]["gui_fields_with_native_reference"],
        "hardware_A_to_Z_verified": 0,
        "live_device_queried": False,
        "source_only": True,
        "output": str(args.output) if args.output else None,
    }, sort_keys=True))


if __name__ == "__main__":
    try:
        main()
    except (auditor.AuditError, OSError, ValueError, KeyError, TypeError) as exc:
        print("CAPABILITY_REGISTRY_STOP:" + str(exc)[:160], file=sys.stderr)
        raise SystemExit(1)
