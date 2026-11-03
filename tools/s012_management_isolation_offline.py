#!/usr/bin/env python3
"""S-012: OFFLINE-ONLY, read-only management listener exposure gate.

Correlates vendor uhttpd UCI listener configuration, separately
provided uhttpd process arguments, Linux TCP LISTEN tables, independently
verified management IP bindings and declared ingress probe outcomes.
Neither a model nor a synthetic probe can qualify live device security.
No network, firewall, UCI, uhttpd, firmware, or ISP mutation is possible.
"""
import argparse
import ipaddress
import json
from pathlib import Path
import re
import shlex
import socket
import sys


class IsolationError(ValueError):
    """Fixed safe refusal code, without echoing addresses or secrets."""


MAX_UCI_BYTES = 65536
MAX_KERNEL_BYTES = 131072
MAX_ARGS = 96
MAX_LISTENERS = 32
PROTOCOLS = ("http", "https")
FAMILIES = ("ipv4", "ipv6")
REMOTE_PATHS = ("host_dataplane", "upstream_wan")
PROC_HEX = re.compile(r"^[A-Fa-f0-9]+$")


def parse_endpoint(value, protocol):
    """Parse only numeric IP socket endpoints, not DNS/URLs or zone IDs."""
    if type(value) is not str or not 1 <= len(value) <= 100:
        raise IsolationError("invalid_listener_endpoint")
    if protocol not in PROTOCOLS or "%" in value:
        raise IsolationError("invalid_listener_endpoint")
    if value.startswith("["):
        match = re.fullmatch(r"\[([0-9a-fA-F:.]+)\]:(\d{1,5})", value)
        if match is None:
            raise IsolationError("invalid_bracketed_ipv6_listener")
        family = "ipv6"
        source, raw_port = match.groups()
    else:
        if value.count(":") != 1:
            raise IsolationError("unsupported_listener_syntax")
        source, raw_port = value.rsplit(":", 1)
        family = "ipv4"
    if not raw_port.isdecimal() or len(raw_port) > 5:
        raise IsolationError("invalid_listener_port")
    port = int(raw_port)
    if not 1 <= port <= 65535:
        raise IsolationError("invalid_listener_port")
    try:
        ip = ipaddress.ip_address(source)
    except ValueError:
        raise IsolationError("unqualified_listener_address") from None
    if (family == "ipv4" and ip.version != 4) or \
       (family == "ipv6" and ip.version != 6):
        raise IsolationError("listener_family_mismatch")
    return (protocol, family, str(ip), port)


def parse_uhttpd_uci(text):
    """Parse only UCI sections/keys that affect uhttpd bind coverage.

    Multiple uhttpd instances MUST be covered. An unexpected relevant
    field fails closed instead of silently omitting additional bindings.
    """
    if not isinstance(text, str) or not 1 <= len(text.encode("utf-8")) <= MAX_UCI_BYTES:
        raise IsolationError("invalid_uci_input_size")
    instance = None
    seen_main = False
    instances = []
    for line in text.splitlines():
        if len(line) > 1024:
            raise IsolationError("oversize_uci_line")
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        try:
            parts = shlex.split(stripped, comments=True, posix=True)
        except ValueError:
            raise IsolationError("invalid_uci_syntax") from None
        if not parts:
            continue
        key = parts[0]
        if key == "config":
            if len(parts) not in (2, 3):
                raise IsolationError("invalid_uci_section")
            kind, section_name = parts[1], parts[2] if len(parts) == 3 else None
            instance = None
            if kind == "uhttpd":
                if section_name is not None and (
                    not re.fullmatch(r"[A-Za-z0-9_-]{1,48}", section_name)):
                    raise IsolationError("unqualified_uhttpd_instance_name")
                if section_name == "main":
                    if seen_main:
                        raise IsolationError("duplicate_main_uhttpd_instance")
                    seen_main = True
                instance = {"http": [], "https": []}
                instances.append(instance)
                if len(instances) > 8:
                    raise IsolationError("too_many_uhttpd_instances")
            continue
        if key in ("option", "list"):
            if len(parts) != 3:
                # Relevant broken listener records should never be ignored.
                if instance is not None and len(parts) >= 2 and \
                   parts[1] in ("listen_http", "listen_https"):
                    raise IsolationError("malformed_uhttpd_listener_record")
                continue
            if instance is None or parts[1] not in ("listen_http", "listen_https"):
                continue
            protocol = "http" if parts[1] == "listen_http" else "https"
            # OpenWrt procd iterates the resulting option string on spaces.
            values = parts[2].split()
            if not values:
                raise IsolationError("empty_uhttpd_listener")
            for value in values:
                endpoint = parse_endpoint(value, protocol)
                instance[protocol].append(endpoint)
                if sum(len(v) for item in instances for v in item.values()) > MAX_LISTENERS:
                    raise IsolationError("too_many_uhttpd_listeners")
            continue
        if instance is not None and key.startswith("listen_"):
            raise IsolationError("unknown_listener_directive")
    if not instances:
        raise IsolationError("no_uhttpd_instance")
    endpoints = []
    for item in instances:
        endpoints.extend(item["http"])
        endpoints.extend(item["https"])
    if len(endpoints) != len(set(endpoints)):
        raise IsolationError("duplicate_uhttpd_listener")
    if not endpoints:
        raise IsolationError("no_configured_http_listener")
    return frozenset(endpoints)


