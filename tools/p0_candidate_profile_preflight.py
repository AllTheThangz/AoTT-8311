#!/usr/bin/env python3
"""P0 preflight: detect a cross-version runtime-profile mismatch BEFORE flashing.

This host-side tool is read-only. It is NOT an authorization to flash; a passing
candidate image must still meet the independent board/vendor compatibility
profile, credential-preservation and device-side qualification requirements.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys

MAX_PROFILE=65536
SHARED={"profile","target","variant","component"}

def entries(raw):
    if not isinstance(raw,(bytes,bytearray)) or len(raw)>MAX_PROFILE or not raw:
        raise ValueError("profile_size_invalid")
    try: data=raw.decode("utf-8")
    except UnicodeDecodeError: raise ValueError("profile_encoding_invalid")
    if "\r" in data or "\x00" in data or not data.endswith("\n"):
        raise ValueError("profile_line_format_invalid")
    rows=[]; keys=set()
    for line in data.splitlines():
        words=line.split()
        if not words: raise ValueError("empty_profile_line")
        kind=words[0]
        if kind in SHARED and len(words)!=(2 if kind in ("profile","target","variant") else 4):
            raise ValueError("profile_header_invalid")
        if kind in ("file","link") and len(words)!=5:
            if not (kind=="link" and len(words)==4):
                raise ValueError("profile_entry_invalid")
        if kind not in (SHARED|{"file","link"}):raise ValueError("profile_record_invalid")
        key=(kind,words[1] if kind in SHARED else (words[1],words[2]))
        if key in keys:raise ValueError("profile_duplicate_record")
        keys.add(key)
        rows.append((kind,words))
    return rows

def shared_contract(raw):
    result=[]
    for kind,words in entries(raw):
        if kind in SHARED or (kind in ("file","link") and words[1]=="common"):
            result.append(" ".join(words))
    return sorted(result)

def check(installed, reviewed, image):
    installed_rows=entries(installed)
    reviewed_rows=entries(reviewed)
    embedded_rows=entries(image)
    if image != reviewed:
        raise ValueError("image_embedded_profile_differs_from_reviewed_candidate")
    if shared_contract(installed)!=shared_contract(reviewed):
        raise ValueError("protected_common_or_hardware_contract_changed")
    old_candidates={tuple(words[:3]):" ".join(words) for kind,words in installed_rows if kind in ("file","link") and words[1]=="candidate"}
    new_candidates={tuple(words[:3]):" ".join(words) for kind,words in reviewed_rows if kind in ("file","link") and words[1]=="candidate"}
    changes=sum(old_candidates.get(k)!=new_candidates.get(k) for k in set(old_candidates)|set(new_candidates))
    return {"status":"P0_CANDIDATE_RUNTIME_PROFILE_REVIEW_PASS",
        "same_candidate_runtime_pins":changes==0,
        "candidate_runtime_changed_records":changes,
        "requires_version_aware_device_qualification":changes>0,
        "device_write_performed":False,
        "profile_sha256":hashlib.sha256(reviewed).hexdigest(),
        "board_and_common_pins_match":True}

def bounded_file(path):
    if path.is_symlink() or not path.is_file() or path.stat().st_size>MAX_PROFILE:
        raise ValueError("profile_file_untrusted")
    return path.read_bytes()

def embedded(image):
    if image.is_symlink() or not image.is_file() or image.stat().st_size>33554432:
        raise ValueError("candidate_image_untrusted")
    if not shutil.which("unsquashfs"):raise ValueError("unsquashfs_unavailable")
    p=subprocess.run(["unsquashfs","-cat",str(image),"lib/8311-release-profile"],
                     stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,timeout=25,check=False)
    if p.returncode!=0 or len(p.stdout)>MAX_PROFILE:raise ValueError("embedded_profile_unavailable")
    return p.stdout

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--installed-profile",required=True,type=Path)
    p.add_argument("--reviewed-profile",required=True,type=Path)
    p.add_argument("--candidate-squashfs",required=True,type=Path)
    args=p.parse_args()
    try:
        result=check(bounded_file(args.installed_profile),
                     bounded_file(args.reviewed_profile),embedded(args.candidate_squashfs))
        print(json.dumps(result,indent=2,sort_keys=True))
    except (OSError,ValueError,subprocess.TimeoutExpired) as e:
        print(json.dumps({"status":"P0_CANDIDATE_PROFILE_REJECTED",
            "reason":str(e)[:128],"device_write_performed":False},
            sort_keys=True),file=sys.stderr)
        raise SystemExit(1)
if __name__=="__main__":main()
