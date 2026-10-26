#!/usr/bin/env python3
"""Offline rootfs profile planner for AoTT-8311 PRX126 firmware.

Creates only a NEW staging tree. It never writes to a running ONU, mounts
UBI, flashes firmware, copies source files into Git, or changes boot selectors.

Production-oriented profiles preserve proprietary PON/OMCI, network recovery,
hardware QoS, PTP, all seven MIB templates, all user-selectable timezones,
TLS crypto, SSH, HTTP, and the 8311 bank recovery scripts.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

# The MIB format readme is static development documentation. The same
# information belongs in docs/MIB-FORMAT.md, not in the stick's rootfs.
DOCS_ONLY = ("etc/mibs/readme",)
PRX126_COMPACT = (
    "usr/bin/nano",
    "www/luci-static/resources/view/status/include/50_dsl.js",
    "www/luci-static/resources/view/status/include/60_wifi.js",
)
# Experimental only. No full device compatibility or runtime profile is
# established by this offline exclusion, even if one observed running device
# has not loaded libssl.so.1.1. A component could be loaded lazily.
EXPERIMENTAL = ("usr/lib/libssl.so.1.1",)

PROFILES = {
    "documentation-free": DOCS_ONLY,
    "prx126-compact": DOCS_ONLY + PRX126_COMPACT,
    "experimental-no-libssl": DOCS_ONLY + PRX126_COMPACT + EXPERIMENTAL,
}
SENTINELS = {
    "etc/openwrt_release": b"intel_mips/prx300",
    "etc/8311_version": b"AoTT-8311",
    "lib/8311-release-profile": b"profile potron-prx126-aott-v1",
    "etc/mibs/prx300_1U.ini": b"",
}
PIN_LINE_PREFIX = "file candidate usr/lib/libssl.so.1.1 "
UNSAFE_DIRS = (Path("/etc"), Path("/dev"), Path("/proc"), Path("/sys"),
               Path("/ptconf"), Path("/root"), Path("/home"))
PROTECTED = frozenset({
    "usr/bin/omcid", "usr/bin/pon", "usr/lib/libcrypto.so.1.1",
    "lib/libustream-ssl.so", "lib/modules", "etc/mibs/prx300_1U.ini",
    "usr/sbin/8311-bankctl.sh", "usr/sbin/8311-firmware-upgrade.sh",
    "usr/sbin/tcpdump", "usr/sbin/8311-rarpd.sh", "usr/lib/libpcap.so.1",
})


class ProfileError(ValueError):
    pass


def require(value: bool, message: str):
    if not value:
        raise ProfileError(message)


def sha_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024*1024), b""):
            digest.update(block)
    return digest.hexdigest()


def safe_root(root: Path) -> Path:
    # Resolve and reject system roots and symlink paths before even reading.
    original = Path(root).absolute()
    require(not original.is_symlink(), "Root path cannot be a symlink")
    result = original.resolve(strict=True)
    require(result.is_dir(), "Rootfs source is not a directory")
    require(result != Path("/") and
            not any(result == p or p in result.parents for p in UNSAFE_DIRS),
            "Refusing a live system directory")
    return result


def verify_family(root: Path):
    for name, expected in SENTINELS.items():
        file = root / name
        require(file.is_file() and not file.is_symlink(),
                "Source does not contain required clean PRX126 image sentinel: "+name)
        if expected:
            require(expected in file.read_bytes(),
                    "PRX126 source sentinel mismatch: "+name)
    firmware_release=(root/"etc/openwrt_release").read_bytes()
    require(b"PTXG_CX_V0.03" in firmware_release,
            "Unsupported vendor firmware base or different SDK ABI")
    omcid = root/"usr/bin/omcid"
    require(omcid.is_file() and not omcid.is_symlink(),
            "Proprietary OMCI runtime missing")
    with omcid.open("rb") as stream:
        head = stream.read(20)
    require(len(head) == 20 and head[:4] == b"\x7fELF" and
            head[4] == 1 and head[5] == 2 and head[18:20] == b"\x00\x08",
            "OMCI daemon is not compatible MIPS32 big-endian ELF")


def profile_plan(root: Path, profile: str, acknowledge: bool = False):
    root=safe_root(root)
    require(profile in PROFILES, "Unknown pruning profile")
    verify_family(root)
    require(profile!="experimental-no-libssl" or acknowledge,
            "Experimental libssl removal requires an explicit risk acknowledgement")
    removals=[]
    for rel in PROFILES[profile]:
        require(rel not in PROTECTED,"Cannot remove protected runtime dependency")
        target=root/rel
        require(target.is_file() and not target.is_symlink(),
                "Expected optional file absent or changed: "+rel)
        removals.append({
            "path":rel, "uncompressed_bytes":target.stat().st_size,
            "sha256":sha_file(target)
        })
    # The release profile is a *runtime* integrity contract, not documentation.
    # An experimental profile must not leave a false pin for a removed asset.
    profile_data=(root/"lib/8311-release-profile").read_text()
    matches=[l for l in profile_data.splitlines()
             if l.startswith(PIN_LINE_PREFIX)]
    if profile=="experimental-no-libssl":
        require(len(matches)==1,"Cannot safely update release profile pin")
        require(matches[0].split()[2]=="usr/lib/libssl.so.1.1",
                "Unexpected runtime pin")
    return {
        "schema":1, "family":"prx126-sfp-pon", "profile":profile,
        "qualification":"experimental" if profile=="experimental-no-libssl"
                        else "offline-candidate",
        "hardware_qualified":False,
        "rootfs_source":str(root),
        "pruned":removals,
        "uncompressed_bytes":sum(x["uncompressed_bytes"] for x in removals),
        "release_profile_requires_update":profile=="experimental-no-libssl",
        "protected_runtime_dependencies":sorted(PROTECTED),
        "note":"Offline optimization plan only. No firmware is installed or certified."
    }


def stage(root: Path, destination: Path, profile: str, acknowledge=False):
    plan=profile_plan(root,profile,acknowledge)
    src=Path(plan["rootfs_source"])
    dst=Path(destination).absolute()
    require(not dst.exists() and not dst.is_symlink(),
            "Destination must not already exist")
    require(dst.parent.exists() and dst.parent.is_dir(),
            "Destination parent must already exist")
    parent=dst.parent.resolve(strict=True)
    require(src not in parent.parents and parent!=src,
            "Destination must not be inside the source rootfs")
    resolved_destination=parent/dst.name
    require(not any(resolved_destination == p or p in resolved_destination.parents
                    for p in UNSAFE_DIRS) and
            resolved_destination != Path("/"),
            "Destination is a protected system location")
    require(not any(src == p or src in p.parents for p in (dst,)),
            "Destination and source cannot contain one another")
    created=False
    try:
        # cp -a preserves file modes, symlinks, ownership, timestamp and the
        # device nodes required by a real offline rootfs image.
        call=subprocess.run(["/bin/cp","-a","--",str(src),str(dst)],
                            stdout=subprocess.PIPE,stderr=subprocess.PIPE,
                            timeout=90,check=False)
        require(call.returncode==0,
                "Offline rootfs copy failed (diagnostics intentionally withheld)")
        created=True
        for obj in plan["pruned"]:
            rel=obj["path"]
            candidate=dst/rel
            require(candidate.is_file() and not candidate.is_symlink(),
                    "Unexpected output path during prune: "+rel)
            require(sha_file(candidate)==obj["sha256"],
                    "Copied source file unexpectedly changed: "+rel)
            candidate.unlink()
        if plan["release_profile_requires_update"]:
            pin=dst/"lib/8311-release-profile"
            data=pin.read_text()
            lines=data.splitlines(keepends=True)
            chosen=[line for line in lines if line.startswith(PIN_LINE_PREFIX)]
            require(len(chosen)==1,"Unexpected runtime compatibility contract")
            updated="".join(line for line in lines
                            if not line.startswith(PIN_LINE_PREFIX))
            require(PIN_LINE_PREFIX not in updated,
                    "Failed to eliminate stale removed-library pin")
            pin.write_text(updated)
        for required in PROTECTED:
            require((dst/required).exists(),
                    "Protected firmware dependency missing: "+required)
        verify_family(dst)
        for obj in plan["pruned"]:
            require(not (dst/obj["path"]).exists(),
                    "Pruned path remains: "+obj["path"])
        result=dict(plan)
        result["rootfs_source"]="(local offline image, not recorded)"
        result["staging_destination"]=str(dst)
        result["staged"]=True
        result["runtime_profile_sha256"]=sha_file(dst/"lib/8311-release-profile")
        return result
    except Exception:
        # Remove only an output that did not exist before this call.
        if created or dst.exists():
            shutil.rmtree(dst,ignore_errors=True)
        raise


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source",type=Path,required=True)
    parser.add_argument("--profile",choices=sorted(PROFILES),required=True)
    parser.add_argument("--destination",type=Path)
    parser.add_argument("--stage",action="store_true",
                        help="Create a new offline output directory")
    parser.add_argument("--acknowledge-experimental",action="store_true",
                        help="Opt in to unqualified removal of libssl.so.1.1")
    args=parser.parse_args()
    try:
        if args.stage:
            require(args.destination is not None,
                    "--destination required when staging")
            data=stage(args.source,args.destination,args.profile,
                       args.acknowledge_experimental)
        else:
            require(args.destination is None,
                    "Omit destination in nonmutating planning mode")
            data=profile_plan(args.source,args.profile,
                              args.acknowledge_experimental)
            data["staged"]=False
    except (ProfileError,OSError,subprocess.SubprocessError) as exc:
        print(json.dumps({"status":"rejected","reason":str(exc)},sort_keys=True))
        return 1
    print(json.dumps(data,indent=2,sort_keys=True))
    return 0


if __name__=="__main__":
    sys.exit(main())
