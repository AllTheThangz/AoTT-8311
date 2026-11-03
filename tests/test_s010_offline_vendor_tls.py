"""S-010: synthetic vendor MIPS TLS SAN and key safety tests, no live ONU."""

from datetime import datetime, timedelta, timezone
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from s010_offline_vendor_tls import (
    CERT_NAME, KEY_NAME, OfflineTLSError,
    canonical_identities, px5g_argv, trusted_test_directory,
    checked_file, inspect_der_pair, generate_offline,
)

VENDOR = Path(os.environ.get("AOTT_VENDOR_ROOTFS", "/missing/offline-vendor-rootfs"))
# Construct reserved documentation addresses, avoiding embedding literal
# subscriber-like IPv4 strings in public source or release artifacts.
V4 = ".".join(("192", "0", "2", "10"))
V4_RSA = ".".join(("192", "0", "2", "25"))
V4_OTHER = ".".join(("192", "0", "2", "12"))


class StrictSANSafetyTests(unittest.TestCase):
    def test_canonical_dns_ipv4_ipv6(self):
        self.assertEqual(
            canonical_identities(["OnU.Home.ARPA"], [V4, "2001:0db8::8"]),
            (("onu.home.arpa",), (V4, "2001:db8::8")),
        )

    def test_no_identity_rejected(self):
        with self.assertRaises(OfflineTLSError):
            canonical_identities()

    def test_reject_shell_meta_and_url_identity(self):
        for name in ["host.local;touch x", "https://host.local",
                     "foo/bar", "*.example.invalid", "good_bad.local",
                     " leading.local", "evil.local\nheader", "täst.invalid",
                     "a"*64+".local", "a..local", "-bad.local"]:
            with self.subTest(name=name), self.assertRaises(OfflineTLSError):
                canonical_identities([name])

    def test_reject_ipv6_zone_or_bad_ip(self):
        for value in ["fe80::1%eth0", ".".join(("127", "0", "0", "999")), "example.invalid",
                      V4 + ";cmd", "", "::1/128"]:
            with self.subTest(value=value), self.assertRaises(OfflineTLSError):
                canonical_identities(ips=[value])

    def test_reject_duplicates_and_san_overflow(self):
        for hosts, ips in [
            (["A.local", "a.LOCAL"], []),
            ([], ["2001:db8::1", "2001:0db8::1"]),
            (["one.local"]*9, []),
        ]:
            with self.subTest(hosts=hosts, ips=ips), self.assertRaises(OfflineTLSError):
                canonical_identities(hosts, ips)

    def test_ipv4_text_must_be_an_ip_san_not_dns(self):
        with self.assertRaisesRegex(OfflineTLSError, "ip_identity_must_use_ip"):
            canonical_identities(dns=[V4])

    def test_reject_scalar_collections(self):
        with self.assertRaises(OfflineTLSError):
            canonical_identities(dns="host.local")

    def test_build_native_addext_once_per_san(self):
        command = px5g_argv(
            "/offline/vendor/px5g", "/offline/cert.der", "/offline/key.der",
            ["localhost"], [V4, "2001:db8::8"], 365)
        self.assertEqual(command.count("-addext"), 3)
        self.assertIn("subjectAltName=DNS:localhost", command)
        self.assertIn("subjectAltName=IP:" + V4, command)
        self.assertIn("subjectAltName=IP:2001:db8::8", command)
        self.assertIn("ec_paramgen_curve:P-256", command)
        self.assertNotIn("-passout", command)
        self.assertNotIn("/bin/sh", command)
        rsa = px5g_argv("px5g", "cert", "key", ips=[V4],
                        key_type="rsa-2048")
        self.assertIn("rsa:2048", rsa)
        self.assertNotIn("ec_paramgen_curve:P-256", rsa)

    def test_days_and_key_type_hard_bounds(self):
        for days in [0, -1, 398, "365", True]:
            with self.subTest(days=days), self.assertRaises(OfflineTLSError):
                px5g_argv("px5g", "cert", "key", ips=[V4], days=days)
        with self.assertRaises(OfflineTLSError):
            px5g_argv("px5g", "cert", "key", ips=[V4],
                       key_type="rsa-1024")

    def test_offline_directory_only(self):
        with self.assertRaises(OfflineTLSError):
            trusted_test_directory("/etc/ssl")
        with self.assertRaises(OfflineTLSError):
            trusted_test_directory("/var/tmp/aott-s010-cert-test-../../etc")
        with self.assertRaises(OfflineTLSError):
            trusted_test_directory("/var/tmp/aott-s010-cert-test-missingdir")

    def test_non_deployed_and_no_legacy_cert_mutation(self):
        source = (ROOT / "tools/s010_offline_vendor_tls.py").read_text()
        self.assertIn("subprocess.run(command, cwd=\"/\"", source)
        for prohibited in ("uci commit", "uhttpd restart", "fw_setenv",
                           "flash_erase", "mtd write", "/dev/mtd"):
            self.assertNotIn(prohibited, source)
        manifest = (ROOT / "MANIFEST.json").read_text()
        controller = (ROOT / "overlay/usr/lib/lua/luci/controller/8311.lua").read_text()
        self.assertNotIn("s010_offline_vendor_tls", manifest)
        self.assertNotIn("s010_offline_vendor_tls", controller)


