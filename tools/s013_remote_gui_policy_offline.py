#!/usr/bin/env python3
"""S-013: offline-only residential remote GUI firewall preview.

Builds disabled fw3 UCI rule candidates and a model of an explicit,
recoverable enablement trial. No host commands or live target access.
This module must never apply, activate or commit firewall rules.
"""
import argparse
import ipaddress
import json
from pathlib import Path
import re
import sys

MAX_CIDRS = 8
MAX_RULES = 8
DEFAULT_TRIAL_SECONDS = 120
MIN_TRIAL_SECONDS = 60
MAX_TRIAL_SECONDS = 300
ROLES = ("ipv4", "ipv6")
REQUIRED_EVIDENCE = (
    "management_https_listener_verified",
    "trusted_local_recovery_verified",
    "independent_alternate_recovery_verified",
    "fw3_backend_qualified",
    "ingress_zone_mapping_verified",
    "wan_input_default_deny_verified",
    "no_broad_input_accept_override_verified",
    "bridge_forwarding_unaffected_verified",
    "rule_snapshot_and_restore_verified",
    "rollback_timer_survives_session_loss_verified",
    "independent_remote_test_vantage_available",
)
SAFE_ZONE = re.compile(r"^[a-z][a-z0-9_]{0,19}$")


class PolicyError(ValueError):
    """Fixed non-sensitive denial code."""


def default_policy():
    return {
        "schema": 1,
        "remote_gui_enabled": False,
        "remote_gui_requires_explicit_opt_in": True,
        "source_cidrs": {"ipv4": [], "ipv6": []},
        "https_port": 443,
        "rule_revision": 0,
        "automatic_activation": False,
        "fw3_uci_write": False,
        "firewall_service_reload": False,
        "no_olt_omci_or_forwarding_mutation": True,
    }


def normalize_sources(sources):
    if not isinstance(sources, dict) or set(sources) != set(ROLES):
        raise PolicyError("explicit_ipv4_ipv6_sources_required")
    canonical = {}
    for family in ROLES:
        values = sources[family]
        if not isinstance(values, (tuple, list)) or len(values) > MAX_CIDRS:
            raise PolicyError("invalid_source_cidr_list")
        found = []
        for value in values:
            if type(value) is not str or len(value) > 64 or "%" in value:
                raise PolicyError("source_cidr_invalid")
            if "/" not in value:
                raise PolicyError("explicit_cidr_prefix_required")
            try:
                network = ipaddress.ip_network(value, strict=True)
            except ValueError:
                raise PolicyError("source_cidr_invalid") from None
            if (network.version == 4 and family != "ipv4") or (
                    network.version == 6 and family != "ipv6"):
                raise PolicyError("source_ip_family_mismatch")
            if network.prefixlen < (24 if family == "ipv4" else 64):
                raise PolicyError("source_scope_too_broad")
            if (network.is_multicast or network.is_unspecified or
                network.is_loopback or network.is_link_local or
                getattr(network.network_address, "ipv4_mapped", None)):
                raise PolicyError("non_remote_source_scope")
            found.append(network)
        if len(set(found)) != len(found):
            raise PolicyError("duplicate_source_cidr")
        for i, a in enumerate(found):
            for b in found[i + 1:]:
                if a.overlaps(b):
                    raise PolicyError("overlapping_source_cidrs")
        canonical[family] = [str(v) for v in sorted(found, key=lambda n: (int(n.network_address), n.prefixlen))]
    if not 1 <= sum(map(len, canonical.values())) <= MAX_CIDRS:
        raise PolicyError("remote_sources_required")
    return canonical


def validate_target(target):
    if not isinstance(target, dict) or set(target) != set(ROLES):
        raise PolicyError("explicit_management_target_families_required")
    result = {}
    for family in ROLES:
        value = target[family]
        if value is None:
            result[family] = None
            continue
        if type(value) is not str or not value or len(value) > 64 or "%" in value:
            raise PolicyError("invalid_management_target_ip")
        try:
            addr = ipaddress.ip_address(value)
        except ValueError:
            raise PolicyError("invalid_management_target_ip") from None
        if (addr.version == 4 and family != "ipv4") or (
                addr.version == 6 and family != "ipv6"):
            raise PolicyError("management_family_mismatch")
        if (addr.is_unspecified or addr.is_multicast or addr.is_loopback or
                addr.is_link_local or
                getattr(addr, "ipv4_mapped", None)):
            raise PolicyError("unsafe_management_target_ip")
        result[family] = str(addr)
    return result


