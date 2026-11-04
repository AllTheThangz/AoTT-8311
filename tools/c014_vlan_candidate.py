"""C-014 staged management-VLAN candidate. Offline only, no live adapter.

Parses bounded native UCI exports, plans an ownership-scoped transition,
and checks every operation on a disposable adapter. Never reloads services,
changes a boot environment, or promotes candidate files to a live device.
"""
import copy
import hashlib
import ipaddress
import json
import re
import shlex

OWNER = "aott_c014_v1"
IDENT = re.compile(r"^[A-Za-z0-9_]{1,48}$")
ADDRESS = ("ipaddr", "netmask", "gateway", "dns")
LCT_OPTIONS = set(ADDRESS) | {"ifname", "proto", "auto", "macaddr"}


class VlanCandidateError(ValueError):
    """Fixed codes only; never include configuration values in errors."""


def parse_export(text, package):
    if type(text) is not str or len(text.encode()) > 65536:
        raise VlanCandidateError("export_size_invalid")
    sections, counts, current = {}, {}, None
    header = False
    for line in text.splitlines():
        try:
            parts = shlex.split(line, comments=True)
        except ValueError:
            raise VlanCandidateError("export_syntax_invalid") from None
        if not parts:
            continue
        if any(any(ord(c) < 32 or ord(c) == 127 for c in p) for p in parts):
            raise VlanCandidateError("export_control_character")
        kind = parts[0]
        if kind == "package" and len(parts) == 2 and not header and not sections:
            if parts[1] != package:
                raise VlanCandidateError("export_package_mismatch")
            header = True
        elif kind == "config" and len(parts) in (2, 3) and header:
            stype = parts[1]
            if not IDENT.fullmatch(stype):
                raise VlanCandidateError("export_section_type_invalid")
            index = counts.get(stype, 0)
            counts[stype] = index + 1
            name = parts[2] if len(parts) == 3 else f"@{stype}[{index}]"
            if len(parts) == 3 and not IDENT.fullmatch(name):
                raise VlanCandidateError("export_section_name_invalid")
            if name in sections or len(sections) >= 128:
                raise VlanCandidateError("duplicate_or_excess_sections")
            current = {"type": stype, "options": {}}
            sections[name] = current
        elif kind in ("option", "list") and len(parts) == 3 and current is not None:
            key, value = parts[1:]
            if not IDENT.fullmatch(key) or len(value) > 2048:
                raise VlanCandidateError("export_option_invalid")
            opts = current["options"]
            if kind == "option":
                if key in opts:
                    raise VlanCandidateError("duplicate_export_option")
                opts[key] = value
            else:
                if key in opts and not isinstance(opts[key], list):
                    raise VlanCandidateError("mixed_scalar_and_list")
                opts.setdefault(key, []).append(value)
                if len(opts[key]) > 64:
                    raise VlanCandidateError("export_list_too_long")
        else:
            raise VlanCandidateError("unsupported_export_record")
    if not header:
        raise VlanCandidateError("export_header_missing")
    return sections


def revision(snapshot):
    raw = json.dumps(snapshot, sort_keys=True, separators=(",", ":"), allow_nan=False)
    if len(raw) > 131072:
        raise VlanCandidateError("snapshot_too_large")
    return hashlib.sha256(raw.encode()).hexdigest()


def _members(section):
    value = section["options"].get("network", [])
    if not isinstance(value, (str, list)):
        raise VlanCandidateError("ambiguous_zone_membership")
    values = value if isinstance(value, list) else value.split()
    if any(type(v) is not str for v in values):
        raise VlanCandidateError("ambiguous_zone_membership")
    if isinstance(value, str) and value != " ".join(values):
        raise VlanCandidateError("noncanonical_zone_membership")
    if len(set(values)) != len(values) or any(not IDENT.fullmatch(v) for v in values):
        raise VlanCandidateError("ambiguous_zone_membership")
    return values


def _replace_members(zone, values):
    original = zone["options"].get("network", [])
    zone["options"]["network"] = values if isinstance(original, list) else " ".join(values)


def _address_check(opts):
    try:
        ip = ipaddress.IPv4Address(opts["ipaddr"])
        ipaddress.IPv4Network(str(ip) + "/" + opts["netmask"], strict=False)
        if ip.is_unspecified or ip.is_multicast or ip.is_loopback:
            raise ValueError()
        if opts.get("gateway"):
            ipaddress.IPv4Address(opts["gateway"])
    except (KeyError, ValueError, TypeError):
        raise VlanCandidateError("management_ipv4_profile_unqualified") from None
    # Preserve a legacy self-address gateway and exact DNS representation.
    # This check does not assert that either is reachable or correct on-device.


