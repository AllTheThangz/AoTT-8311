"""Offline r8 boot-hook preservation and startup-sequence checks.

No production sysctl, PON, persistent storage, or boot settings are modified.
"""
from pathlib import Path
import os
import re
import subprocess
import unittest

ROOT=Path(__file__).resolve().parents[1]
VENDOR=Path(os.getenv("AOTT_VENDOR_ROOTFS","/nonexistent/vendor/rootfs"))


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
        path=VENDOR/"etc/init.d/sysctl"
        if not path.is_file():
            if os.getenv("AOTT_VENDOR_ROOTFS"):
                self.fail("Explicit vendor sysctl baseline unavailable")
            self.skipTest("Optional private vendor rootfs not present")
        vendor=path.read_text()
        marker="\t# AoTT-8311 r8: restore the protected monitoring record only when"
        self.assertIn(marker,actual)
        first,second=actual.split(marker,1)
        # In the vendor original the last closing bracket ends start().
        self.assertTrue(vendor.endswith("}\n"))
        self.assertEqual(first.rstrip("\n")+"\n}\n",vendor)
        self.assertIn(">",second)
        self.assertTrue(actual.endswith("}\n"))

    def test_preexisting_vendor_boot_links_and_config_unmodified(self):
        if not VENDOR.is_dir():
            if os.getenv("AOTT_VENDOR_ROOTFS"):
                self.fail("Explicit vendor baseline unavailable")
            self.skipTest("Optional private vendor rootfs not present")
        links={
            "etc/rc.d/S10boot":"../init.d/boot",
            "etc/rc.d/S11sysctl":"../init.d/sysctl",
            "etc/rc.d/S12log":"../init.d/log",
        }
        for name,target in links.items():
            p=VENDOR/name
            self.assertTrue(p.is_symlink(),name)
            self.assertEqual(str(p.readlink()),target)
        source=ROOT/"overlay/etc/uci-defaults/zzz-8311"
        baseline=VENDOR/"etc/uci-defaults/zzz-8311"
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