def validate_request(request):
    """Accept only an explicit HTTPS-only policy request, not a toggle default."""
    if not isinstance(request, dict):
        raise PolicyError("invalid_remote_policy_request")
    required = {
        "explicit_enable", "operator_acknowledged", "https_port",
        "ingress_zone", "sources", "management_targets", "trial_seconds",
    }
    if set(request) != required:
        raise PolicyError("remote_policy_schema_mismatch")
    if request["explicit_enable"] is not True or request["operator_acknowledged"] is not True:
        raise PolicyError("remote_gui_not_explicitly_authorized")
    port = request["https_port"]
    if type(port) is not int or not (
        port == 443 or 1024 <= port <= 65535):
        raise PolicyError("https_port_out_of_bounds")
    seconds = request["trial_seconds"]
    if type(seconds) is not int or not MIN_TRIAL_SECONDS <= seconds <= MAX_TRIAL_SECONDS:
        raise PolicyError("rollback_trial_duration_invalid")
    zone = request["ingress_zone"]
    if type(zone) is not str or not SAFE_ZONE.fullmatch(zone) or zone == "lan":
        raise PolicyError("ingress_zone_not_qualified")
    src = normalize_sources(request["sources"])
    dest = validate_target(request["management_targets"])
    for family in ROLES:
        if src[family] and not dest[family]:
            raise PolicyError("missing_management_target_for_family")
    return {
        "port": port, "ingress_zone": zone,
        "sources": src, "targets": dest, "trial_seconds": seconds,
    }


def render_disabled_candidate(request):
    """Render fw3 rule candidates with enabled=0, never a live/apply command.

    Source address and management target must already be independently
    qualified in a later actual-device admission flow. No change is
    applied or even staged by this tool.
    """
    plan = validate_request(request)
    rules = []
    for family in ROLES:
        for source in plan["sources"][family]:
            target = plan["targets"][family]
            rule = {
                "enabled": "0", "src": plan["ingress_zone"],
                "src_ip": source, "dest_ip": target,
                "dest_port": str(plan["port"]), "proto": "tcp",
                "family": family, "target": "ACCEPT",
            }
            rules.append(rule)
    if len(rules) > MAX_RULES:
        raise PolicyError("too_many_firewall_rules")
    text = []
    for idx, r in enumerate(rules, 1):
        # Names are deliberately generated, never copied from input.
        text.extend(["config rule",
                     f"\toption name 'AoTT-Remote-HTTPS-{idx}'"])
        for key in ("enabled", "src", "src_ip", "dest_ip",
                    "dest_port", "proto", "family", "target"):
            text.append(f"\toption {key} '{r[key]}'")
        text.append("")
    return {"rules": rules, "disabled_uci_text": "\n".join(text),
            "summary": {"source_only": True, "active_rules": 0,
                        "candidate_rules": len(rules), "enabled": False,
                        "no_network_write": True,
                        "no_live_device_operation": True}}


def qualify_offline(request, evidence):
    """Fail closed if required external evidence is absent/unknown.

    This is a modeled source contract, not production activation
    authorization and never proof of a true remote connection.
    """
    candidate = render_disabled_candidate(request)
    # A request, typo or forged non-dictionary evidence must never raise
    # an unexpected error or result in partial rule activation.
    if not isinstance(evidence, dict):
        evidence = {}
    missing = [key for key in REQUIRED_EVIDENCE if evidence.get(key) is not True]
    status = "SOURCE_BLOCKED" if missing else "SOURCE_TRIAL_PLAN_READY_NOT_DEPLOYED"
    plan = validate_request(request)
    for family in ROLES:
        if plan["sources"][family]:
            key = "source_family_" + family + "_verified"
        else:
            key = "remote_" + family + "_default_denial_verified"
        if evidence.get(key) is not True:
            missing.append(key)
    if missing:
        status = "SOURCE_BLOCKED"
    return {
        "status": status,
        "missing_guards": sorted(set(missing)),
        "candidate_rules": candidate["summary"]["candidate_rules"],
        "active_rules": 0,
        "configured_ipv4_sources": len(plan["sources"]["ipv4"]),
        "configured_ipv6_sources": len(plan["sources"]["ipv6"]),
        "remote_gui_enabled": False,
        "source_only_not_deployed": True,
        "hardware_reachability_unverified": True,
        "no_fw3_or_iptables_write": True,
        "no_bridge_or_omci_change": True,
    }


