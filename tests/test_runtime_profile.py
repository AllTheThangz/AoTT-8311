"""Regression tests for review-gated firmware runtime integrity pins.

Synthetic fixtures only. They contain no production credentials, hardware
serials, vendor firmware binaries or actual device flash data.
"""
from pathlib import Path
import hashlib
import importlib.util
import json
import os
import tempfile
import unittest

REPO=Path(__file__).resolve().parent.parent
SPEC=importlib.util.spec_from_file_location(
    "runtime_profile_test_module",REPO/"tools/refresh_runtime_profile.py")
mod=importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(mod)


def sha(blob):
    return hashlib.sha256(blob).hexdigest()


class RuntimeProfileSourceTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)/"offline-rootfs"
        self.root.mkdir()
        self.old=b"old-function\n"
        self.new=b"reviewed-function-v2\n"
        self.rel="usr/lib/lua/8311/config.lua"
        self.manifest=Path(self.tmp.name)/"MANIFEST.json"
        self.profile=self.root/"lib/8311-release-profile"
        self.profile.parent.mkdir(parents=True)
        source=self.root/self.rel
        source.parent.mkdir(parents=True)
        source.write_bytes(self.new)
        self.pinned={}
        for i in range(11):
            rel=f"etc/fixture/f{i}"
            p=self.root/rel
            p.parent.mkdir(parents=True,exist_ok=True)
            data=("fixture-"+str(i)+"\n").encode()
            p.write_bytes(data)
            self.pinned[rel]=data
        self.lines=[
            "profile potron-prx126-aott-v1",
            "target WAS-110",
            "variant basic",
        ]
        for component,(length,digest) in mod.QUALIFIED_COMPONENTS.items():
            self.lines.append(f"component {component} {length} {digest}")
        self.lines += [
            f"file common {name} {len(value)} {sha(value)}"
            for name,value in sorted(self.pinned.items())
        ]
        self.lines.append(f"file candidate {self.rel} {len(self.old)} {sha(self.old)}")
        self.profile.write_text("\n".join(self.lines)+"\n")
        self.manifest.write_text(json.dumps({
            "source_only":True,
            "firmware_binaries_included":False,
            "overlay_files":[{"path":self.rel,"bytes":len(self.new),
                              "sha256":sha(self.new)}]
        })+"\n")

    def test_only_reviewed_candidate_is_refreshable(self):
        old=self.profile.read_text()
        report=mod.run(self.root,self.manifest,False)
        self.assertEqual(report["changed_path_count"],1)
        self.assertEqual(self.profile.read_text(),old)
        approved=mod.run(self.root,self.manifest,True)
        self.assertEqual(approved["changed_path_count"],1)
        self.assertIn(f"file candidate {self.rel} {len(self.new)} {sha(self.new)}",
                      self.profile.read_text())
        self.assertEqual(mod.run(self.root,self.manifest,False)["changed_path_count"],0)

    def test_kernel_profile_change_rejected(self):
        original=self.profile.read_text()
        for part,(length,digest) in mod.QUALIFIED_COMPONENTS.items():
            if part=="kernel":
                original=original.replace(
                    f"component kernel {length} {digest}",
                    f"component kernel {length} "+("0"*64))
                break
        self.profile.write_text(original)
        with self.assertRaisesRegex(mod.RuntimeProfileError,
                                    "Kernel or bootcore compatibility"):
            mod.run(self.root,self.manifest,True)

    def test_wrong_vendor_target_rejected(self):
        self.profile.write_text(
            self.profile.read_text().replace("target WAS-110","target UNIVERSAL"))
        with self.assertRaisesRegex(mod.RuntimeProfileError,
                                    "Unqualified firmware target"):
            mod.run(self.root,self.manifest,True)

    def test_common_runtime_change_rejected(self):
        file=self.root/"etc/fixture/f0"
        file.write_text("modified-vendor-runtime\n")
        with self.assertRaisesRegex(mod.RuntimeProfileError,
                                    "Protected or unapproved"):
            mod.run(self.root,self.manifest,True)

    def test_unlisted_candidate_change_rejected(self):
        fake=self.root/"usr/lib/lua/8311/unknown.lua"
        fake.write_text("local x = 2\n")
        self.profile.write_text(
            self.profile.read_text()+
            f"file candidate usr/lib/lua/8311/unknown.lua 10 {sha(b'wrong-file')}\n")
        with self.assertRaisesRegex(mod.RuntimeProfileError,
                                    "Protected or unapproved"):
            mod.run(self.root,self.manifest,True)

    def test_wrong_manifest_digest_rejected(self):
        data=json.loads(self.manifest.read_text())
        data["overlay_files"][0]["sha256"]="0"*64
        self.manifest.write_text(json.dumps(data))
        with self.assertRaisesRegex(mod.RuntimeProfileError,
                                    "Protected or unapproved"):
            mod.run(self.root,self.manifest,True)

    def test_duplicate_pinned_file_rejected(self):
        self.profile.write_text(self.profile.read_text()+self.lines[-1]+"\n")
        with self.assertRaisesRegex(mod.RuntimeProfileError,
                                    "Duplicate runtime profile"):
            mod.run(self.root,self.manifest)

    def test_missing_file_rejected(self):
        (self.root/"etc/fixture/f4").unlink()
        with self.assertRaisesRegex(mod.RuntimeProfileError,
                                    "Missing required"):
            mod.run(self.root,self.manifest)

    def test_common_symlink_reference_rejected(self):
        p=self.root/"etc/fixture/f1"
        p.unlink()
        p.symlink_to(self.root/"etc/fixture/f2")
        with self.assertRaisesRegex(mod.RuntimeProfileError,
                                    "Missing required"):
            mod.run(self.root,self.manifest)

    def test_missing_source_manifest_rejected(self):
        self.manifest.unlink()
        with self.assertRaises(OSError):
            mod.run(self.root,self.manifest)

    def test_rejected_non_source_manifest(self):
        data=json.loads(self.manifest.read_text())
        data["source_only"]=False
        self.manifest.write_text(json.dumps(data))
        with self.assertRaisesRegex(mod.RuntimeProfileError,
                                    "approved source-only"):
            mod.run(self.root,self.manifest)

if __name__=="__main__":
    unittest.main()
