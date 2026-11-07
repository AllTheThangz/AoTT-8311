"""Offline r8 boot-hook preservation and startup-sequence checks.

No production sysctl, PON, persistent storage, or boot settings are modified.
Missing private reference files use immutable pre-monitoring r7 snapshots.
"""
from pathlib import Path
import hashlib
import json
import os
import subprocess
import unittest

ROOT=Path(__file__).resolve().parents[1]
VENDOR=Path(os.getenv("AOTT_VENDOR_ROOTFS","/nonexistent/vendor/rootfs"))

FIXTURES=ROOT/"tests/fixtures/r7_boot_baseline"
PROVENANCE_SHA256="4f8035271aacc0bab0ad2f4ecae4dcf20b9f49d1abce0552095f1b6889bf6499"
REFERENCE_FILES=("etc/init.d/sysctl", "etc/uci-defaults/zzz-8311")
REFERENCE_LINKS=("etc/rc.d/S10boot", "etc/rc.d/S11sysctl", "etc/rc.d/S12log")


def boot_reference():
    """Use complete supplied references or independently captured r7 snapshots.

    The fixed MIPS test runtime intentionally contains only execution fixtures.
    Missing boot-reference files therefore use hash-pinned source snapshots.
    Any supplied partial reference must still match that captured baseline.
    """
    if all((VENDOR/name).is_file() and not (VENDOR/name).is_symlink()
           for name in REFERENCE_FILES) and all(
               (VENDOR/name).is_symlink() for name in REFERENCE_LINKS):
        return ({name: VENDOR/name for name in REFERENCE_FILES},
                {name: {"type": "symlink", "target": str((VENDOR/name).readlink())}
                 for name in REFERENCE_LINKS})

    provenance_path=FIXTURES/"provenance.json"
    if provenance_path.is_symlink():
        raise AssertionError("Boot-reference provenance must be a regular file")
    encoded=provenance_path.read_bytes()
    if hashlib.sha256(encoded).hexdigest() != PROVENANCE_SHA256:
        raise AssertionError("Captured r7 boot-reference provenance changed")
    provenance=json.loads(encoded)
    files={}
    for name in REFERENCE_FILES:
        entry=provenance["files"][name]
        path=FIXTURES/entry["fixture"]
        if path.is_symlink() or not path.is_file():
            raise AssertionError("Captured r7 boot reference is not regular: "+name)
        data=path.read_bytes()
        if (len(data) != entry["bytes"] or
                hashlib.sha256(data).hexdigest() != entry["sha256"]):
            raise AssertionError("Captured r7 boot-reference bytes changed: "+name)
        provided=VENDOR/name
        if provided.exists() or provided.is_symlink():
            if provided.is_symlink() or not provided.is_file():
                raise AssertionError("Supplied boot reference is not regular: "+name)
            if provided.read_bytes() != data:
                raise AssertionError("Partial supplied boot reference differs: "+name)
            files[name]=provided
        else:
            files[name]=path
    links=provenance["links"]
    for name in REFERENCE_LINKS:
        provided=VENDOR/name
        if provided.exists() or provided.is_symlink():
            if not provided.is_symlink():
                raise AssertionError("Supplied boot reference is not a symlink: "+name)
            if str(provided.readlink()) != links[name]["target"]:
                raise AssertionError("Partial supplied boot link differs: "+name)
    return files, links


class VendorS11BootSafetyTests(unittest.TestCase):
    def test_public_source_boot_hook_is_regular_text_not_new_symlink(self):
        source=ROOT/"overlay/etc/init.d/sysctl"
        self.assertTrue(source.is_file())
        self.assertFalse(source.is_symlink())
        self.assertFalse((ROOT/"overlay/etc/rc.d/S118311-monitoring").exists())
        self.assertFalse((ROOT/"overlay/etc/init.d/8311-monitoring").exists())
        self.assertEqual(source.stat().st_mode & 0o111, 0o111)
        subprocess.run(["/bin/sh","-n",str(source)],check=True,timeout=4)

    def test_hook_only_when_durable_record_exists(self):
        s=(ROOT/"overlay/etc/init.d/sysctl").read_text()
        self.assertIn('START=11',s)
        self.assertIn('[ -f /ptconf/8311-monitoring/config.json ]',s)
        self.assertIn('/usr/bin/timeout -k 1 12',s)
        self.assertEqual(s.count('/usr/libexec/8311-monitoring-restore'),1)
        self.assertLess(s.index('sysctl -e -p'),s.index('8311-monitoring-restore'))
        self.assertNotIn("uci commit",s)
        self.assertNotIn("fw_setenv",s)
        self.assertNotIn("reboot",s)

    def test_original_vendor_sysctl_content_is_preserved_except_guard(self):
        actual=(ROOT/"overlay/etc/init.d/sysctl").read_text()
        files,_=boot_reference()
        vendor=files["etc/init.d/sysctl"].read_text()
        marker="\t# AoTT-8311 r8: restore the protected monitoring record only when"
        self.assertIn(marker,actual)
        first,second=actual.split(marker,1)
        # In the vendor original the last closing bracket ends start().
        self.assertTrue(vendor.endswith("}\n"))
        self.assertEqual(first.rstrip("\n")+"\n}\n",vendor)
        self.assertIn(">",second)
        self.assertTrue(actual.endswith("}\n"))

    def test_preexisting_vendor_boot_links_and_config_unmodified(self):
        files,reference_links=boot_reference()
        links={
            "etc/rc.d/S10boot":"../init.d/boot",
            "etc/rc.d/S11sysctl":"../init.d/sysctl",
            "etc/rc.d/S12log":"../init.d/log",
        }
        for name,target in links.items():
            entry=reference_links[name]
            self.assertEqual(entry["type"],"symlink",name)
            self.assertEqual(entry["target"],target)
        source=ROOT/"overlay/etc/uci-defaults/zzz-8311"
        baseline=files["etc/uci-defaults/zzz-8311"]
        self.assertEqual(source.read_bytes(),baseline.read_bytes())
        self.assertEqual(
            (ROOT/"overlay/etc/init.d/sysctl").read_text().split("START=",1)[1][:2],
            "11")

    def test_source_package_is_symlink_free(self):
        links=[str(p.relative_to(ROOT)) for p in (ROOT/"overlay").rglob("*")
               if p.is_symlink()]
        self.assertEqual(links, [])


if __name__=="__main__":
    unittest.main()