def simulate_guarded_trial(request, evidence, receipts):
    """Offline state machine for trial and automatic fallback conditions.

    Input receipts represent independent *injected observations* at a
    monotonic clock, never active connections or system side effects.
    A trial is not an actual device rollout even when the model passes.
    """
    preflight = qualify_offline(request, evidence)
    if preflight["status"] != "SOURCE_TRIAL_PLAN_READY_NOT_DEPLOYED":
        return {"status": "SOURCE_TRIAL_BLOCKED", "rollback_required": False,
                "source_only_not_deployed": True}
    plan = validate_request(request)
    if not isinstance(receipts, (tuple, list)) or not 1 <= len(receipts) <= 16:
        raise PolicyError("invalid_trial_evidence")
    seen_local = False
    seen_allowed_remote = False
    seen_denied_unauthorized = False
    operator_final_confirmation = False
    previous_time = -1
    for event in receipts:
        if not isinstance(event, dict) or set(event) != {
            "at_second", "source", "outcome"}:
            raise PolicyError("invalid_trial_receipt_schema")
        now, kind, result = (event["at_second"], event["source"], event["outcome"])
        if type(now) is not int or now <= previous_time:
            raise PolicyError("trial_clock_invalid")
        previous_time = now
        if now > plan["trial_seconds"]:
            return {"status": "SOURCE_TRIAL_ROLLBACK_MODEL",
                    "reason": "deadline_elapsed_without_confirmation",
                    "rollback_required": True, "source_only_not_deployed": True}
        if operator_final_confirmation:
            return {"status": "SOURCE_TRIAL_ROLLBACK_MODEL",
                    "reason": "unexpected_postconfirmation_activity",
                    "rollback_required": True, "source_only_not_deployed": True}
        if (kind, result) == ("trusted_local", "connected"):
            seen_local = True
        elif (kind, result) == ("allowlisted_remote", "connected"):
            seen_allowed_remote = True
        elif (kind, result) == ("unlisted_remote", "refused"):
            seen_denied_unauthorized = True
        elif (kind, result) == ("operator_confirmation", "approved") and all(
            (seen_local, seen_allowed_remote, seen_denied_unauthorized)
        ):
            # Confirmation must be AFTER the three separate modeled
            # observations. Do not treat initial opt-in as final consent.
            operator_final_confirmation = True
        else:
            return {"status": "SOURCE_TRIAL_ROLLBACK_MODEL",
                    "reason": "unexpected_trial_evidence",
                    "rollback_required": True, "source_only_not_deployed": True}
    if not all((seen_local, seen_allowed_remote,
                seen_denied_unauthorized, operator_final_confirmation)):
        return {"status": "SOURCE_TRIAL_ROLLBACK_MODEL",
                "reason": "missing_confirmation_or_recovery",
                "rollback_required": True, "source_only_not_deployed": True}
    return {
        "status": "SOURCE_TRIAL_VERIFIED_SYNTHETIC_ONLY",
        "rollback_required": False,
        "source_only_not_deployed": True,
        "real_wan_connectivity_unverified": True,
        "no_live_commit_performed": True,
    }


def probe_vendor_fw3(rootfs):
    """Inspect only published text configs/binary existence in offline rootfs."""
    if type(rootfs) is not str or not rootfs.startswith("/var/tmp/"):
        raise PolicyError("offline_rootfs_required")
    path = Path(rootfs)
    if not (path / "sbin/fw3").is_file():
        raise PolicyError("vendor_fw3_not_found")
    cfg = path / "etc/config/firewall"
    if cfg.is_symlink() or not cfg.is_file() or cfg.stat().st_size > 65536:
        raise PolicyError("offline_firewall_config_unavailable")
    # Fixed-bounded bytes, never print the actual UCI file contents.
    data = cfg.read_bytes()
    if len(data) > 65536:
        raise PolicyError("offline_firewall_config_oversize")
    text = data.decode("utf-8", errors="strict")
    # Vendor default WAN input REJECT is necessary but never sufficient.
    sections = text.split("config zone")
    wan_reject = any(re.search(r"option name\s+'?wan'?", s) and
                     re.search(r"option input\s+REJECT", s)
                     for s in sections[1:])
    return {
        "status": "SOURCE_VENDOR_FW3_PRESENT",
        "wan_input_reject_in_extracted_source": bool(wan_reject),
        "runtime_filter_rules_unverified": True,
        "ipv4_and_ipv6_firewall_execution_unverified": True,
        "source_only_not_deployed": True,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--offline-vendor-rootfs", required=True)
    a = parser.parse_args()
    try:
        result = probe_vendor_fw3(a.offline_vendor_rootfs)
        print(json.dumps(result, sort_keys=True))
        return 0
    except (PolicyError, OSError, UnicodeError):
        print(json.dumps({"status": "SOURCE_VENDOR_FW3_UNVERIFIED",
                          "source_only_not_deployed": True}))
        return 2


if __name__ == "__main__":
    sys.exit(main())
