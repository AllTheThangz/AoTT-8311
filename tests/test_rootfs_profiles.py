"""Safety tests for offline PRX126 rootfs slimming plans.

All fixtures use synthetic binaries and nonfunctional placeholder config.
Nothing accesses a real device or includes real identifiers.
"""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

REPO=Path(__file__).resolve().parent.parent
SPEC=importlib.util.spec_from_file_location("profile_module",
                                           REPO/"tools/prune_rootfs.py")
m=importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(m)

FAKE_MIPS=b"\x7fELF"+bytes([1,2,1])+bytes(11)+b"\x00\x08"+bytes(20)


def fixture(root: Path):
    files={
       "etc/openwrt_release":b"DISTRIB_TARGET='intel_mips/prx300'\nDISTRIB_RELEASE='PTXG_CX_V0.03'\n",
       "etc/8311_version":b"FW_VERSION=AoTT-8311-v2r1\n",
       "lib/8311-release-profile": (
           b"profile potron-prx126-aott-v1\n"
           b"target WAS-110\n"
           b"file candidate usr/lib/libssl.so.1.1 5 abcdef0123456789\n"
           b"file common usr/bin/omcid 5 abcdef0123456789\n"
       ),
       "etc/mibs/readme":b"See the MIB format notes in project documentation.\n",
       "etc/mibs/prx300_1U.ini":b"fixture\n",
       "etc/mibs/prx300_2U.ini":b"fixture\n",
       "usr/bin/omcid":FAKE_MIPS,
       "usr/bin/pon":b"fake\n",
       "usr/bin/nano":b"editor\n",
       "usr/lib/libcrypto.so.1.1":b"crypto\n",
       "usr/lib/libssl.so.1.1":b"tls\n",
       "usr/lib/libpcap.so.1":b"libpcap\n",
       "lib/libustream-ssl.so":b"ustream\n",
       "usr/sbin/8311-bankctl.sh":b"#!/bin/sh\n",
       "usr/sbin/8311-firmware-upgrade.sh":b"#!/bin/sh\n",
       "usr/sbin/tcpdump":b"fake\n",
       "usr/sbin/8311-rarpd.sh":b"fake\n",
       "www/luci-static/resources/view/status/include/50_dsl.js":b"legacy_dsl\n",
       "www/luci-static/resources/view/status/include/60_wifi.js":b"legacy_wireless\n",
       "www/luci-static/resources/view/status/include/15_pon.js":b"pon\n",
    }
    for path,data in files.items():
        p=root/path
        p.parent.mkdir(parents=True,exist_ok=True)
        p.write_bytes(data)
    (root/"lib/modules").mkdir(parents=True)
    return files


class ProfileSafetyTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir=Path(self.tmp.name)
        self.root=self.dir/"synthetic-prx126"
        self.root.mkdir()
        self.baseline=fixture(self.root)

    def test_nonmutating_docs_profile(self):
        out=m.profile_plan(self.root,"documentation-free")
        self.assertEqual([x["path"] for x in out["pruned"]],
                         ["etc/mibs/readme"])
        self.assertFalse(out["hardware_qualified"])
        self.assertTrue((self.root/"etc/mibs/readme").exists())

    def test_compact_preserves_pon_rarp_recovery_and_mibs(self):
        staged=self.dir/"compact-output"
        report=m.stage(self.root,staged,"prx126-compact")
        self.assertTrue(report["staged"])
        self.assertFalse(report["hardware_qualified"])
        for path in ("usr/bin/nano","etc/mibs/readme",
                     "www/luci-static/resources/view/status/include/50_dsl.js",
                     "www/luci-static/resources/view/status/include/60_wifi.js"):
            self.assertFalse((staged/path).exists(),path)
            self.assertTrue((self.root/path).exists(),path)
        for required in m.PROTECTED:
            self.assertTrue((staged/required).exists(),required)
        self.assertTrue((staged/"etc/mibs/prx300_2U.ini").exists())
        self.assertTrue((staged/"usr/lib/libssl.so.1.1").exists())
        self.assertTrue((staged/"www/luci-static/resources/view/status/include/15_pon.js").exists())

    def test_experimental_opt_in_required(self):
        with self.assertRaisesRegex(m.ProfileError,"risk acknowledgement"):
            m.profile_plan(self.root,"experimental-no-libssl")
        with self.assertRaisesRegex(m.ProfileError,"risk acknowledgement"):
            m.stage(self.root,self.dir/"unapproved",
                    "experimental-no-libssl")
        self.assertFalse((self.dir/"unapproved").exists())

    def test_experimental_manifest_pin_updates_only_in_output(self):
        staged=self.dir/"experimental-output"
        result=m.stage(self.root,staged,"experimental-no-libssl",True)
        self.assertEqual(result["qualification"],"experimental")
        self.assertFalse((staged/"usr/lib/libssl.so.1.1").exists())
        self.assertTrue((staged/"usr/lib/libcrypto.so.1.1").exists())
        self.assertTrue((staged/"usr/bin/omcid").exists())
        self.assertNotIn(m.PIN_LINE_PREFIX,
                         (staged/"lib/8311-release-profile").read_text())
        self.assertIn(m.PIN_LINE_PREFIX,
                      (self.root/"lib/8311-release-profile").read_text())

    def test_unsupported_board_rejected(self):
        p=self.root/"etc/openwrt_release"
        p.write_text("DISTRIB_TARGET='realtek/rtl9615'\n")
        with self.assertRaisesRegex(m.ProfileError,"sentinel mismatch"):
            m.profile_plan(self.root,"prx126-compact")

    def test_different_prx300_vendor_sdk_rejected(self):
        p=self.root/"etc/openwrt_release"
        data=p.read_text().replace("PTXG_CX_V0.03","v22.03.3")
        p.write_text(data)
        with self.assertRaisesRegex(m.ProfileError,"vendor firmware base"):
            m.profile_plan(self.root,"prx126-compact")

    def test_incorrect_omci_abi_rejected(self):
        p=self.root/"usr/bin/omcid"
        data=bytearray(p.read_bytes())
        data[5]=1
        p.write_bytes(data)
        with self.assertRaisesRegex(m.ProfileError,"MIPS32"):
            m.profile_plan(self.root,"documentation-free")

    def test_stale_missing_removable_file_fails_closed(self):
        (self.root/"usr/bin/nano").unlink()
        with self.assertRaisesRegex(m.ProfileError,"optional file absent"):
            m.profile_plan(self.root,"prx126-compact")

    def test_nonexistent_destination_required(self):
        with self.assertRaisesRegex(m.ProfileError,"must not already exist"):
            m.stage(self.root,self.root,"documentation-free")

    def test_unknown_profile_rejected(self):
        with self.assertRaisesRegex(m.ProfileError,"Unknown pruning profile"):
            m.profile_plan(self.root,"delete-everything")

    def test_unsupported_experimental_pin_fails_closed(self):
        p=self.root/"lib/8311-release-profile"
        p.write_text("profile potron-prx126-aott-v1\n")
        with self.assertRaisesRegex(m.ProfileError,"release profile"):
            m.profile_plan(self.root,"experimental-no-libssl",True)

    def test_symlink_source_rejected(self):
        link=self.dir/"source-alias"
        link.symlink_to(self.root,target_is_directory=True)
        with self.assertRaisesRegex(m.ProfileError,"cannot be a symlink"):
            m.profile_plan(link,"prx126-compact")

    def test_rarpd_and_tcpdump_cannot_be_pruned(self):
        for path in ("usr/sbin/tcpdump","usr/sbin/8311-rarpd.sh",
                     "usr/lib/libpcap.so.1"):
            self.assertIn(path,m.PROTECTED)
            for profile in m.PROFILES:
                self.assertNotIn(path,m.PROFILES[profile])

    def test_no_documentation_runtimes(self):
        self.assertIn("etc/mibs/readme",m.DOCS_ONLY)
        for profile,prunes in m.PROFILES.items():
            self.assertIn("etc/mibs/readme",prunes)

if __name__=="__main__":
    unittest.main()