def parse_uhttpd_processes(processes):
    """Process argv must come from a separate, trusted read of /proc/<pid>.

    In production, process identity and socket inode ownership require
    direct target proof. This function does not read /proc itself.
    """
    if not isinstance(processes, (tuple, list)) or not 1 <= len(processes) <= 8:
        raise IsolationError("invalid_process_evidence")
    observed = []
    for argv in processes:
        if not isinstance(argv, (tuple, list)) or not 1 <= len(argv) <= MAX_ARGS \
           or any(type(arg) is not str or len(arg) > 256 for arg in argv):
            raise IsolationError("invalid_process_arguments")
        if argv[0] != "/usr/sbin/uhttpd":
            raise IsolationError("uhttpd_executable_identity_unverified")
        i = 1
        while i < len(argv):
            arg = argv[i]
            if arg in ("-p", "-s"):
                if i + 1 >= len(argv):
                    raise IsolationError("missing_listener_argument")
                protocol = "http" if arg == "-p" else "https"
                observed.append(parse_endpoint(argv[i + 1], protocol))
                i += 2
            else:
                i += 1
    if not observed or len(observed) != len(set(observed)):
        raise IsolationError("empty_or_duplicate_active_listener")
    return frozenset(observed)


def parse_proc_tcp(text, family):
    """Read a bounded Linux /proc/net/tcp or tcp6 snapshot, LISTEN only."""
    if family not in FAMILIES or not isinstance(text, str) or \
       len(text.encode("utf-8")) > MAX_KERNEL_BYTES:
        raise IsolationError("invalid_kernel_listener_evidence")
    lines = text.splitlines()
    if not lines or not lines[0].lstrip().startswith("sl "):
        raise IsolationError("invalid_kernel_listener_header")
    result = set()
    for line in lines[1:]:
        fields = line.split()
        if not fields:
            continue
        if len(fields) < 4 or ":" not in fields[1]:
            raise IsolationError("malformed_kernel_listener_row")
        if fields[3].upper() != "0A":
            continue
        encoded, hexport = fields[1].rsplit(":", 1)
        expected = 8 if family == "ipv4" else 32
        if len(encoded) != expected or len(hexport) != 4 or \
           not PROC_HEX.fullmatch(encoded) or not PROC_HEX.fullmatch(hexport):
            raise IsolationError("malformed_listening_socket_address")
        raw = bytes.fromhex(encoded)
        # Linux /proc/net/tcp6 encodes 32-bit words in host endian order.
        normalized = b"".join(raw[i:i + 4][::-1] for i in range(0, len(raw), 4))
        ip = ipaddress.ip_address(normalized)
        port = int(hexport, 16)
        if not 1 <= port <= 65535:
            raise IsolationError("kernel_listener_port_invalid")
        result.add((family, str(ip), port))
    return frozenset(result)


