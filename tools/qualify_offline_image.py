#!/usr/bin/env python3
"""Read-only offline AoTT-8311 upgrade-archive verifier.

Verifies component hashes, five-member archive shape, SquashFS v4/XZ
superblock layout and UBI capacity, without extraction or device access.
Does NOT claim bootability, PON compatibility or authenticity of firmware.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import struct
import sys
import tarfile

MEMBERS=("upgrade.sh","control","kernel.bin","bootcore.bin","rootfs.img")
ROOTFS_MIN=96
ROOTFS_MAX=33554432
MAX_MEMBER={
    "upgrade.sh":131072,
    "control":4096,
    "kernel.bin":8388608,
    "bootcore.bin":16777216,
    "rootfs.img":ROOTFS_MAX,
}
EXPECTED_COMPRESSION=4
EXPECTED_BLOCK=1048576
VALID_SHA=re.compile(r"^[0-9a-f]{64}$")


class QualificationError(ValueError):
    pass


def require(condition, message):
    if not condition:
        raise QualificationError(message)


def checksum(stream, size):
    digest=hashlib.sha256()
    remaining=size
    while remaining:
        block=stream.read(min(262144,remaining))
        require(bool(block),"Truncated archive component")
        digest.update(block)
        remaining-=len(block)
    return digest.hexdigest()


def parse_control(content):
    require(0 < len(content) <= MAX_MEMBER["control"],"Invalid control size")
    try:
        lines=content.decode("ascii").splitlines()
    except UnicodeDecodeError as exc:
        raise QualificationError("Control is not ASCII") from exc
    result={}
    for line in lines:
        if not line.strip():
            continue
        require("=" in line,"Malformed control field")
        name,value=line.split("=",1)
        require(bool(re.fullmatch(r"[A-Z_][A-Z0-9_]*",name)),
                "Malformed control field name")
        require(name not in result,"Duplicate control field")
        require("\x00" not in value and "\r" not in value,
                "Invalid control value")
        require(len(value) <= 160,"Oversized control value")
        result[name]=value
    required=set()
    for part in ("KERNEL","BOOTCORE","ROOTFS"):
        required.update(("SIZE_"+part,"SHA256_"+part))
    require(required.issubset(result),"Missing size/hash control fields")
    require(result.get("FW_VERSION","").startswith("AoTT-8311-"),
            "Incorrect firmware family")
    return result


def superblock(data,extent,capacity):
    require(len(data)==96,"Short SquashFS superblock")
    require(data[:4]==b"hsqs","Incorrect filesystem magic")
    u16=lambda offset: struct.unpack_from("<H",data,offset)[0]
    u32=lambda offset: struct.unpack_from("<I",data,offset)[0]
    u64=lambda offset: struct.unpack_from("<Q",data,offset)[0]
    major,minor=u16(28),u16(30)
    require((major,minor)==(4,0),"Unsupported SquashFS version")
    require(u16(20)==EXPECTED_COMPRESSION,
            "Incorrect SquashFS compressor; expected XZ")
    log=u16(22)
    require(12<=log<=20 and u32(12)==(1<<log)==EXPECTED_BLOCK,
            "Incorrect SquashFS block geometry")
    used=u64(40)
    require(ROOTFS_MIN<=used<=extent<=capacity,
            "Root filesystem exceeds image extent or target UBI volume")
    require(extent-used<=4095,
            "Image has more than 4095 trailing padding bytes")
    inodes,fragments,ids=u32(4),u32(16),u16(26)
    require(1<=inodes<=1048576 and fragments<=inodes and ids>=1,
            "Invalid SquashFS inode/fragment/ID counts")
    flags=u16(24)
    require(flags < 4096,"Unrecognized SquashFS features")
    def pointer(offset,optional=False):
        x=u64(offset)
        if optional and x==(2**64-1):
            return None
        require(96<=x<used, "Invalid SquashFS table pointer")
        return x
    id_table=pointer(48)
    xattr=pointer(56,True)
    inode=pointer(64)
    directory=pointer(72)
    fragment=pointer(80,True)
    lookup=pointer(88,True)
    require(inode<directory<=id_table,"Invalid metadata table ordering")
    require(id_table+((ids+2047)//2048)*8<=used,
            "ID table exceeds compressed filesystem")
    if fragments:
        require(fragment is not None and fragment>=directory and
                fragment+((fragments+511)//512)*8<=used,
                "Invalid SquashFS fragment table")
    if flags&128:
        require(lookup is not None,"Missing export table")
    if lookup is not None:
        require(lookup>=directory and
                lookup+((inodes+1023)//1024)*8<=used,
                "Invalid SquashFS export table")
    if xattr is not None:
        require(xattr+16<=used,"Truncated extended attributes")
    root_ref=u64(32)
    root_block=root_ref>>16
    root_offset=root_ref&0xffff
    require(root_offset<8192 and root_block < (directory-inode),
            "Root inode reference out of range")
    return {
        "filesystem":"squashfs4",
        "compression":"xz",
        "block_size":u32(12),
        "inodes":inodes,
        "bytes_used":used,
        "padding_bytes":extent-used,
        "image_extent":extent,
        "target_volume_capacity":capacity,
        "headroom_bytes":capacity-extent,
    }


def qualify_archive(path,capacity,min_headroom=32768,preferred_headroom=65536):
    path=Path(path)
    require(path.is_file() and not path.is_symlink(),
            "Input archive must be an existing regular file")
    require(1048576<=capacity<=ROOTFS_MAX,
            "Unsupported volume capacity")
    require(0<=min_headroom<=capacity and
            0<=preferred_headroom<=capacity,
            "Invalid reserved headroom")
    # This five-member firmware format requires strict USTAR headers.
    # Do not accept GNU or PAX extensions with hidden global metadata.
    with path.open("rb") as infile:
        magic=infile.read(512)[257:265]
    require(magic==b"ustar\x0000",
            "Archive does not use expected USTAR format")
    with tarfile.open(path,"r:") as tar:
        entries=tar.getmembers()
        require([e.name for e in entries]==list(MEMBERS),
                "Incorrect member order or unsupported archive contents")
        require(all(e.isfile() and not e.issym() and not e.islnk()
                    and e.uid==0 and e.gid==0 and not e.pax_headers
                    for e in entries),
                "Unexpected metadata or nonregular archive member")
        for entry in entries:
            require(0<entry.size<=MAX_MEMBER[entry.name],
                    "Component size exceeds offline safety limits")
        controls=tar.extractfile(entries[1])
        require(controls is not None,"Cannot open control")
        control=parse_control(controls.read(MAX_MEMBER["control"]+1))
        # No extraction, modifications or filesystem mounts.
        details={}
        root_info=None
        for entry in entries:
            source=tar.extractfile(entry)
            require(source is not None,"Cannot stream component")
            if entry.name=="rootfs.img":
                header=source.read(96)
                root_info=superblock(header,entry.size,capacity)
                digest=hashlib.sha256()
                digest.update(header)
                remaining=entry.size-96
                read_pos=96
                used=root_info["bytes_used"]
                while remaining:
                    block=source.read(min(262144,remaining))
                    require(bool(block),"Truncated rootfs image")
                    # A padded SquashFS extent must have zero padding.
                    if read_pos + len(block) > used:
                        offset=max(0,used-read_pos)
                        require(not any(block[offset:]),
                                "Nonzero SquashFS padding")
                    digest.update(block)
                    read_pos+=len(block)
                    remaining-=len(block)
                hexdigest=digest.hexdigest()
            else:
                hexdigest=checksum(source,entry.size)
            details[entry.name]={"bytes":entry.size,"sha256":hexdigest}
        assert root_info is not None
        for member,field in (("kernel.bin","KERNEL"),
                             ("bootcore.bin","BOOTCORE"),
                             ("rootfs.img","ROOTFS")):
            try:
                expected_size=int(control["SIZE_"+field])
            except (ValueError,OverflowError) as exc:
                raise QualificationError("Invalid component size in control") from exc
            expected_hash=control["SHA256_"+field]
            require(VALID_SHA.fullmatch(expected_hash) is not None,
                    "Invalid SHA256 in control")
            require(details[member]["bytes"]==expected_size,
                    "Component length differs from control")
            require(details[member]["sha256"]==expected_hash,
                    "Component hash differs from control")
        rootfs_headroom=root_info["headroom_bytes"]
        require(rootfs_headroom>=min_headroom,
                "Rootfs image leaves less than mandatory reserve")
        return {
            "schema":1,
            "status":"passed",
            "release":control["FW_VERSION"],
            "rootfs":root_info,
            "min_headroom_bytes":min_headroom,
            "preferred_headroom_bytes":preferred_headroom,
            "headroom_recommendation_met":rootfs_headroom>=preferred_headroom,
            "checks":{
                "five_member_ustar":"passed",
                "component_sha256":"passed",
                "squashfs_superblock":"passed",
                "zero_padding":"passed",
                "volume_capacity":"passed"
            },
            "sha256_components":details,
            "warning":("Below preferred headroom" if
                       rootfs_headroom<preferred_headroom else None),
            "hardware_qualified":False,
            "note":"Read-only image verification; does not prove firmware bootability."
        }


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive",required=True,
                        help="Offline five-member firmware tar (read-only)")
    parser.add_argument("--volume-bytes",required=True,type=int)
    parser.add_argument("--min-headroom",type=int,default=32768)
    parser.add_argument("--preferred-headroom",type=int,default=65536)
    args=parser.parse_args()
    try:
        result=qualify_archive(args.archive,args.volume_bytes,
                               args.min_headroom,args.preferred_headroom)
    except (QualificationError,OSError,tarfile.TarError) as exc:
        print(json.dumps({"status":"failed","reason":str(exc),
                          "hardware_qualified":False},sort_keys=True))
        return 1
    print(json.dumps(result,indent=2,sort_keys=True))
    return 0


if __name__=="__main__":
    sys.exit(main())
