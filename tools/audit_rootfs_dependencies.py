#!/usr/bin/env python3
"""Read-only PRX126 rootfs dependency and feature audit.

This tool does not remove any files, write to the rootfs, contact an ONU,
read subscriber configuration values, or generate a flashable image.
Dynamic imports and hardware functions must still be reviewed separately.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys

from prune_rootfs import safe_root, verify_family, ProfileError

NEEDED_RE = re.compile(r"\(NEEDED\)\s+Shared library:\s+\[([A-Za-z0-9_.+-]+)\]")
DYNAMIC_CANDIDATES = ("usr/bin/omcid", "usr/sbin/uhttpd", "sbin/rpcd",
                      "lib/libustream-ssl.so", "usr/sbin/tcpdump")
LIBRARY_DIRS = ("lib", "usr/lib", "usr/lib/sudo", "opt/pon/lib", "opt/intel/lib")
PROTECTED_LIBS = ("usr/lib/libcrypto.so.1.1", "lib/libustream-ssl.so",
                  "usr/lib/libmbedtls.so.3.6.7",
                  "usr/lib/libmbedcrypto.so.3.6.7")
DOCUMENTATION = ("etc/mibs/readme",)
OMCI_NAME = "libcrypto.so.1.1"
SSL_NAME = "libssl.so.1.1"


class AuditError(ValueError):
    pass


def elf32_mips_big_endian(path: Path) -> bool:
    with path.open("rb") as source:
        hdr = source.read(20)
    return (len(hdr) >= 20 and hdr[:4] == b"\x7fELF"
            and hdr[4] == 1 and hdr[5] == 2
            and hdr[18:20] == b"\x00\x08")


def parse_needed(text: str) -> tuple[str, ...]:
    return tuple(sorted(set(NEEDED_RE.findall(text))))


def needed_for(path: Path) -> tuple[str, ...]:
    if not elf32_mips_big_endian(path):
        return ()
    proc = subprocess.run(["/usr/bin/readelf", "--dynamic", "--wide", str(path)],
                          capture_output=True, text=True, timeout=12,
                          check=False)
    if proc.returncode != 0:
        raise AuditError("Unable to parse one MIPS ELF runtime dependency")
    return parse_needed(proc.stdout)


def list_elfs(root: Path) -> dict[str, tuple[str, ...]]:
    deps = {}
    for base in ("bin", "sbin", "usr/bin", "usr/sbin",
                 "usr/lib", "lib", "opt"):
        location = root / base
        if not location.is_dir():
            continue
        for path in location.rglob("*"):
            if path.is_symlink() or not path.is_file() or path.suffix == ".ko":
                continue
            if path.is_relative_to(root / "lib/modules"):
                continue
            if elf32_mips_big_endian(path):
                deps[path.relative_to(root).as_posix()] = needed_for(path)
    return dict(sorted(deps.items()))


def duplicate_groups(root: Path):
    groups = defaultdict(list)
    for path in root.rglob("*"):
        if not path.is_file() or path.is_symlink():
            continue
        size = path.stat().st_size
        if size < 512:
            continue
        h = hashlib.sha256()
        with path.open("rb") as f:
            for part in iter(lambda: f.read(262144), b""):
                h.update(part)
        groups[(size, h.hexdigest())].append(path.relative_to(root).as_posix())
    grouped = [(size, sorted(paths))
               for (size, _), paths in groups.items() if len(paths) > 1]
    return sorted(grouped, key=lambda pair: (-pair[0] * (len(pair[1]) - 1),
                                             pair[1][0]))


def optional_status_assets(root: Path) -> dict:
    menu_file = root / "usr/share/luci/menu.d/luci-mod-status.json"
    try:
        menu = json.loads(menu_file.read_text())
    except (OSError, ValueError) as exc:
        raise AuditError("Cannot inspect LuCI menu conditions") from exc
    status = menu.get("admin/status/realtime/wireless", {})
    wifi_route = (
        status.get("action", {}).get("path") == "status/wireless"
        and status.get("depends", {}).get("uci", {})
                  .get("wireless", {}).get("@wifi-device") is True)
    radio_config = (root / "etc/config/wireless").exists()
    paths = (
        "www/luci-static/resources/view/status/include/50_dsl.js",
        "www/luci-static/resources/view/status/include/60_wifi.js",
        "www/luci-static/resources/view/status/wireless.js",
        "www/luci-static/resources/wireless.svg",
        "www/luci-static/resources/wifirate.svg",
    )
    available = [p for p in paths if (root / p).is_file()]
    return {
        "wireless_route_uci_guarded": wifi_route,
        "firmware_contains_wireless_config": radio_config,
        "conditional_pruning_suitable": bool(wifi_route and not radio_config),
        "optional_status_assets_present": available,
        "note": "Conditional UI pruning only; all other LuCI routing requires review",
    }


def runtime_classification(root: Path,
                           deps: dict[str, tuple[str, ...]]) -> dict:
    consumer_map = defaultdict(list)
    for source, names in deps.items():
        for name in names:
            consumer_map[name].append(source)
    def uses(name: str) -> list[str]:
        return sorted(consumer_map.get(name, ()))
    omci_dependencies = deps.get("usr/bin/omcid", ())
    ssl_direct = uses(SSL_NAME)
    pcap_needed = tuple(name for name in
                        deps.get("usr/sbin/tcpdump", ())
                        if name.startswith("libpcap.so."))
    pcap_direct = sorted(set(path for name in ("libpcap.so.1","libpcap.so.0.8")
                             for path in uses(name)))
    pcap_elf = bool((root / "usr/sbin/tcpdump").is_file()
                    and pcap_needed)
    reverse_arp = root / "usr/sbin/8311-rarpd.sh"
    rarp_requires_tcpdump = reverse_arp.is_file() and "tcpdump" in reverse_arp.read_text()
    uhttpd_path = root / "usr/sbin/uhttpd"
    uhttpd_mentions_ustream = (uhttpd_path.is_file()
                                and b"libustream-ssl.so" in uhttpd_path.read_bytes())
    runtime = {
        "critical_omci_crypto": {
            "required_library": OMCI_NAME,
            "omcid_directly_needs_it": OMCI_NAME in omci_dependencies,
            "consumer_paths": uses(OMCI_NAME),
            "action": "keep",
        },
        "web_tls": {
            "uhttpd_mentions_ustream_module": uhttpd_mentions_ustream,
            "mbedtls_linked_in_ustream":
                "libmbedtls.so.21" in deps.get("lib/libustream-ssl.so", ()),
            "action": "keep",
        },
        "openssl_ssl": {
            "library_present": (root / "usr/lib/libssl.so.1.1").is_file(),
            "direct_elf_consumers": ssl_direct,
            "action": "experimental_only" if not ssl_direct else "keep",
            "note": "Late loading and vendor runtime profile still require qualification",
        },
        "reverse_arp_capture": {
            "rarp_script_mentions_tcpdump": rarp_requires_tcpdump,
            "tcpdump_directly_needs_libpcap": pcap_elf,
            "libpcap_consumers": pcap_direct,
            "action": "keep",
        },
    }
    return runtime


def audit(root: Path) -> dict:
    root = safe_root(root)
    verify_family(root)
    deps = list_elfs(root)
    duplicate = duplicate_groups(root)
    libs = {}
    for name in LIBRARY_DIRS:
        p = root / name
        if p.is_dir():
            libs[name] = sum(1 for x in p.rglob("*")
                             if x.is_file() and not x.is_symlink())
    available_lib_names = set()
    for name in LIBRARY_DIRS:
        p = root / name
        if p.is_dir():
            available_lib_names.update(
                x.name for x in p.iterdir() if x.is_file() or x.is_symlink())
    required = sorted(set(name for items in deps.values() for name in items))
    unresolved = [x for x in required if x not in available_lib_names]
    # Unresolved sonames can be supplied through RPATH or dlopen and require
    # individual analysis. They are not proof of missing platform libraries.
    groups = [
        {"files": paths, "copies": len(paths),
         "bytes_each": size, "unpacked_redundant_bytes": size * (len(paths)-1)}
        for size, paths in duplicate[:15]
    ]
    candidate_docs = [rel for rel in DOCUMENTATION if (root/rel).is_file()]
    classification = runtime_classification(root, deps)
    if not classification["critical_omci_crypto"]["omcid_directly_needs_it"]:
        raise AuditError("Required OMCI OpenSSL dependency missing: cannot audit this ABI")
    if not classification["web_tls"]["mbedtls_linked_in_ustream"]:
        raise AuditError("Expected Mbed TLS link contract changed")
    if not classification["reverse_arp_capture"]["rarp_script_mentions_tcpdump"]:
        raise AuditError("Reverse-ARP dependency assumption changed")
    return {
        "schema": 1,
        "hardware_family": "PRX126-SFP-PON",
        "vendor_base": "PTXG_CX_V0.03",
        "source_only": True,
        "read_only": True,
        "flashable": False,
        "hardware_qualified": False,
        "elf_objects_scanned": len(deps),
        "direct_needed_sonames": len(required),
        "unresolved_soname_names": unresolved,
        "library_directory_regular_file_counts": libs,
        "classification": classification,
        "ui": optional_status_assets(root),
        "documentation_only_present": candidate_docs,
        "exact_duplicate_groups": len(duplicate),
        "redundant_uncompressed_bytes": sum(size*(len(paths)-1)
                                            for size, paths in duplicate),
        "largest_exact_duplicate_groups": groups,
        "caveats": [
            "One image and one board. Conditional firmware/OLT modes are not all exercised.",
            "ELF NEEDED does not capture dlopen, shell, Lua, boot scripts, or kernel module dependencies.",
            "Xz/SquashFS deduplication already avoids much redundant compressed data.",
            "Do not automatically delete items not observed in this report.",
            "No subscriber serials, MACs, boot environment dumps, or secrets are reported.",
        ]
    }


def main() -> int:
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rootfs",required=True,type=Path)
    parser.add_argument("--output",choices=("summary","json"),default="summary")
    args=parser.parse_args()
    try:
        report=audit(args.rootfs)
    except (AuditError,ProfileError,OSError,ValueError,
            subprocess.TimeoutExpired) as exc:
        print(json.dumps({"status": "rejected", "reason": str(exc)[:150]}))
        return 1
    if args.output == "json":
        print(json.dumps(report,indent=2,sort_keys=True))
    else:
        selected={
            "status":"audited",
            "elf_objects_scanned":report["elf_objects_scanned"],
            "needed_sonames":report["direct_needed_sonames"],
            "unresolved_sonames":len(report["unresolved_soname_names"]),
            "documentation_only_present":report["documentation_only_present"],
            "redundant_uncompressed_bytes":report["redundant_uncompressed_bytes"],
            "exact_duplicate_groups":report["exact_duplicate_groups"],
            "critical_runtime":report["classification"],
            "optional_ui":report["ui"],
            "hardware_qualified":False,
            "safe_to_auto_prune":False,
        }
        print(json.dumps(selected,indent=2,sort_keys=True))
    return 0


if __name__=="__main__":
    raise SystemExit(main())
