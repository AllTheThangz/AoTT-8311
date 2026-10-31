"""Regression tests for offline snapshot consistency and extracted source modes."""
from pathlib import Path
import hashlib
import importlib.util
import json
import shutil
import tarfile
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from test_offline_image import build_rootfs


ROOT = Path(__file__).resolve().parent.parent
SPEC = importlib.util.spec_from_file_location(
    "offline_archive_build_tests", ROOT / "tools/build_offline_archive.py")
builder = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(builder)
from release_identity import write_source


class OfflineArchiveBuildTests(unittest.TestCase):
    def setUp(self):
        self.workspace = tempfile.TemporaryDirectory()
        self.addCleanup(self.workspace.cleanup)
        self.base = Path(self.workspace.name)
        self.source = self.base / "source"
        (self.source / "overlay").mkdir(parents=True)
        shutil.copyfile(ROOT / "release.json", self.source / "release.json")
        (self.source / "MANIFEST.json").write_text("{}\n")
        spec = write_source(self.source)
        updater = self.source / "overlay/usr/sbin/8311-firmware-upgrade.sh"
        updater.parent.mkdir(parents=True)
        updater.write_text("#!/bin/sh\nexit 0\n")
        updater.chmod(0o755)
        entries = []
        for path in sorted((self.source / "overlay").rglob("*")):
            if path.is_file():
                entries.append({"path": str(path.relative_to(self.source / "overlay")),
                                "bytes": path.stat().st_size,
                                "sha256": builder.digest(path),
                                "executable": bool(path.stat().st_mode & 0o111)})
        self.manifest = {"release": spec["release"], "revision": spec["revision"],
                         "source_only": True, "firmware_binaries_included": False,
                         "overlay_files": entries}
        (self.source / "MANIFEST.json").write_text(json.dumps(self.manifest))
        self.original = {"KERNEL": b"synthetic-kernel",
                         "BOOTCORE": b"synthetic-bootcore", "ROOTFS": build_rootfs()}
        self.inputs = {}
        for name, content in self.original.items():
            path = self.base / (name.lower() + ".img")
            path.write_bytes(content)
            self.inputs[name] = path
        self.vendor_fixture = {
            name.lower(): (str(len(self.original[name])),
                           hashlib.sha256(self.original[name]).hexdigest())
            for name in ("KERNEL", "BOOTCORE")}

    def run_build(self, after_extract=None):
        def extract(command, **kwargs):
            self.assertEqual(command[0], "unsquashfs")
            self.assertNotEqual(Path(command[-1]), self.inputs["ROOTFS"])
            self.assertEqual(Path(command[-1]).read_bytes(), self.original["ROOTFS"])
            target = Path(command[3])
            shutil.copytree(self.source / "overlay", target)
            (target / "lib").mkdir()
            (target / "lib/8311-release-profile").write_text(
                "profile potron-prx126-aott-v1\ntarget WAS-110\nvariant basic\n")
            if after_extract:
                after_extract()
            return SimpleNamespace(returncode=0, stdout=b"synthetic extraction fixture\n")

        with patch.object(builder, "QUALIFIED_COMPONENTS", self.vendor_fixture), \
             patch.object(builder.shutil, "which", return_value="/usr/bin/unsquashfs"), \
             patch.object(builder.subprocess, "run", side_effect=extract), \
             patch.object(builder, "check_runtime", return_value={
                 "changed_path_count": 0, "profile_sha256_after": "0" * 64}):
            return builder.build(self.source, self.inputs["ROOTFS"], self.inputs["KERNEL"],
                                 self.inputs["BOOTCORE"], self.base / "candidate", 1234567890)

    def test_packed_bytes_remain_the_verified_snapshot_when_inputs_change(self):
        def mutate_inputs():
            for path in self.inputs.values():
                path.write_bytes(b"new unrelated bytes")

        report = self.run_build(mutate_inputs)
        archive = self.base / "candidate" / report["archive"]
        with tarfile.open(archive) as image:
            for name, member in (("KERNEL", "kernel.bin"),
                                 ("BOOTCORE", "bootcore.bin"), ("ROOTFS", "rootfs.img")):
                self.assertEqual(image.extractfile(member).read(), self.original[name])
            self.assertEqual(image.getnames(), ["upgrade.sh", "control", "kernel.bin",
                                                "bootcore.bin", "rootfs.img"])
            for member in image.getmembers():
                self.assertEqual((member.uid, member.gid, member.mtime), (0, 0, 1234567890))
                self.assertEqual(member.mode, 0o755 if member.name == "upgrade.sh" else 0o644)
        self.assertTrue(report["archive_reproducible"])
        self.assertFalse(report["hardware_qualified"])

    def test_source_metadata_drift_cannot_produce_success_receipt(self):
        def mutate_metadata():
            metadata = self.source / "MANIFEST.json"
            metadata.write_text(metadata.read_text() + "\n")

        with self.assertRaisesRegex(ValueError, "metadata changed during assembly"):
            self.run_build(mutate_metadata)
        self.assertTrue((self.base / "candidate/FAILED").is_file())
        self.assertFalse((self.base / "candidate/qualification.json").exists())

    def test_overlay_rejects_setuid_or_world_writable_modes(self):
        path = self.source / "overlay/usr/sbin/8311-firmware-upgrade.sh"
        for mode in (0o4755, 0o777):
            with self.subTest(mode=oct(mode)):
                path.chmod(mode)
                with self.assertRaisesRegex(ValueError, "Extracted overlay differs"):
                    builder.verify_overlay(self.source / "overlay", self.manifest)

    def test_overlay_rejects_symlink_parent(self):
        root = self.base / "extracted"
        root.mkdir()
        (root / "etc").symlink_to(self.source / "overlay/etc", target_is_directory=True)
        with self.assertRaisesRegex(ValueError, "Symlink parent"):
            builder.verify_overlay(root, self.manifest)

    def test_snapshot_refuses_oversized_component(self):
        with self.assertRaisesRegex(ValueError, "bounded regular-file contract"):
            builder.snapshot_component(self.inputs["ROOTFS"], self.base / "snapshot", 100)

    def test_snapshot_refuses_symlink_component(self):
        alias = self.base / "rootfs-link"
        alias.symlink_to(self.inputs["ROOTFS"])
        with self.assertRaisesRegex(ValueError, "regular nonsymlink component"):
            builder.snapshot_component(alias, self.base / "snapshot", 1024)


if __name__ == "__main__":
    unittest.main()