def _management_bindings(bindings):
    if not isinstance(bindings, dict) or set(bindings) != set(FAMILIES):
        raise IsolationError("unknown_management_address_families")
    result = set()
    for family, addresses in bindings.items():
        if not isinstance(addresses, (list, tuple)) or len(addresses) > 6:
            raise IsolationError("invalid_management_address_evidence")
        for value in addresses:
            if type(value) is not str:
                raise IsolationError("invalid_management_ip_address")
            try:
                ip = ipaddress.ip_address(value)
            except ValueError:
                raise IsolationError("invalid_management_ip_address") from None
            if (family == "ipv4" and ip.version != 4) or \
               (family == "ipv6" and ip.version != 6) or \
               ip.is_unspecified or ip.is_multicast or ip.is_loopback or \
               getattr(ip, "ipv4_mapped", None) is not None:
                raise IsolationError("unqualified_management_ip_address")
            result.add((family, str(ip)))
    if not result:
        raise IsolationError("no_independent_management_address")
    return result


def _report(status, violations, missing, endpoints, checked_families):
    # Source-only receipts never echo management/customer IPs, paths,
    # UCI strings, process argv, endpoint ports or ingress source details.
    return {
        "status": status,
        "violation_codes": sorted(set(violations)),
        "missing_evidence": sorted(set(missing)),
        "configured_listener_count": len(endpoints),
        "configured_ipv4_listeners": sum(x[1] == "ipv4" for x in endpoints),
        "configured_ipv6_listeners": sum(x[1] == "ipv6" for x in endpoints),
        "family_coverage": sorted(checked_families),
        "source_only_not_deployed": True,
        "live_hardware_isolation_unverified": True,
        "no_network_or_device_mutation": True,
        "no_firewall_or_uci_apply": True,
        "real_trusted_untrusted_probes_still_required": True,
    }


def assess(uci, management=None, processes=None, kernel=None,
           ingress=None, ipv6_disabled_verified=False):
    """Fail-closed source decision; SOURCE_ELIGIBLE is not hardware PASS.

    management: two-family independently confirmed address inventory.
    kernel: independently read /proc net TCP snapshots, two families.
    ingress: observations per endpoint/path:
      (protocol, family, address, port, role, result),
      role is trusted, host_dataplane or upstream_wan.
      result is connected, refused or unknown.
    All these inputs are OFFLINE injected evidence, never live attestation.
    """
    configured = parse_uhttpd_uci(uci)
    violations, missing = [], []
    covered = set()
    try:
        mgmt = _management_bindings(management)
    except (IsolationError, TypeError):
        mgmt = set()
        missing.append("independent_management_ips")
    local_endpoints = set()
    for protocol, family, addr, port in configured:
        ip = ipaddress.ip_address(addr)
        if ip.is_unspecified:
            violations.append("wildcard_management_listener")
        elif ip.is_multicast or ip.is_reserved or ip.is_link_local or \
             getattr(ip, "ipv4_mapped", None) is not None:
            # IPv6 mapped/ambiguous addresses cannot be trusted as
            # local-only without independent dual-stack qualification.
            violations.append("unqualified_listener_address")
        elif ip.is_loopback:
            continue
        elif (family, addr) not in mgmt:
            violations.append("non_management_listener")
        else:
            local_endpoints.add((protocol, family, addr, port))
    if not any(p == "https" for p, _, _, _ in local_endpoints):
        missing.append("verified_management_https_listener")
    if processes is None:
        missing.append("actual_uhttpd_process_arguments")
    else:
        try:
            runtime = parse_uhttpd_processes(processes)
        except IsolationError:
            violations.append("untrusted_or_invalid_uhttpd_process")
        else:
            if runtime != configured:
                violations.append("configured_runtime_listener_mismatch")
    if kernel is None:
        missing.append("independent_kernel_ipv4_and_ipv6_sockets")
    elif not isinstance(kernel, dict) or set(kernel) != set(FAMILIES):
        missing.append("incomplete_kernel_family_evidence")
    else:
        active = set()
        for family in FAMILIES:
            payload = kernel[family]
            if payload is None:
                missing.append("missing_kernel_" + family)
                continue
            try:
                table = parse_proc_tcp(payload, family)
            except IsolationError:
                violations.append("invalid_kernel_" + family)
                continue
            covered.add(family)
            active.update(table)
        # Kernel tables include other processes; comparison is only
        # conservative corroboration, not socket owner attribution.
        watched_ports = {x[3] for x in configured}
        expected = {(f, addr, port) for _, f, addr, port in configured}
        matched = {x for x in active if x[2] in watched_ports}
        if not expected.issubset(active):
            missing.append("configured_listener_missing_in_kernel")
        unexpected = matched - expected
        if unexpected:
            violations.append("additional_kernel_listener_same_port")
    if not any(x[1] == "ipv4" for x in configured):
        missing.append("ipv4_listener_absence_not_qualified")
    if ipv6_disabled_verified is not True and not any(
        x[1] == "ipv6" for x in configured):
        missing.append("ipv6_listener_absence_not_qualified")
    elif ipv6_disabled_verified is True and any(
        x[1] == "ipv6" for x in configured):
        violations.append("ipv6_disabled_but_listener_configured")
    if ingress is None:
        missing.append("trusted_and_untrusted_ingress_checks")
    elif not isinstance(ingress, (list, tuple)) or len(ingress) > 128:
        violations.append("invalid_ingress_evidence")
    else:
        mapping = {}
        for record in ingress:
            if not isinstance(record, (tuple, list)) or len(record) != 6:
                violations.append("invalid_ingress_record")
                continue
            protocol, family, addr, port, role, outcome = record
            if role not in ("trusted",) + REMOTE_PATHS or \
               outcome not in ("connected", "refused", "unknown"):
                violations.append("invalid_ingress_record")
                continue
            endpoint = (protocol, family, addr, port)
            if endpoint not in local_endpoints:
                violations.append("ingress_for_unqualified_endpoint")
                continue
            key = (endpoint, role)
            if key in mapping:
                violations.append("duplicate_ingress_evidence")
            else:
                mapping[key] = outcome
        for endpoint in local_endpoints:
            trusted = mapping.get((endpoint, "trusted"))
            if trusted == "refused":
                violations.append("trusted_management_path_unreachable")
            elif trusted != "connected":
                missing.append("missing_trusted_ingress_evidence")
            for role in REMOTE_PATHS:
                external = mapping.get((endpoint, role))
                if external == "connected":
                    violations.append("untrusted_ingress_connected")
                elif external != "refused":
                    missing.append("missing_untrusted_ingress_" + role)
    if violations:
        status = "SOURCE_POLICY_REJECTED"
    elif missing:
        status = "SOURCE_EVIDENCE_INCOMPLETE"
    else:
        status = "SOURCE_ELIGIBLE_NOT_HARDWARE_QUALIFIED"
    return _report(status, violations, missing, configured, covered)


