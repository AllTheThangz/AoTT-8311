"""Synthetic offline upgrade-image qualification tests.

No proprietary firmware or device-specific configuration is embedded.
"""
from pathlib import Path
import hashlib
import importlib.util
import io
import os
import struct
import tarfile
import tempfile
import unittest

ROOT=Path(__file__).resolve().parent.parent
SPEC=importlib.util.spec_from_file_location(
    "offline_image_qualification",ROOT/"tools/qualify_offline_image.py")
module=importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)


def build_rootfs(compression=4,padding_nonzero=False,extent=512):
    data=bytearray(extent)
    data[:4]=b"hsqs"
    struct.pack_into("<I",data,4,1)
    struct.pack_into("<I",data,12,1048576)
    struct.pack_into("<I",data,16,0)
    struct.pack_into("<H",data,20,compression)
    struct.pack_into("<H",data,22,20)
    struct.pack_into("<H",data,24,0)
    struct.pack_into("<H",data,26,1)
    struct.pack_into("<H",data,28,4)
    struct.pack_into("<H",data,30,0)
    struct.pack_into("<Q",data,32,0)
    struct.pack_into("<Q",data,40,256)
    struct.pack_into("<Q",data,48,220)
    struct.pack_into("<Q",data,56,(2**64)-1)
    struct.pack_into("<Q",data,64,128)
    struct.pack_into("<Q",data,72,170)
    struct.pack_into("<Q",data,80,(2**64)-1)
    struct.pack_into("<Q",data,88,(2**64)-1)
    if padding_nonzero:
        data[-1]=0x45
    return bytes(data)


def create_archive(path,compression=4,padding_nonzero=False,
                   tamper_hash=False,extra=False,duplicate=False):
    root=build_rootfs(compression,padding_nonzero)
    files={
        "upgrade.sh":b"#!/bin/sh\nexit 0\n",
        "kernel.bin":b"synthetic-kernel",
        "bootcore.bin":b"synthetic-bootcore",
        "rootfs.img":root,
    }
    control=[
        "FW_VERSION=AoTT-8311-v2r1",
        "SIZE_KERNEL="+str(len(files["kernel.bin"])),
        "SHA256_KERNEL="+hashlib.sha256(files["kernel.bin"]).hexdigest(),
        "SIZE_BOOTCORE="+str(len(files["bootcore.bin"])),
        "SHA256_BOOTCORE="+hashlib.sha256(files["bootcore.bin"]).hexdigest(),
        "SIZE_ROOTFS="+str(len(root)),
        "SHA256_ROOTFS="+hashlib.sha256(root).hexdigest()
    ]
    if tamper_hash:
        control[-1]="SHA256_ROOTFS="+"0"*64
    if duplicate:
        control.append(control[0])
    files["control"]=("\n".join(control)+"\n").encode()
    with tarfile.open(path,"w",format=tarfile.USTAR_FORMAT) as tf:
        for name in module.MEMBERS:
            blob=files[name]
            item=tarfile.TarInfo(name)
            item.size=len(blob)
            item.uid=item.gid=0
            item.mtime=0
            item.mode=0o755 if name=="upgrade.sh" else 0o644
            tf.addfile(item,io.BytesIO(blob))
        if extra:
            item=tarfile.TarInfo("unsafe-export")
            item.size=2
            item.uid=item.gid=0
            tf.addfile(item,io.BytesIO(b"no"))


class OfflineImageValidationTests(unittest.TestCase):
    CAPACITY=1048576

    def qualify(self,**fixture):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/"fixture.tar"
            create_archive(path,**fixture)
            return module.qualify_archive(path,self.CAPACITY)

    def test_valid_five_member_archive(self):
        report=self.qualify()
        self.assertEqual(report["status"],"passed")
        self.assertEqual(report["rootfs"]["bytes_used"],256)
        self.assertEqual(report["rootfs"]["padding_bytes"],256)
        self.assertTrue(report["headroom_recommendation_met"])

    def test_non_ustar_archive_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/"fixture.tar"
            create_archive(path)
            with path.open("r+b") as stream:
                stream.seek(257)
                stream.write(b"other")
            with self.assertRaisesRegex(module.QualificationError,
                                        "expected USTAR"):
                module.qualify_archive(path,self.CAPACITY)

    def test_unknown_compression_rejected(self):
        with self.assertRaisesRegex(module.QualificationError,
                                    "expected XZ"):
            self.qualify(compression=1)

    def test_nonzero_padding_rejected(self):
        with self.assertRaisesRegex(module.QualificationError,
                                    "Nonzero SquashFS padding"):
            self.qualify(padding_nonzero=True)

    def test_component_digest_mismatch_rejected(self):
        with self.assertRaisesRegex(module.QualificationError,
                                    "Component hash differs"):
            self.qualify(tamper_hash=True)

    def test_extra_archive_member_rejected(self):
        with self.assertRaisesRegex(module.QualificationError,
                                    "member order"):
            self.qualify(extra=True)

    def test_duplicate_control_field_rejected(self):
        with self.assertRaisesRegex(module.QualificationError,
                                    "Duplicate control"):
            self.qualify(duplicate=True)

    def test_volume_capacity_rejected(self):
        with self.assertRaisesRegex(module.QualificationError,
                                    "Unsupported volume capacity"):
            with tempfile.TemporaryDirectory() as tmp:
                path=Path(tmp)/"fixture.tar"
                create_archive(path)
                module.qualify_archive(path,100)

    def test_mandatory_reserve_guard(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/"fixture.tar"
            create_archive(path)
            with self.assertRaisesRegex(module.QualificationError,
                                        "mandatory reserve"):
                module.qualify_archive(
                    path,self.CAPACITY,min_headroom=self.CAPACITY-100)

    def test_symlink_archive_input_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            a=Path(tmp)/"fixture.tar"
            link=Path(tmp)/"other.tar"
            create_archive(a)
            link.symlink_to(a)
            with self.assertRaisesRegex(module.QualificationError,
                                        "regular file"):
                module.qualify_archive(link,self.CAPACITY)

if __name__=="__main__":
    unittest.main()
