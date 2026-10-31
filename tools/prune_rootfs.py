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
import posixpath
import re
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
    # The standalone wireless status view is guarded by an absent
    # wireless UCI device. Its SVG assets have no other source consumers.
    "www/luci-static/resources/view/status/wireless.js",
    "www/luci-static/resources/wireless.svg",
    "www/luci-static/resources/wifirate.svg",
)
# Optional host-side development and terminal tools. These are not imported
# by the audited PRX126 management or boot scripts. Keep them in the full
# diagnostic image. Production use still requires a hardware trial.
PRX126_LEAN_COMMANDS = (
    "usr/bin/stress",
    "usr/bin/omci_simulate",
    "usr/sbin/mtr",
    "usr/bin/lrz", "usr/bin/lrx", "usr/bin/rx", "usr/bin/lrb",
    "usr/bin/rz", "usr/bin/rb",
    "usr/bin/lsz", "usr/bin/lsx", "usr/bin/sb", "usr/bin/sz",
    "usr/bin/lsb", "usr/bin/sx",
    "usr/bin/zstd", "usr/bin/zstdcat", "usr/bin/unzstd",
    "usr/bin/zstdmt", "usr/bin/zstdless", "usr/bin/zstdgrep",
)
# Libraries solely linked from these removable debugging utilities.
# Check the ELF closure and all symlinks on every build before excluding.
PRX126_LEAN_LIBRARIES = (
    "usr/lib/libzstd.so", "usr/lib/libzstd.so.1",
    "usr/lib/libzstd.so.1.4.5",
    "usr/lib/libncursesw.so.6", "usr/lib/libncursesw.so.6.1",
    "usr/lib/libncurses.so.6", "usr/lib/libncurses.so.6.1",
    "usr/lib/libformw.so.6", "usr/lib/libformw.so.6.1",
    "usr/lib/libform.so.6", "usr/lib/libform.so.6.1",
    "usr/lib/libmenuw.so.6", "usr/lib/libmenuw.so.6.1",
    "usr/lib/libmenu.so.6", "usr/lib/libmenu.so.6.1",
    "usr/lib/libpanelw.so.6", "usr/lib/libpanelw.so.6.1",
    "usr/lib/libpanel.so.6", "usr/lib/libpanel.so.6.1",
)
LEAN_REMOVALS = PRX126_LEAN_COMMANDS + PRX126_LEAN_LIBRARIES
LEAN_LOGIN_ALIAS = 'alias mtr=\'/usr/sbin/mtr -b -o "LSRD NBAWVJMX"\''
LEAN_LOGIN_PROFILE = "root/.profile"
# Experimental only. Do not remove the vendor OpenSSL SSL ABI before
# late-loading, release-profile and recovery tests on a separate device.
EXPERIMENTAL = ("usr/lib/libssl.so.1.1",)