def plan_transition(snapshot, vlan, expected_revision, parent, zone_name):
    """Return private candidate data and argv operations; no host/device I/O."""
    if type(snapshot) is not dict or set(snapshot) != {"network", "firewall"}:
        raise VlanCandidateError("snapshot_packages_invalid")
    if revision(snapshot) != expected_revision:
        raise VlanCandidateError("stale_source_revision")
    if type(vlan) is not int or not 0 <= vlan <= 4094:
        raise VlanCandidateError("vlan_not_explicitly_supported")
    if type(parent) is not str or not re.fullmatch(r"[A-Za-z0-9_]{1,32}", parent):
        raise VlanCandidateError("parent_unqualified")
    if type(zone_name) is not str or not IDENT.fullmatch(zone_name) or zone_name == "wan":
        raise VlanCandidateError("trusted_zone_unqualified")
    desired = copy.deepcopy(snapshot)
    network, firewall = desired["network"], desired["firewall"]
    lct = network.get("lct", {})
    opts = lct.get("options", {})
    if (lct.get("type") != "interface" or opts.get("ifname") != parent or
            opts.get("proto") != "static" or set(opts) - LCT_OPTIONS):
        raise VlanCandidateError("lct_profile_unqualified")
    if any(name.startswith("@interface[") for name in network):
        raise VlanCandidateError("anonymous_network_interface_unqualified")
    owned = "mgmt" in network or "lct_vlan" in network
    if owned:
        mgmt, device = network.get("mgmt", {}), network.get("lct_vlan", {})
        mo, do = mgmt.get("options", {}), device.get("options", {})
        if (mgmt.get("type") != "interface" or device.get("type") != "device" or
                mo.get("aott_owner") != OWNER or do.get("aott_owner") != OWNER or
                mo.get("ifname") != "mgmt" or mo.get("proto") != "static" or
                do.get("ifname") != parent or do.get("name") != "mgmt" or
                do.get("type") != "8021q" or
                set(mo) - (LCT_OPTIONS | {"aott_owner"}) or
                set(do) != {"aott_owner", "ifname", "name", "type", "vid"} or
                not str(do.get("vid", "")).isdigit() or
                not 1 <= int(do["vid"]) <= 4094 or
                any(k in opts for k in ADDRESS)):
            raise VlanCandidateError("legacy_or_foreign_interface_ownership")
        if mo.get("macaddr") != opts.get("macaddr"):
            raise VlanCandidateError("management_mac_profile_mismatch")
        source = mo
    else:
        source = opts
    _address_check(source)
    for name, section in network.items():
        if name not in ("lct", "mgmt", "lct_vlan"):
            for key in ("ifname", "device", "interface", "name"):
                value = section["options"].get(key, [])
                values = value if isinstance(value, list) else value.split()
                if "mgmt" in values or "lct_vlan" in values:
                    raise VlanCandidateError("foreign_management_reference")
    zones = [(name, s) for name, s in firewall.items() if s["type"] == "zone"]
    matches = [(name, s) for name, s in zones if s["options"].get("name") == zone_name]
    if len(matches) != 1:
        raise VlanCandidateError("trusted_zone_not_unique")
    zone_id, zone = matches[0]
    members = _members(zone)
    if "lct" not in members or (owned and "mgmt" not in members) or (not owned and "mgmt" in members):
        raise VlanCandidateError("management_zone_binding_unqualified")
    for name, section in zones:
        if name != zone_id and set(_members(section)) & {"lct", "mgmt"}:
            raise VlanCandidateError("management_in_multiple_zones")
    if vlan:
        mgmt_opts = {k: copy.deepcopy(source[k]) for k in ADDRESS if k in source}
        mgmt_opts.update(ifname="mgmt", proto="static", auto=source.get("auto", "1"), aott_owner=OWNER)
        if "macaddr" in opts:
            mgmt_opts["macaddr"] = opts["macaddr"]
        network["lct_vlan"] = {"type": "device", "options": dict(
            ifname=parent, name="mgmt", type="8021q", vid=str(vlan), aott_owner=OWNER)}
        network["mgmt"] = {"type": "interface", "options": mgmt_opts}
        for key in ADDRESS:
            opts.pop(key, None)
        if "mgmt" not in members:
            _replace_members(zone, members + ["mgmt"])
    elif owned:
        for key in ADDRESS:
            if key in source:
                opts[key] = copy.deepcopy(source[key])
            else:
                opts.pop(key, None)
        del network["mgmt"], network["lct_vlan"]
        _replace_members(zone, [v for v in members if v != "mgmt"])
    operations = []
    for package in ("network", "firewall"):
        before, after = snapshot[package], desired[package]
        for name in sorted(set(before) | set(after)):
            left, right = before.get(name), after.get(name)
            key = package + "." + name
            if right is None:
                operations.append(("delete", key))
                continue
            if left is None:
                operations.append(("set", key + "=" + right["type"]))
            old = left["options"] if left else {}
            for option in sorted(set(old) | set(right["options"])):
                previous, value = old.get(option), right["options"].get(option)
                path = key + "." + option
                if previous == value:
                    continue
                if value is None or isinstance(previous, list) or isinstance(value, list):
                    if option in old:
                        operations.append(("delete", path))
                    if isinstance(value, list):
                        operations.extend(("add_list", path + "=" + v) for v in value)
                        continue
                if value is not None:
                    operations.append(("set", path + "=" + value))
    return {"before_revision": expected_revision, "after": desired,
            "operations": operations, "source_only_not_deployed": True}


def verify_staged_plan(plan, adapter):
    """Only disposable adapters are implemented; never promotes any files.

    A rejection may leave a PARTIAL CANDIDATE. Its caller must discard it.
    The independently retained source is never an operation destination.
    """
    if getattr(adapter, "disposable_fixture", False) is not True:
        raise VlanCandidateError("private_candidate_adapter_required")
    if revision(adapter.snapshot()) != plan["before_revision"]:
        raise VlanCandidateError("stale_candidate_revision")
    for operation in plan["operations"]:
        if adapter.command(operation) is not True:
            raise VlanCandidateError("candidate_mutation_failed")
    for package in ("network", "firewall"):
        if adapter.command(("commit", package)) is not True:
            raise VlanCandidateError("candidate_commit_failed")
    # A zero commit exit code or delta-visible export is not durability.
    # The final adapter read must exclude the staged change directory.
    if adapter.persisted_snapshot() != plan["after"]:
        raise VlanCandidateError("candidate_readback_mismatch")
    return {"status": "SOURCE_NATIVE_UCI_CANDIDATE_VALIDATED",
            "operations_checked": len(plan["operations"]),
            "source_only_not_deployed": True, "live_promote_available": False,
            "hardware_network_and_recovery_unverified": True}
