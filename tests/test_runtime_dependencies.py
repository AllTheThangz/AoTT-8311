"""Isolated PRX126 dependency auditing tests with synthetic source fixtures.

No live ONU, vendor binaries, private keys or customer identities.
"""
from pathlib import Path
import json
import os
import re
import tempfile
import unittest

import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT/"tools"))
import audit_rootfs_dependencies as audit


class RuntimeDependencyAuditTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def add(self,relative,bytes_):
        file=self.root/relative
        file.parent.mkdir(parents=True,exist_ok=True)
        file.write_bytes(bytes_)
        return file

    def test_readelf_needed_parser(self):
        sample = """
 0x00000001 (NEEDED) Shared library: [libcrypto.so.1.1]
 0x00000001 (NEEDED) Shared library: [libc.so]
 0x00000001 (NEEDED) Shared library: [libcrypto.so.1.1]
 0x0000000e (SONAME) Shared library: [libsomething.so.1]
"""
        self.assertEqual(audit.parse_needed(sample),
                         ("libc.so","libcrypto.so.1.1"))

    def test_invalid_elf_does_not_match_mips(self):
        f=self.add("usr/bin/fake-elf",b"\x7fELF"+b"\0"*24)
        self.assertFalse(audit.elf32_mips_big_endian(f))
        f.write_bytes(b"\x7fELF"+bytes([1,2,1])+bytes(11)+b"\x00\x08")
        self.assertTrue(audit.elf32_mips_big_endian(f))

    def test_crypto_is_required_by_omci(self):
        deps = {
            "usr/bin/omcid": ("libcrypto.so.1.1",),
            "usr/lib/libssl.so.1.1": ("libcrypto.so.1.1",),
            "lib/libustream-ssl.so": ("libmbedtls.so.21",),
            "usr/sbin/tcpdump": ("libpcap.so.0.8",),
        }
        self.add("usr/lib/libssl.so.1.1",b"synthetic-unusable-fixture")
        self.add("usr/sbin/uhttpd",b"libustream-ssl.so")
        self.add("usr/sbin/tcpdump",b"fake-elf")
        self.add("usr/sbin/8311-rarpd.sh",b"#!/bin/sh\ntcpdump -n\n")
        result=audit.runtime_classification(self.root,deps)
        self.assertTrue(result["critical_omci_crypto"]["omcid_directly_needs_it"])
        self.assertEqual(result["critical_omci_crypto"]["action"],"keep")
        self.assertEqual(result["openssl_ssl"]["action"],"experimental_only")
        self.assertFalse(result["openssl_ssl"]["direct_elf_consumers"])
        self.assertTrue(result["web_tls"]["mbedtls_linked_in_ustream"])
        self.assertTrue(result["reverse_arp_capture"]["tcpdump_directly_needs_libpcap"])
        self.assertEqual(result["reverse_arp_capture"]["libpcap_consumers"],
                         ["usr/sbin/tcpdump"])

    def test_explicit_ssl_consumer_prevents_experimental_removal(self):
        deps={"usr/bin/omcid":("libcrypto.so.1.1",),
              "usr/bin/example":("libssl.so.1.1",)}
        self.add("usr/lib/libssl.so.1.1",b"fixture")
        result=audit.runtime_classification(self.root,deps)
        self.assertEqual(result["openssl_ssl"]["action"],"keep")
        self.assertEqual(result["openssl_ssl"]["direct_elf_consumers"],
                         ["usr/bin/example"])

    def test_exact_duplicates_are_only_reported_not_deleted(self):
        a=self.add("usr/lib/a.dat",b"A"*4096)
        b=self.add("opt/pon/lib/a.dat",b"A"*4096)
        self.add("usr/lib/other.dat",b"B"*4096)
        groups=audit.duplicate_groups(self.root)
        self.assertEqual(groups,[(4096,["opt/pon/lib/a.dat","usr/lib/a.dat"])])
        self.assertEqual(a.read_bytes(),b.read_bytes())

    def test_doc_only_and_wifi_conditional(self):
        data={
            "admin/status/realtime/wireless":{
                "action":{"type":"view","path":"status/wireless"},
                "depends":{"uci":{"wireless":{"@wifi-device":True}}}
            }
        }
        self.add("usr/share/luci/menu.d/luci-mod-status.json",
                 json.dumps(data).encode())
        for name in ("www/luci-static/resources/view/status/wireless.js",
                     "www/luci-static/resources/wireless.svg",
                     "www/luci-static/resources/wifirate.svg"):
            self.add(name,b"fixture")
        info=audit.optional_status_assets(self.root)
        self.assertTrue(info["conditional_pruning_suitable"])
        self.add("etc/config/wireless",b"config wifi-device\n")
        info=audit.optional_status_assets(self.root)
        self.assertFalse(info["conditional_pruning_suitable"])

    def test_invalid_rootfs_paths_rejected(self):
        with self.assertRaises((audit.ProfileError,audit.AuditError)):
            audit.audit(Path("/"))
        with self.assertRaises((audit.ProfileError,audit.AuditError)):
            audit.audit(self.root)

    def test_no_sensitive_field_names_emitted(self):
        expected=Path(audit.__file__).read_text()
        self.assertNotIn("fw_printenv",expected)
        self.assertNotIn("ssh root@",expected)
        self.assertNotIn("macaddr",expected)
        self.assertNotIn("gpon_sn",expected)

if __name__=="__main__":
    unittest.main()
