#!/usr/bin/env python3
"""Copy verified text-source overlay into a NEW offline staging directory.

This tool never patches /, /etc, existing source trees or running devices.
It does not generate firmware images, network configuration, or credentials.
"""
import argparse
import json
import os
from pathlib import Path
import shutil
import stat
import sys

HERE=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(Path(__file__).resolve().parent))
from verify_release import check

def stage(destination,source=HERE):
    root=Path(source).resolve()
    destination=Path(destination).resolve()
    if destination.exists() or destination.is_symlink():
        raise ValueError("Destination already exists")
    if destination==root or root in destination.parents:
        raise ValueError("Do not stage over or inside the source checkout")
    if str(destination).startswith(("/etc/","/proc/","/sys/","/dev/","/ptconf/")):
        raise ValueError("Prohibited system path")
    count,findings=check(root)
    if findings:
        raise ValueError("Source security audit failed: "+str(len(findings))+" finding(s)")
    manifest=json.loads((root/"MANIFEST.json").read_text())
    destination.mkdir(mode=0o700,parents=False)
    try:
        for item in manifest["overlay_files"]:
            rel=Path(item["path"])
            if rel.is_absolute() or ".." in rel.parts:
                raise ValueError("Unsafe overlay path")
            source_file=root/"overlay"/rel
            assert source_file.is_file() and not source_file.is_symlink()
            target=destination/rel
            target.parent.mkdir(parents=True,exist_ok=True)
            with source_file.open("rb") as stream, target.open("xb") as out:
                shutil.copyfileobj(stream,out)
            target.chmod(0o755 if item["executable"] else 0o644)
        print("Offline text overlay staged: ",len(manifest["overlay_files"]),"files")
        print("Destination:",destination)
    except Exception:
        # The only data owned by this function is this newly created directory.
        shutil.rmtree(destination)
        raise

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--destination",required=True,help="NEW output directory (must not already exist)")
    args=parser.parse_args()
    stage(args.destination)

if __name__=="__main__":
    main()
