#!/usr/bin/env python3
"""Assemble and verify a private five-member firmware candidate offline.

The input SquashFS is independently extracted with unsquashfs. Source files,
release identity, runtime pins and the original kernel/bootcore are verified
before packing. No device connection, firmware write or boot action exists.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parent))
from release_identity import load_release, firmware_fields, assignments, check_rootfs
from refresh_runtime_profile import QUALIFIED_COMPONENTS, run as check_runtime
from qualify_offline_image import MAX_MEMBER, qualify_archive
from verify_release import check as check_source

SOURCE = Path(__file__).resolve().parent.parent


def digest(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(262144), b""):
            h.update(block)
    return h.hexdigest()


def regular(path):
    path = Path(path)
    if not path.is_file() or path.is_symlink():
        raise ValueError("A regular nonsymlink component file is required")
    return path.resolve()


def snapshot_component(source, destination, limit):
    """Make a bounded private snapshot used for both inspection and packing."""
    source = regular(source)
    with source.open("rb") as incoming, Path(destination).open("xb") as outgoing:
        metadata = os.fstat(incoming.fileno())
        if not stat.S_ISREG(metadata.st_mode) or not 0 < metadata.st_size <= limit:
            raise ValueError("Component exceeds its bounded regular-file contract")
        total = 0
        while True:
            data = incoming.read(min(262144, limit + 1 - total))
            if not data:
                break
            total += len(data)
            if total > limit:
                raise ValueError("Component grew beyond its runtime size limit")
            outgoing.write(data)
        if total != metadata.st_size:
            raise ValueError("Component size changed while taking its snapshot")
    return Path(destination)


def verify_overlay(root, manifest):
    for item in manifest["overlay_files"]:
        relative = Path(item["path"])
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError("Unsafe source overlay image path")
        path = root / relative
        if any((root / parent).is_symlink() for parent in relative.parents):
            raise ValueError("Symlink parent in source overlay image path")
        expected_mode = 0o755 if item["executable"] else 0o644
        if (not path.is_file() or path.is_symlink()
                or path.stat().st_size != item["bytes"]
                or digest(path) != item["sha256"]
                or stat.S_IMODE(path.stat().st_mode) != expected_mode):
            raise ValueError("Extracted overlay differs from reviewed source: " + str(relative))


def pack(destination, members, epoch):
    with destination.open("xb") as stream:
        with tarfile.open(fileobj=stream, mode="w", format=tarfile.USTAR_FORMAT) as archive:
            for name, path, mode in members:
                info = tarfile.TarInfo(name)
                info.size = path.stat().st_size
                info.uid = info.gid = 0
                info.uname = info.gname = "root"
                info.mtime = epoch
                info.mode = mode
                with path.open("rb") as source:
                    archive.addfile(info, source)


def build(source, rootfs, kernel, bootcore, destination, epoch, volume_bytes=6221824):
    source = Path(source).resolve()
    metadata_bytes = {name: regular(source / name).read_bytes()
                      for name in ("MANIFEST.json", "release.json")}
    _, findings = check_source(source)
    if findings:
        raise ValueError("Source audit failed before archive assembly")
    spec = load_release(source)
    if any((source / name).read_bytes() != content for name, content in metadata_bytes.items()):
        raise ValueError("Source release metadata changed during its audit")
    inputs = {"KERNEL": regular(kernel), "BOOTCORE": regular(bootcore),
              "ROOTFS": regular(rootfs)}
    if type(epoch) is not int or not 0 <= epoch <= 0xFFFFFFFF:
        raise ValueError("Invalid reproducible build epoch")
    destination = Path(destination)
    if destination.exists() or destination.is_symlink():
        raise ValueError("Output directory must be new")
    destination = destination.resolve()
    if destination == source or source in destination.parents:
        raise ValueError("Private firmware output must stay outside the source checkout")
    if shutil.which("unsquashfs") is None:
        raise ValueError("unsquashfs is required for independent image verification")
    destination.mkdir(mode=0o700, parents=False)
    os.chmod(destination, 0o700)
    try:
        with tempfile.TemporaryDirectory(prefix=".image-check-", dir=destination) as tmp:
            private = Path(tmp)
            inputs = {name: snapshot_component(path, private / (name.lower() + ".img"),
                      MAX_MEMBER["rootfs.img" if name == "ROOTFS" else name.lower() + ".bin"])
                      for name, path in inputs.items()}
            for name in ("KERNEL", "BOOTCORE"):
                expected_size, expected_hash = QUALIFIED_COMPONENTS[name.lower()]
                path = inputs[name]
                if path.stat().st_size != int(expected_size) or digest(path) != expected_hash:
                    raise ValueError("Unqualified " + name.lower() + " component")
            frozen_source = private / "reviewed-source"
            frozen_source.mkdir()
            for name, content in metadata_bytes.items():
                (frozen_source / name).write_bytes(content)
            unpacked = private / "rootfs"
            result = subprocess.run(
                ["unsquashfs", "-no-progress", "-d", str(unpacked), str(inputs["ROOTFS"])],
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=180)
            (destination / "extraction.log").write_bytes(result.stdout)
            if result.returncode:
                raise ValueError("Independent SquashFS extraction failed")
            manifest = json.loads(metadata_bytes["MANIFEST.json"])
            verify_overlay(unpacked, manifest)
            runtime = check_runtime(unpacked, frozen_source / "MANIFEST.json", False)
            if runtime["changed_path_count"] != 0:
                raise ValueError("Extracted image still contains stale runtime pins")
            fields = firmware_fields(spec)
            fields.update(FW_TARGET=spec["target"], FW_PROFILE=spec["hardware_profile"])
            for name, path in inputs.items():
                fields["SIZE_" + name] = str(path.stat().st_size)
                fields["SHA256_" + name] = digest(path)
            control = destination / "control.txt"
            control.write_text(assignments(fields), encoding="ascii")
            identity = check_rootfs(unpacked, frozen_source, control)
            members = [
                ("upgrade.sh", unpacked / "usr/sbin/8311-firmware-upgrade.sh", 0o755),
                ("control", control, 0o644), ("kernel.bin", inputs["KERNEL"], 0o644),
                ("bootcore.bin", inputs["BOOTCORE"], 0o644), ("rootfs.img", inputs["ROOTFS"], 0o644),
            ]
            archive = destination / (spec["release"] + "-UNTRIALED-local-upgrade.tar")
            pack(archive, members, epoch)
            repeat = Path(tmp) / "repeat.tar"
            pack(repeat, members, epoch)
            if digest(repeat) != digest(archive):
                raise ValueError("Archive reproducibility verification failed")
            report = qualify_archive(archive, volume_bytes, 65536, 65536)
            if any((source / name).read_bytes() != content
                   for name, content in metadata_bytes.items()):
                raise ValueError("Source release metadata changed during assembly")
            report.update(identity)
            report.update({
                "status": "UNTRIALED_OFFLINE_ONLY", "archive": archive.name,
                "archive_bytes": archive.stat().st_size, "archive_sha256": digest(archive),
                "build_epoch": epoch,
                "source_manifest_sha256": hashlib.sha256(metadata_bytes["MANIFEST.json"]).hexdigest(),
                "canonical_release_sha256": hashlib.sha256(metadata_bytes["release.json"]).hexdigest(),
                "runtime_profile_sha256": runtime["profile_sha256_after"],
                "source_overlay_files_verified": len(manifest["overlay_files"]),
                "archive_reproducible": True, "safe_for_live_install": False,
                "note": "Offline candidate. Hardware trial and credential persistence remain unverified.",
            })
            (destination / "qualification.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
            return report
    except Exception:
        # Retain failed outputs for diagnosis, but make failure explicit.
        (destination / "FAILED").write_text("Offline assembly failed. Do not use this candidate.\n")
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=SOURCE)
    parser.add_argument("--rootfs", required=True, type=Path)
    parser.add_argument("--kernel", required=True, type=Path)
    parser.add_argument("--bootcore", required=True, type=Path)
    parser.add_argument("--destination", required=True, type=Path)
    parser.add_argument("--epoch", required=True, type=int)
    parser.add_argument("--volume-bytes", type=int, default=6221824)
    args = parser.parse_args()
    try:
        result = build(args.source, args.rootfs, args.kernel, args.bootcore,
                       args.destination, args.epoch, args.volume_bytes)
    except (ValueError, OSError, AssertionError, subprocess.SubprocessError, tarfile.TarError) as exc:
        print(json.dumps({"status": "failed", "reason": str(exc), "hardware_qualified": False}))
        return 1
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
