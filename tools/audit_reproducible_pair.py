#!/usr/bin/env python3
"""Compare two independent private firmware builds against one sanitized source.

Read-only. Refuses symlinks, source drift, noncanonical tar members and
unqualified rootfs/capacity. Produces a checksum-based evidence receipt,
NOT a cryptographic signature or hardware qualification. No device I/O.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import struct
import tarfile

from release_identity import load_release
from verify_release import check as check_source

PIN_KERNEL = (2274800, "d66b24cf873cc1071a3aa2d155bf677f503f10d221513e469083f8a591f6b96c")
PIN_BOOTCORE = (5426656, "e99e25332bdcb3c9b0447abad1be9b1e54511b6bda99f2b51ae2499db5b905a4")
VOLUME_CAPACITY = 6221824
MINIMUM_HEADROOM = 65536
MEMBERS = ("upgrade.sh", "control", "kernel.bin", "bootcore.bin", "rootfs.img")


class ProvenanceError(ValueError):
    pass


def require(check, message):
    if not check:
        raise ProvenanceError(message)


def private_file(path: Path, maximum: int):
    path = Path(path)
    require(path.is_file() and not path.is_symlink(), "Regular nonsymlink input required")
    require(0 < path.stat().st_size <= maximum, "Input exceeds size bounds")
    return path


def independent_files(path_a, path_b, maximum):
    a = private_file(Path(path_a), maximum)
    b = private_file(Path(path_b), maximum)
    left = a.stat()
    right = b.stat()
    require(a.resolve() != b.resolve() and
            (left.st_dev, left.st_ino) != (right.st_dev, right.st_ino),
            "Independent builds must be different regular files, not aliases")
    return (a, b)


def hash_file(path: Path):
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1048576), b""):
            h.update(block)
    return h.hexdigest()


def read_qualification(path):
    path = private_file(Path(path), 65536)
    data = json.loads(path.read_text(), object_pairs_hook=_unique_object)
    require(isinstance(data, dict) and data.get("schema") == 1,
            "Invalid offline qualification record")
    return data


def _unique_object(pairs):
    result = {}
    for k, v in pairs:
        require(k not in result, "Duplicate qualification JSON member")
        result[k] = v
    return result


def validate_tar(path, expected_components, epoch, expected_archive_hash):
    path = private_file(Path(path), 134217728)
    require(hash_file(path) == expected_archive_hash, "Firmware archive digest mismatch")
    with path.open("rb") as f:
        f.seek(257)
        require(f.read(6) == b"ustar\x00", "Non-USTAR archive format")
    with tarfile.open(path, mode="r:") as archive:
        members = archive.getmembers()
        require([m.name for m in members] == list(MEMBERS),
                "Archive contains missing, extra or reordered members")
        for member in members:
            require(member.isfile() and not member.issym() and not member.islnk(),
                    "Nonregular firmware archive member")
            require(member.uid == member.gid == 0 and
                    member.uname == member.gname == "root" and
                    member.mtime == epoch and
                    member.mode == (0o755 if member.name == "upgrade.sh" else 0o644),
                    "Noncanonical private archive member metadata")
            expected = expected_components.get(member.name)
            require(isinstance(expected, dict), "Unpinned archive member")
            require(member.size == expected["bytes"],
                    "Archive member size differs from qualified image")
            stream = archive.extractfile(member)
            require(stream is not None, "Cannot inspect member bytes")
            digest = hashlib.sha256()
            for part in iter(lambda: stream.read(1048576), b""):
                digest.update(part)
            require(digest.hexdigest() == expected["sha256"],
                    "Archive member digest differs from qualification")
    return True


def audit(source, qual_a, qual_b, archive_a, archive_b, rootfs_a, rootfs_b):
    source = Path(source)
    require(source.is_dir() and not source.is_symlink(),
            "Canonical sanitized source directory required")
    spec = load_release(source)
    require(spec["hardware_profile"] == "potron-prx126-aott-v1" and
            spec["target"] == "WAS-110", "Unsupported board profile")
    _, findings = check_source(source)
    require(not findings, "Sanitized source manifest/disclosure gate rejected")
    independent_files(qual_a, qual_b, 65536)
    independent_files(archive_a, archive_b, 134217728)
    independent_files(rootfs_a, rootfs_b, VOLUME_CAPACITY)
    qa = read_qualification(qual_a)
    qb = read_qualification(qual_b)
    require(qa == qb, "Independent qualification receipts differ")
    require(qa.get("status") == "UNTRIALED_OFFLINE_ONLY" and
            qa.get("hardware_qualified") is False and
            qa.get("safe_for_live_install") is False and
            qa.get("archive_reproducible") is True,
            "Unsafe or incorrectly labeled candidate")
    require(qa.get("release") == spec["release"] and
            qa.get("revision") == spec["revision"] and
            qa.get("compatibility_profile") == spec["hardware_profile"] and
            qa.get("target") == spec["target"] and
            qa.get("variant") == spec["variant"], "Release identity mismatch")
    require(qa.get("source_manifest_sha256") == hash_file(
            private_file(source / "MANIFEST.json", 1048576)) and
            qa.get("canonical_release_sha256") == hash_file(
            private_file(source / "release.json", 65536)),
            "Source changed after the reproducible build")
    checks = qa.get("checks")
    require(isinstance(checks, dict) and all(checks.get(k) == "passed" for k in
            ("component_sha256", "control_identity", "five_member_ustar",
             "squashfs_superblock", "volume_capacity", "zero_padding")),
            "Missing private qualification checks")
    components = qa.get("sha256_components")
    require(isinstance(components, dict) and set(components) == set(MEMBERS),
            "Unexpected firmware archive component set")
    for name, expected in (("kernel.bin", PIN_KERNEL),
                           ("bootcore.bin", PIN_BOOTCORE)):
        require(components[name] == {"bytes": expected[0], "sha256": expected[1]},
                "Unqualified kernel or bootcore ABI")
    volume = qa.get("rootfs")
    require(isinstance(volume, dict) and
            volume.get("target_volume_capacity") == VOLUME_CAPACITY and
            volume.get("compression") == "xz" and
            volume.get("filesystem") == "squashfs4" and
            volume.get("block_size") == 1048576,
            "Unknown flash or compression profile")
    extent = components["rootfs.img"]["bytes"]
    require(type(extent) is int and extent == volume.get("image_extent") and
            extent % 4096 == 0 and
            VOLUME_CAPACITY - extent == volume.get("headroom_bytes") and
            volume["headroom_bytes"] >= MINIMUM_HEADROOM,
            "Unqualified rootfs bank capacity")
    require(qa.get("build_epoch") is not None and
            type(qa["build_epoch"]) is int and 0 <= qa["build_epoch"] <= 0xFFFFFFFF,
            "Invalid deterministic build epoch")
    for img in (rootfs_a, rootfs_b):
        img = private_file(Path(img), VOLUME_CAPACITY)
        require(img.stat().st_size == extent and
                hash_file(img) == components["rootfs.img"]["sha256"],
                "Rootfs independent build differs from archive receipt")
        with img.open("rb") as f:
            header = f.read(96)
        require(header[:4] == b"hsqs" and
                struct.unpack_from("<Q", header, 40)[0] == volume["bytes_used"] and
                0 < volume["bytes_used"] <= extent,
                "SquashFS superblock differs from qualification")
    archive_name = spec["release"] + "-UNTRIALED-local-upgrade.tar"
    require(qa.get("archive") == archive_name and
            type(qa.get("archive_bytes")) is int and qa["archive_bytes"] > 0,
            "Incorrect release archive name or length")
    for archive in (archive_a, archive_b):
        archive = private_file(Path(archive), 134217728)
        require(archive.name == archive_name and
                archive.stat().st_size == qa["archive_bytes"],
                "Archive filename or length mismatch")
        validate_tar(archive, components, qa["build_epoch"], qa["archive_sha256"])
    return {
        "schema": 1,
        "status": "PRIVATE_INDEPENDENT_RELEASE_PAIR_REPRODUCIBLE",
        "release": spec["release"],
        "compatibility_profile": spec["hardware_profile"],
        "archive_sha256": qa["archive_sha256"],
        "rootfs_sha256": components["rootfs.img"]["sha256"],
        "kernel_abi_sha256": components["kernel.bin"]["sha256"],
        "bootcore_abi_sha256": components["bootcore.bin"]["sha256"],
        "rootfs_image_extent": extent,
        "rootfs_flash_headroom_bytes": volume["headroom_bytes"],
        "two_independent_squashfs_images_match": True,
        "two_independent_private_archives_match": True,
        "source_manifest_unchanged_since_build": True,
        "unsigned_checksum_evidence_only": True,
        "signed_attestation": False,
        "hardware_qualified": False,
        "safe_for_live_install": False,
        "production_device_modified": False
    }


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--source", required=True, type=Path)
    p.add_argument("--qualification-a", required=True, type=Path)
    p.add_argument("--qualification-b", required=True, type=Path)
    p.add_argument("--archive-a", required=True, type=Path)
    p.add_argument("--archive-b", required=True, type=Path)
    p.add_argument("--rootfs-a", required=True, type=Path)
    p.add_argument("--rootfs-b", required=True, type=Path)
    p.add_argument("--report", type=Path)
    args = p.parse_args()
    record = audit(args.source, args.qualification_a, args.qualification_b,
                   args.archive_a, args.archive_b, args.rootfs_a, args.rootfs_b)
    if args.report:
        target = args.report
        require(not target.exists() and not target.is_symlink(),
                "Evidence report must use a new path")
        with target.open("x", encoding="utf-8") as f:
            json.dump(record, f, indent=2, sort_keys=True)
            f.write("\n")
    else:
        print(json.dumps(record, indent=2, sort_keys=True))


if __name__ == "__main__":
    try:
        main()
    except (ProvenanceError, OSError, ValueError, KeyError, tarfile.TarError) as error:
        raise SystemExit("REPRODUCIBLE_PAIR_REJECTED: " + str(error)[:200])