def read_vendor_uhttpd(rootfs):
    """Fixed read-only extracted-rootfs path; no keys or other files."""
    if type(rootfs) is not str or not rootfs.startswith("/var/tmp/"):
        raise IsolationError("offline_vendor_rootfs_path_required")
    path = Path(rootfs) / "etc/config/uhttpd"
    if path.is_symlink() or not path.is_file():
        raise IsolationError("offline_uhttpd_config_unavailable")
    with path.open("rb") as handle:
        raw = handle.read(MAX_UCI_BYTES + 1)
    if len(raw) > MAX_UCI_BYTES:
        raise IsolationError("offline_uhttpd_config_too_large")
    try:
        return raw.decode("utf-8")
    except UnicodeError:
        raise IsolationError("offline_uhttpd_not_utf8") from None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--offline-vendor-rootfs", required=True)
    args = parser.parse_args()
    try:
        uci = read_vendor_uhttpd(args.offline_vendor_rootfs)
        receipt = assess(uci)
        # Real IP identities, config lines and process arguments are
        # intentionally absent; do not log actual subscriber data.
        print(json.dumps(receipt, sort_keys=True))
    except IsolationError as exc:
        print(json.dumps({
            "status": "SOURCE_POLICY_REJECTED",
            "violation_codes": [str(exc)],
            "source_only_not_deployed": True,
            "no_network_or_device_mutation": True,
        }, sort_keys=True))
        return 1
    # Exit 2 for unqualified/unsafe native vendor source defaults.
    return 0 if receipt["status"] == "SOURCE_ELIGIBLE_NOT_HARDWARE_QUALIFIED" else 2


if __name__ == "__main__":
    sys.exit(main())