PROFILES = {
    "documentation-free": DOCS_ONLY,
    "prx126-compact": DOCS_ONLY + PRX126_COMPACT,
    "prx126-runtime-lean": DOCS_ONLY + PRX126_COMPACT + LEAN_REMOVALS,
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
        file = checked_path(root,name)
        require(file.is_file() and not file.is_symlink(),
                "Source does not contain required clean PRX126 image sentinel: "+name)
        if expected:
            require(expected in file.read_bytes(),
                    "PRX126 source sentinel mismatch: "+name)
    firmware_release=(root/"etc/openwrt_release").read_bytes()
    require(b"PTXG_CX_V0.03" in firmware_release,
            "Unsupported vendor firmware base or different SDK ABI")
    omcid = checked_path(root,"usr/bin/omcid")
    require(omcid.is_file() and not omcid.is_symlink(),
            "Proprietary OMCI runtime missing")
    with omcid.open("rb") as stream:
        head = stream.read(20)
    require(len(head) == 20 and head[:4] == b"\x7fELF" and
            head[4] == 1 and head[5] == 2 and head[18:20] == b"\x00\x08",
            "OMCI daemon is not compatible MIPS32 big-endian ELF")


def checked_path(root: Path, relative: str) -> Path:
    """Never inspect or mutate an image path through an external directory link."""
    parts=Path(relative).parts
    require(parts and not Path(relative).is_absolute() and ".." not in parts,
            "Unsafe image-relative path")
    current=root
    for part in parts[:-1]:
        current=current/part
        require(not current.is_symlink(),
                "Image path traverses a symlink directory: "+relative)
    return root/relative


def lean_login_profile(root: Path):
    """Remove only the audited vendor alias for the intentionally omitted MTR."""
    path=checked_path(root,LEAN_LOGIN_PROFILE)
    if not path.exists():
        require(not path.is_symlink(),"Broken login profile link")
        return None
    require(path.is_file() and not path.is_symlink(),
            "Unsupported login profile path")
    before=path.read_bytes()
    try:
        text=before.decode("utf-8")
    except UnicodeError as exc:
        raise ProfileError("Unsupported login profile encoding") from exc
    lines=text.splitlines(keepends=True)
    matching=[line for line in lines if line.rstrip("\r\n")==LEAN_LOGIN_ALIAS]
    require(len(matching)<=1,"Ambiguous MTR login aliases")
    if not matching:
        return None
    after="".join(line for line in lines if line not in matching).encode("utf-8")
    return {
        "path":LEAN_LOGIN_PROFILE,
        "operation":"remove-audited-mtr-alias",
        "sha256_before":hashlib.sha256(before).hexdigest(),
        "sha256_after":hashlib.sha256(after).hexdigest(),
        "bytes_before":len(before),"bytes_after":len(after),
    }


def lean_source_text(path: Path, relative: str, edits):
    data=path.read_bytes()
    if b"\0" in data:
        return None
    # Latin-1 preserves ASCII command names in otherwise non-UTF8 shell text.
    text=data.decode("latin-1")
    if relative==LEAN_LOGIN_PROFILE and edits:
        text="".join(line for line in text.splitlines(keepends=True)
                     if line.rstrip("\r\n")!=LEAN_LOGIN_ALIAS)
    return text


def verify_lean_runtime_closure(root: Path, edits=None):
    """Check retained ELF, scripts, embedded library names and symlink targets.

    This is deliberately conservative static evidence. Dynamically constructed
    names, optional OLT behavior and hardware recovery still need qualification.
    """
    removed=set(PROFILES["prx126-runtime-lean"])
    removed_libraries={Path(x).name for x in PRX126_LEAN_LIBRARIES}
    commands={Path(x).name for x in PRX126_LEAN_COMMANDS}|{"nano"}
    long_commands={x for x in commands if len(x)>2}
    library_pattern=re.compile(r"(?<![A-Za-z0-9_])(?:"+
                               "|".join(re.escape(x) for x in
                                        sorted(removed_libraries,key=len,reverse=True))+
                               r")(?![A-Za-z0-9_.])")
    # A '-' boundary is significant in shell defaults such as ${ZCAT:-zstdcat}.
    command_pattern=re.compile(r"(?<![A-Za-z0-9_])(?:"+
                               "|".join(re.escape(x) for x in
                                        sorted(long_commands,key=len,reverse=True))+
                               r")(?![A-Za-z0-9_-])")
    short_commands=commands-long_commands
    short_pattern=re.compile(r"(?:^|[;|&()]|\bexec\s+|\bcommand\s+)\s*(?:"+
                             "|".join(re.escape(x) for x in sorted(short_commands))+
                             r")(?=\s|[;|&()]|$)",re.MULTILINE)
    absolute_pattern=re.compile(r"/(?:usr/)?(?:s?bin)/(?:"+
                                "|".join(re.escape(x) for x in
                                         sorted(commands,key=len,reverse=True))+
                                r")(?![A-Za-z0-9_-])")
    needed_pattern=re.compile(r"\(NEEDED\)\s+Shared library:\s+\[([^\]]+)\]")
    scanned=0
    sources=0
    symlinks=0
    files=sorted(root.rglob("*"))
    for path in files:
        relative=path.relative_to(root).as_posix()
        if relative in removed:
            continue
        checked_path(root,relative)
        if path.is_symlink():
            target=os.readlink(path)
            destination=posixpath.normpath(
                target.lstrip("/") if target.startswith("/")
                else posixpath.join(posixpath.dirname(relative),target))
            require(destination not in removed,
                    "Retained symlink targets a pruned path: "+relative)
            symlinks+=1
            continue
        if not path.is_file():
            continue
        with path.open("rb") as stream:
            header=stream.read(4)
        if header==b"\x7fELF" and not relative.startswith("lib/modules/"):
            result=subprocess.run(
                ["/usr/bin/readelf","--dynamic","--wide",str(path)],
                capture_output=True,text=True,timeout=12,check=False)
            require(result.returncode==0,
                    "Cannot inspect retained ELF: "+relative)
            scanned+=1
            require(not (set(needed_pattern.findall(result.stdout)) & removed_libraries),
                    "Retained ELF requires pruned shared library: "+relative)
            # Include likely dlopen names, which are absent from DT_NEEDED.
            binary=path.read_bytes()
            require(not any(name.encode("ascii")+b"\0" in binary
                            for name in removed_libraries),
                    "Retained ELF embeds a pruned library name: "+relative)
            require(not any(("/"+command).encode("ascii")+b"\0" in binary
                            for command in removed if "/bin/" in command or "/sbin/" in command),
                    "Retained ELF embeds a pruned command path: "+relative)
            continue
        text=lean_source_text(path,relative,edits)
        if text is None:
            continue
        sources+=1
        shell_source=(header.startswith(b"#!") or path.suffix==".sh" or
                      path.name in (".profile","profile"))
        require(not (command_pattern.search(text) or
                     (shell_source and short_pattern.search(text)) or
                     absolute_pattern.search(text)),
                "Retained source refers to a pruned utility: "+relative)
        require(not library_pattern.search(text),
                "Retained source refers to a pruned library: "+relative)
    require(scanned>=1,"No surviving ELF files were audited")
    return {"elf_objects_scanned":scanned,"text_files_scanned":sources,
            "retained_symlinks_checked":symlinks,
            "hardware_qualified":False,
            "limitations":"Static checks cannot prove dynamically constructed or conditional runtime dependencies."}


def profile_plan(root: Path, profile: str, acknowledge: bool = False):
    root=safe_root(root)
    require(profile in PROFILES, "Unknown pruning profile")
    verify_family(root)
    require(profile!="experimental-no-libssl" or acknowledge,
            "Experimental libssl removal requires an explicit risk acknowledgement")
    if profile!="documentation-free":
        menu_path=root/"usr/share/luci/menu.d/luci-mod-status.json"
        require(menu_path.is_file() and not menu_path.is_symlink(),
                "Cannot verify conditional wireless status route")
        menu=json.loads(menu_path.read_text())
        wireless=menu.get("admin/status/realtime/wireless")
        require(isinstance(wireless,dict) and
                wireless.get("action",{}).get("path")=="status/wireless" and
                wireless.get("depends",{}).get("uci",{}).get("wireless",{}).get("@wifi-device") is True,
                "Wireless status view is not safely hidden by a conditional menu route")
        require(not (root/"etc/config/wireless").exists(),
                "Source contains wireless configuration; PRX126 compact profile is not applicable")
        view=root/"www/luci-static/resources/view/status/wireless.js"
        require(view.is_file() and
                "wireless.svg" in view.read_text() and
                "wifirate.svg" in view.read_text(),
                "Wireless status SVG dependency assumptions changed")
    edits=[]
    closure=None
    if profile == "prx126-runtime-lean":
        login_edit=lean_login_profile(root)
        if login_edit:
            edits.append(login_edit)
        closure=verify_lean_runtime_closure(root,edits)
    removals=[]
    for rel in PROFILES[profile]:
        require(rel not in PROTECTED,"Cannot remove protected runtime dependency")
        target=checked_path(root,rel)
        require(target.is_file() or target.is_symlink(),
                "Expected optional file absent or changed: "+rel)
        if target.is_symlink():
            link=os.readlink(target)
            require(not Path(link).is_absolute() and
                    ".." not in Path(link).parts and target.is_file(),
                    "Unsafe or broken optional symlink: "+rel)
            resolved=target.resolve(strict=True)
            require(root in resolved.parents and
                    resolved.relative_to(root).as_posix() in PROFILES[profile],
                    "Optional symlink does not resolve to a pruned file: "+rel)
            removals.append({
                "path":rel, "kind":"symlink", "link_target":link,
                "uncompressed_bytes":0, "sha256":sha_file(target)
            })
        else:
            removals.append({
                "path":rel, "kind":"file",
                "uncompressed_bytes":target.stat().st_size,
                "sha256":sha_file(target)
            })
    # The release profile is a *runtime* integrity contract, not documentation.
    # An experimental profile must not leave a false pin for a removed asset.
    profile_data=(root/"lib/8311-release-profile").read_text()
    for line in profile_data.splitlines():
        parts=line.split()
        if len(parts)>=3 and parts[0] in ("file","link"):
            require(parts[2] not in PROFILES[profile] or
                    (profile=="experimental-no-libssl" and
                     line.startswith(PIN_LINE_PREFIX)),
                    "Pruned path is still pinned by runtime integrity profile: "+parts[2])
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
        "source_edits":edits,
        "static_dependency_checks":closure,
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
        # Validate the complete copied input before deleting symlink targets.
        for obj in plan["pruned"]:
            candidate=checked_path(dst,obj["path"])
            if obj["kind"]=="symlink":
                require(candidate.is_symlink() and
                        os.readlink(candidate)==obj["link_target"],
                        "Copied optional symlink changed: "+obj["path"])
                resolved=candidate.resolve(strict=True)
                require(dst in resolved.parents and
                        resolved.relative_to(dst).as_posix() in PROFILES[profile],
                        "Copied optional symlink target changed: "+obj["path"])
            else:
                require(not candidate.is_symlink(),
                        "Copied optional file became a symlink: "+obj["path"])
            require(candidate.is_file() and sha_file(candidate)==obj["sha256"],
                    "Copied source file unexpectedly changed: "+obj["path"])
        for edit in plan["source_edits"]:
            candidate=checked_path(dst,edit["path"])
            require(sha_file(candidate)==edit["sha256_before"],
                    "Copied login profile unexpectedly changed")
            lines=candidate.read_bytes().splitlines(keepends=True)
            updated=b"".join(line for line in lines
                             if line.rstrip(b"\r\n")!=LEAN_LOGIN_ALIAS.encode("ascii"))
            require(hashlib.sha256(updated).hexdigest()==edit["sha256_after"],
                    "Unexpected login alias transformation")
            candidate.write_bytes(updated)
        for obj in plan["pruned"]:
            rel=obj["path"]
            candidate=checked_path(dst,rel)
            if obj["kind"] == "symlink":
                require(candidate.is_symlink() and
                        os.readlink(candidate) == obj["link_target"],
                        "Copied optional symlink changed: "+rel)
            else:
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
            require(not os.path.lexists(dst/obj["path"]),
                    "Pruned path remains: "+obj["path"])
        if profile=="prx126-runtime-lean":
            plan["static_dependency_checks"]=verify_lean_runtime_closure(dst)
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