@unittest.skipUnless(
    os.geteuid() == 0 and os.environ.get("AOTT_VENDOR_ROOTFS")
    and shutil.which("qemu-mips-static") and
    (VENDOR / "usr/sbin/px5g").is_file(),
    "Requires root and an extracted offline vendor-MIPS px5g rootfs",
)
class VendorMIPSSANTests(unittest.TestCase):
    def setUp(self):
        try:
            from cryptography import x509  # noqa: F401
        except ImportError:
            self.skipTest("Offline cryptography verifier unavailable")
        self.sandboxes = []

    def tearDown(self):
        for folder in self.sandboxes:
            if folder.exists() and not folder.is_symlink():
                shutil.rmtree(folder)

    def sandbox(self):
        path = Path(tempfile.mkdtemp(prefix="aott-s010-cert-test-",
                                    dir="/var/tmp"))
        path.chmod(0o700)
        self.sandboxes.append(path)
        return path

    def make(self, dns=(), ips=(), days=30, key_type="ec-p256"):
        path = self.sandbox()
        report = generate_offline(VENDOR, path, dns, ips, days, key_type)
        self.assertEqual(report["status"], "S010_OFFLINE_VENDOR_CERT_VERIFIED")
        self.assertTrue(report["source_only_not_deployed"])
        self.assertTrue(report["candidate_only_no_install_or_reload"])
        self.assertEqual((path / KEY_NAME).stat().st_mode & 0o777, 0o600)
        self.assertIn((path / CERT_NAME).stat().st_mode & 0o777, (0o600, 0o644))
        return path, report

    def test_native_ec_dns_ipv4_ipv6_sans(self):
        folder, receipt = self.make(["onu.example.invalid"],
                                    [V4, "2001:db8::8"])
        self.assertEqual(receipt["dns"], ["onu.example.invalid"])
        self.assertEqual(receipt["ips"], [V4, "2001:db8::8"])
        self.assertEqual(receipt["key_type"], "ec-p256")
        self.assertEqual(len(receipt["certificate_sha256"]), 64)
        self.assertEqual(len(receipt["vendor_px5g_sha256"]), 64)

    def test_native_rsa2048_san(self):
        _, receipt = self.make(ips=[V4_RSA], key_type="rsa-2048")
        self.assertEqual(receipt["key_type"], "rsa-2048")
        self.assertEqual(receipt["ips"], [V4_RSA])

    def test_native_local_hostname_without_ip(self):
        _, receipt = self.make(dns=["onu.home.arpa"])
        self.assertEqual(receipt["dns"], ["onu.home.arpa"])
        self.assertEqual(receipt["ips"], [])

    def test_mismatched_key_rejected(self):
        first, _ = self.make(dns=["one.local"])
        second, _ = self.make(dns=["two.local"])
        with self.assertRaisesRegex(OfflineTLSError, "mismatch"):
            inspect_der_pair((first / CERT_NAME).read_bytes(),
                             (second / KEY_NAME).read_bytes(),
                             dns=["one.local"])

    def test_wrong_or_extra_san_rejected(self):
        first, _ = self.make(dns=["onu.local"], ips=[V4])
        data = (first / CERT_NAME).read_bytes(), (first / KEY_NAME).read_bytes()
        for names, ips in [
            (["other.local"], [V4]),
            (["onu.local"], [V4_OTHER]),
            (["onu.local"], []),
        ]:
            with self.subTest(names=names, ips=ips):
                with self.assertRaisesRegex(OfflineTLSError, "san_mismatch"):
                    inspect_der_pair(*data, names, ips)

    def test_certificate_signature_tamper_rejected(self):
        first, _ = self.make(dns=["onu.local"])
        corrupted = bytearray((first / CERT_NAME).read_bytes())
        corrupted[-1] ^= 1
        with self.assertRaisesRegex(OfflineTLSError, "parse_failed"):
            inspect_der_pair(bytes(corrupted), (first / KEY_NAME).read_bytes(),
                             dns=["onu.local"])

    def test_future_time_expiration_rejected(self):
        first, _ = self.make(dns=["onu.local"], days=1)
        with self.assertRaisesRegex(OfflineTLSError, "invalid_validity"):
            inspect_der_pair((first / CERT_NAME).read_bytes(),
                             (first / KEY_NAME).read_bytes(),
                             dns=["onu.local"],
                             now=datetime.now(timezone.utc)+timedelta(days=3))

    def test_existing_candidate_cannot_be_replaced(self):
        folder, _ = self.make(dns=["onu.local"])
        first = (folder / CERT_NAME).read_bytes()
        with self.assertRaisesRegex(OfflineTLSError, "already_exists"):
            generate_offline(VENDOR, folder, dns=["onu.local"])
        self.assertEqual((folder / CERT_NAME).read_bytes(), first)

    def test_private_key_broader_mode_refused(self):
        folder, _ = self.make(dns=["onu.local"])
        path = folder / KEY_NAME
        path.chmod(0o644)
        with self.assertRaisesRegex(OfflineTLSError, "unsafe_tls"):
            checked_file(path, key_material=True)

    def test_symlink_private_dir_is_rejected(self):
        private = self.sandbox()
        link = Path("/var/tmp/aott-s010-cert-test-link" + private.name[-8:])
        self.assertFalse(link.exists())
        link.symlink_to(private)
        try:
            with self.assertRaisesRegex(OfflineTLSError, "unapproved_offline"):
                generate_offline(VENDOR, link, dns=["onu.local"])
            self.assertFalse((private / CERT_NAME).exists())
        finally:
            link.unlink()

    def test_no_san_legacy_vendor_cert_refused(self):
        folder = self.sandbox()
        crt, key = folder / CERT_NAME, folder / KEY_NAME
        cmd = [shutil.which("qemu-mips-static"), "-L", str(VENDOR),
               str(VENDOR / "usr/sbin/px5g"), "selfsigned", "-der",
               "-days", "30", "-newkey", "ec", "-pkeyopt",
               "ec_paramgen_curve:P-256", "-keyout", str(key), "-out",
               str(crt), "-subj", "/CN=onu.local"]
        subprocess.run(cmd, stdout=subprocess.DEVNULL,
                       stderr=subprocess.DEVNULL, check=True, timeout=20)
        with self.assertRaisesRegex(OfflineTLSError, "parse_failed"):
            inspect_der_pair(crt.read_bytes(), key.read_bytes(),
                             dns=["onu.local"])


if __name__ == "__main__":
    unittest.main()
