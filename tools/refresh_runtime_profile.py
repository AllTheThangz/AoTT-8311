#!/usr/bin/env python3
"""Verify an offline 8311 runtime profile, or refresh reviewed overlay pins.

Only candidate file records explicitly present in the current sanitized source
manifest may be repinned, and only when their exact bytes and sizes match that
manifest. Common files, links, vendor OMCI, kernel, bootcore and unrelated
candidate records remain protected. Never run against a mounted live rootfs.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import tempfile


# The qualified component identities for this specific PRX126 vendor ABI.
# Cross-board firmware must use a new separately reviewed compatibility profile.
QUALIFIED_COMPONENTS = {
    "kernel": ("2274800",
               "d66b24cf873cc1071a3aa2d155bf677f503f10d221513e469083f8a591f6b96c"),
    "bootcore": ("5426656",
                 "e99e25332bdcb3c9b0447abad1be9b1e54511b6bda99f2b51ae2499db5b905a4"),
}


class RuntimeProfileError(ValueError):
    pass


def require(value, reason):
    if not value:
        raise RuntimeProfileError(reason)


def digest(file: Path):
    with file.open("rb") as stream:
        h=hashlib.sha256()
        for part in iter(lambda:stream.read(1024*1024), b""):
            h.update(part)
    return h.hexdigest()


def safe_root(path: Path):
    p=Path(path).absolute()
    require(not p.is_symlink(), "Offline image path cannot be a symlink")
    result=p.resolve(strict=True)
    require(result.is_dir() and result!=Path("/"),
            "Offline image must be a separate local directory")
    for path in ("/etc","/proc","/sys","/dev","/root","/ptconf","/home"):
        protected=Path(path)
        require(result!=protected and protected not in result.parents,
                "Refusing a potentially live filesystem")
    return result


def validate_relative(root: Path, rel: str):
    require(bool(re.fullmatch(r"[A-Za-z0-9_./+-]+",rel)) and
            not rel.startswith("/") and ".." not in Path(rel).parts,
            "Invalid runtime profile path")
    candidate=root/rel
    require(all(not (root/Path(*candidate.relative_to(root).parts[:i])).is_symlink()
                for i in range(1,len(candidate.relative_to(root).parts))),
            "Untrusted symlink path in offline source")
    return candidate


def overlay_allowlist(manifest: Path):
    data=json.loads(Path(manifest).read_text())
    require(data.get("source_only") is True and
            data.get("firmware_binaries_included") is False,
            "Source manifest is not an approved source-only overlay")
    result={}
    for row in data["overlay_files"]:
        rel=row["path"]
        require(rel not in result,"Duplicate overlay entry")
        require(re.fullmatch(r"[A-Za-z0-9_./+-]+",rel) is not None
                and not rel.startswith("/") and ".." not in Path(rel).parts,
                "Invalid source path")
        require(re.fullmatch("[a-f0-9]{64}",row["sha256"]) is not None
                and 0<row["bytes"]<1048576,"Malformed overlay manifest entry")
        result[rel]=(row["bytes"],row["sha256"])
    require(len(result)>0,"Empty source manifest")
    return result


def assess(root: Path, manifest: Path):
    root=safe_root(root)
    path=root/"lib/8311-release-profile"
    require(path.is_file() and not path.is_symlink(),
            "Offline runtime profile missing")
    text=path.read_text()
    require(text.startswith("profile potron-prx126-aott-v1\n"),
            "Unrecognized board profile")
    require(text.count("\nprofile ")==0,"Duplicated profile header")
    lines_header=text.splitlines()
    require(lines_header.count("target WAS-110")==1 and
            lines_header.count("variant basic")==1,
            "Unqualified firmware target or variant")
    components={}
    for line in lines_header:
        if line.startswith("component "):
            parts=line.split()
            require(len(parts)==4 and parts[1] not in components,
                    "Malformed component profile")
            components[parts[1]]=(parts[2],parts[3])
    require(components==QUALIFIED_COMPONENTS,
            "Kernel or bootcore compatibility profile differs from qualified ABI")
    allowed=overlay_allowlist(manifest)
    lines=text.splitlines(keepends=True)
    changed=[]
    entries=0
    errors=[]
    output=[]
    seen=set()
    for line in lines:
        parts=line.strip().split()
        if not parts:
            output.append(line);continue
        kind=parts[0]
        if kind in ("profile","target","variant","component"):
            output.append(line);continue
        require(kind in ("file","link") and
                len(parts)==(5 if kind=="file" else 4),
                "Malformed runtime profile record")
        _,scope,rel,*others=parts
        require(scope in ("common","candidate"),"Unknown runtime profile scope")
        require(rel not in seen,"Duplicate runtime profile record")
        seen.add(rel)
        file=validate_relative(root,rel)
        entries+=1
        if kind=="link":
            require(file.is_symlink() and str(file.readlink())==others[0],
                    "Runtime symlink does not match pinned profile: "+rel)
            output.append(line);continue
        size_str,sha=others
        require(size_str.isascii() and size_str.isdecimal() and
                not size_str.startswith("0") and
                re.fullmatch(r"[a-f0-9]{64}",sha) is not None,
                "Malformed runtime file record")
        require(file.is_file() and not file.is_symlink(),
                "Missing required runtime file: "+rel)
        actual=(file.stat().st_size,digest(file))
        declared=(int(size_str),sha)
        if actual==declared:
            output.append(line);continue
        if scope!="candidate" or rel not in allowed or actual!=allowed[rel]:
            errors.append(rel)
            output.append(line)
            continue
        changed.append(rel)
        output.append("file candidate "+rel+" "+str(actual[0])+" "+actual[1]+"\n")
    require(entries>=11,"Suspiciously short runtime profile")
    require(not errors,"Protected or unapproved runtime pin mismatch: "+
            ", ".join(sorted(errors)[:9]))
    return {
        "root":root,
        "file":path,
        "old_sha256":digest(path),
        "old_text":text,
        "refreshed_text":"".join(output),
        "candidate_entries_refreshed":sorted(changed),
        "candidate_entries_refreshed_count":len(changed),
        "checked_entries":entries,
        "verified":len(errors)==0,
    }


def run(root,manifest,refresh=False):
    report=assess(root,manifest)
    target=report["file"]
    if refresh and report["refreshed_text"]!=report["old_text"]:
        original=target.stat()
        directory=target.parent
        with tempfile.NamedTemporaryFile(mode="w",prefix=".profile.",
                                         suffix=".new",dir=directory,
                                         encoding="utf-8",delete=False) as stream:
            staging=Path(stream.name)
            stream.write(report["refreshed_text"])
            stream.flush()
            os.fsync(stream.fileno())
        try:
            staging.chmod(original.st_mode & 0o7777)
            os.utime(staging,ns=(original.st_atime_ns,original.st_mtime_ns))
            os.replace(staging,target)
            # Re-read every pinned element after the atomic profile change.
            verified=assess(root,manifest)
            require(verified["candidate_entries_refreshed_count"]==0,
                    "Post-refresh profile still has stale pins")
        finally:
            staging.unlink(missing_ok=True)
    return {
        "schema":1,
        "source_only":True,
        "status":"refreshed" if refresh else "reviewed",
        "refreshed":refresh,
        "runtime_profile_records":report["checked_entries"],
        "reviewed_changed_paths":report["candidate_entries_refreshed"],
        "changed_path_count":report["candidate_entries_refreshed_count"],
        "profile_sha256_before":report["old_sha256"],
        "profile_sha256_after":digest(target),
        "hardware_qualified":False,
        "note":"Offline integrity update only. Does not authorize any firmware flash."
    }


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--rootfs",required=True,type=Path)
    p.add_argument("--source-manifest",required=True,type=Path)
    p.add_argument("--refresh-reviewed-candidate-pins",action="store_true")
    args=p.parse_args()
    try:
        report=run(args.rootfs,args.source_manifest,
                   args.refresh_reviewed_candidate_pins)
    except (RuntimeProfileError,ValueError,OSError) as exc:
        print(json.dumps({"status":"rejected","reason":str(exc)},sort_keys=True))
        return 1
    print(json.dumps(report,sort_keys=True,indent=2))
    return 0


if __name__=="__main__":
    sys.exit(main())
