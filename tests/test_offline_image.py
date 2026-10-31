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
                   tamper_hash=False,extra=False,duplicate=False,
                   control_updates=None,omit_fields=(),upper_hashes=False,
                   oversized_updater=False,control_separator="\n"):
    root=build_rootfs(compression,padding_nonzero)
    files={
        "upgrade.sh":(b"x"*65537 if oversized_updater else b"#!/bin/sh\nexit 0\n"),
        "kernel.bin":b"synthetic-kernel",
        "bootcore.bin":b"synthetic-bootcore",
        "rootfs.img":root,
    }
    control=[
        "FW_VERSION=AoTT-8311-v2r1",
        "FW_REVISION=r1",
        "FW_VARIANT=basic",
        "FW_TARGET=WAS-110",
        "FW_PROFILE=potron-prx126-aott-v1",
        "FW_VER=AoTT-8311-v2r1",
        "FW_REV=r1",
        "FW_LONG_VERSION=AoTT-8311-v2r1_basic",
        "FW_SUFFIX=",
        "SIZE_KERNEL="+str(len(files["kernel.bin"])),
        "SHA256_KERNEL="+hashlib.sha256(files["kernel.bin"]).hexdigest(),
        "SIZE_BOOTCORE="+str(len(files["bootcore.bin"])),
        "SHA256_BOOTCORE="+hashlib.sha256(files["bootcore.bin"]).hexdigest(),
        "SIZE_ROOTFS="+str(len(root)),
        "SHA256_ROOTFS="+hashlib.sha256(root).hexdigest()
    ]
    if tamper_hash:
        control[-1]="SHA256_ROOTFS="+"0"*64
    fields=dict(line.split("=",1) for line in control)
    fields.update(control_updates or {})
    for name in omit_fields:
        fields.pop(name,None)
    if upper_hashes:
        for name in fields:
            if name.startswith("SHA256_"):
                fields[name]=fields[name].upper()
    control=[name+"="+value for name,value in fields.items()]
    if duplicate:
        control.append(control[0])
    files["control"]=(control_separator.join(control)+control_separator).encode()
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
        self.assertEqual(report["revision"],"r1")
        self.assertEqual(report["compatibility_profile"],"potron-prx126-aott-v1")

    def test_required_runtime_identity_fields(self):
        for field in ("FW_VERSION","FW_REVISION","FW_VARIANT","FW_TARGET","FW_PROFILE"):
            with self.subTest(field=field):
                with self.assertRaisesRegex(module.QualificationError,
                                            "Missing firmware identity"):
                    self.qualify(omit_fields=(field,))

    def test_wrong_board_profile_target_or_variant_rejected(self):
        for field,value in (("FW_PROFILE","different-hardware"),
                            ("FW_TARGET","unqualified-board"),
                            ("FW_VARIANT","other")):
            with self.subTest(field=field):
                with self.assertRaisesRegex(module.QualificationError,
                                            "Unsupported firmware"):
                    self.qualify(control_updates={field:value})

    def test_invalid_runtime_version_fields_rejected(self):
        for field,value in (("FW_REVISION",""),("FW_REVISION","r"*65),
                            ("FW_VERSION","AoTT-8311-v2 r2"),
                            ("FW_REVISION","r2;false")):
            with self.subTest(field=field,value=value):
                with self.assertRaisesRegex(module.QualificationError,
                                            "Invalid firmware version"):
                    self.qualify(control_updates={field:value})

    def test_legacy_identity_aliases_must_agree(self):
        for field,value in (("FW_VER","AoTT-8311-v2r0"),
                            ("FW_REV","r0"),
                            ("FW_LONG_VERSION","AoTT-8311-v2r0_basic"),
                            ("FW_SUFFIX","unreviewed")):
            with self.subTest(field=field):
                with self.assertRaisesRegex(module.QualificationError,
                                            "identity alias differs"):
                    self.qualify(control_updates={field:value})

    def test_legacy_aliases_are_optional(self):
        result=self.qualify(omit_fields=("FW_VER","FW_REV","FW_LONG_VERSION","FW_SUFFIX"))
        self.assertEqual(result["status"],"passed")

    def test_unsupported_control_field_rejected(self):
        with self.assertRaisesRegex(module.QualificationError,"Unsupported control field"):
            self.qualify(control_updates={"UNREVIEWED_OPTION":"1"})

    def test_noncanonical_component_sizes_rejected(self):
        for value in ("0","0015","+15","-15","15 ","1e1"):
            with self.subTest(size=value):
                with self.assertRaisesRegex(module.QualificationError,
                                            "positive canonical decimal"):
                    self.qualify(control_updates={"SIZE_KERNEL":value})

    def test_declared_component_runtime_limits(self):
        for field,value in (("SIZE_KERNEL","8388609"),
                            ("SIZE_BOOTCORE","8388609"),
                            ("SIZE_ROOTFS","33554433")):
            with self.subTest(field=field):
                with self.assertRaisesRegex(module.QualificationError,
                                            "Component size exceeds runtime limit"):
                    self.qualify(control_updates={field:value})

    def test_archive_updater_matches_runtime_64_kib_limit(self):
        with self.assertRaisesRegex(module.QualificationError,
                                    "Component size exceeds offline safety limits"):
            self.qualify(oversized_updater=True)

    def test_uppercase_component_hashes_match_runtime_acceptance(self):
        self.assertEqual(self.qualify(upper_hashes=True)["status"],"passed")

    def test_control_crlf_is_rejected_like_device_stager(self):
        with self.assertRaisesRegex(module.QualificationError,
                                    "unsupported text bytes"):
            self.qualify(control_separator="\r\n")

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
