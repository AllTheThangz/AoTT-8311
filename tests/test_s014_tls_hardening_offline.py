"""S-014 TLS private-key hardening, source-only diagnostics and vendor TLS.

All certificates are newly generated synthetic fixtures. No actual ONU
management endpoint, device certificate or subscriber data is accessed.
"""
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import shutil
import socket
import ssl
import stat
import subprocess
import sys
import tempfile
import time
import unittest

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, rsa
from cryptography.x509.oid import NameOID

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from s014_tls_hardening_offline import (
    CERT_FILENAME, KEY_FILENAME, TLSAuditError, evaluate_metadata,
    audit_source_material, inspect_offline_candidate,
)

VENDOR = Path(os.environ.get("AOTT_VENDOR_ROOTFS", "/missing/vendor-rootfs"))
LOCAL_TEST_IPV4 = ".".join(("127", "0", "0", "1"))


def synthetic_pair(dns="offline.invalid", ips=(), days=90,
                   key=None, include_san=True):
    import ipaddress
    key = key or ec.generate_private_key(ec.SECP256R1())
    now = datetime.now(timezone.utc)
    subject = x509.Name([
        x509.NameAttribute(NameOID.COMMON_NAME, dns)
    ])
    builder = (x509.CertificateBuilder()
        .subject_name(subject).issuer_name(subject).public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=5))
        .not_valid_after(now + timedelta(days=days))
        .add_extension(x509.BasicConstraints(ca=False, path_length=None),
                       critical=True))
    if include_san:
        builder = builder.add_extension(
            x509.SubjectAlternativeName(
                [x509.DNSName(dns)] + [
                    x509.IPAddress(ipaddress.ip_address(ip)) for ip in ips
                ]),
            critical=False)
    cert = builder.sign(key, hashes.SHA256())
    return (
        cert.public_bytes(serialization.Encoding.DER),
        key.private_bytes(
            serialization.Encoding.DER,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption()),
    )


def metadata(key_mode=0o600, cert_mode=0o644, key_uid=0,
             key_nlink=1, key_kind="regular", dir_mode=0o700):
    return {
        "directory": {
            "mode": dir_mode, "uid": 0, "gid": 0, "kind": "directory"
        },
        "certificate": {
            "mode": cert_mode, "uid": 0, "gid": 0,
            "nlink": 1, "kind": "regular", "size": 480
        },
        "private_key": {
            "mode": key_mode, "uid": key_uid, "gid": 0,
            "nlink": key_nlink, "kind": key_kind, "size": 120
        },
    }


class SourceHealthTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cert, cls.key = synthetic_pair()

    def health(self, meta=None, cert=None, key=None, days=None,
               handshake=None, dns=("offline.invalid",)):
        obj = meta or metadata()
        cert = self.cert if cert is None else cert
        key = self.key if key is None else key
        obj["certificate"]["size"] = len(cert)
        obj["private_key"]["size"] = len(key)
        return audit_source_material(
            cert, key, dns, (), obj,
            offline_vendor_handshake=handshake)

    def test_valid_material_but_no_native_handshake_is_not_qualified(self):
        result = self.health()
        self.assertEqual(result["status"], "SOURCE_TLS_REVIEW_REQUIRED")
        self.assertIn("vendor_tls_load_not_verified", result["warnings"])
        self.assertTrue(result["source_material_validated"])
        self.assertTrue(result["live_onu_certificate_unverified"])
        self.assertTrue(result["browser_trust_unverified"])
        self.assertFalse(result["tls_service_changed"])
        self.assertFalse(result["private_key_permissions_changed"])
        self.assertFalse(result["key_or_hostname_exported"])
        self.assertNotIn("offline.invalid", str(result))

    def test_strongest_ever_is_only_vendor_emulation(self):
        result = self.health(handshake=True)
        self.assertEqual(result["status"],
                         "SOURCE_CERT_AND_VENDOR_EMULATION_VERIFIED")
        self.assertTrue(result["vendor_emulated_tls_load"])
        self.assertTrue(result["live_onu_certificate_unverified"])
        self.assertTrue(result["browser_trust_unverified"])
        self.assertEqual(result["cert_key_storage_mode"],
                         "root_only_0400_or_0600")

    def test_excessively_permissive_private_key_is_refused(self):
        for mode in (0o644, 0o640, 0o666, 0o440, 0o777):
            with self.subTest(mode=mode):
                result = self.health(metadata(key_mode=mode))
                self.assertEqual(
                    result["status"], "SOURCE_TLS_STORAGE_REMEDIATION_REQUIRED")
                self.assertIn("private_key_not_root_only", result["warnings"])
                self.assertFalse(result["source_material_validated"])

    def test_readonly_root_owned_private_key_is_allowed(self):
        result = self.health(metadata(key_mode=0o400))
        self.assertTrue(result["source_material_validated"])
        self.assertEqual(result["status"], "SOURCE_TLS_REVIEW_REQUIRED")

    def test_private_key_not_root_owned(self):
        result = self.health(metadata(key_uid=99))
        self.assertIn("not_root_owned", result["warnings"])

    def test_hardlinked_key_rejected(self):
        result = self.health(metadata(key_nlink=2))
        self.assertIn("multiple_links_or_unknown", result["warnings"])

    def test_symlink_key_never_read_as_safe(self):
        result = self.health(metadata(key_kind="symlink"))
        self.assertIn("unexpected_inode_type", result["warnings"])

    def test_certificate_public_read_mode_allowed(self):
        result = self.health(metadata(cert_mode=0o644))
        self.assertTrue(result["source_material_validated"])

    def test_certificate_executable_mode_not_allowed(self):
        result = self.health(metadata(cert_mode=0o755))
        self.assertIn("certificate_mode_unqualified", result["warnings"])

    def test_parent_directory_not_private(self):
        result = self.health(metadata(dir_mode=0o755))
        self.assertIn("parent_directory_untrusted", result["warnings"])

    def test_metadata_wrong_shape_refused(self):
        with self.assertRaises(TLSAuditError):
            evaluate_metadata({}, {}, {})
        with self.assertRaises(TLSAuditError):
            audit_source_material(self.cert, self.key, ["offline.invalid"],
                                  metadata())

    def test_empty_or_oversized_source_material(self):
        for data in (b"", b"x" * 17000):
            with self.subTest(size=len(data)):
                result = self.health(cert=data)
                self.assertFalse(result["source_material_validated"])
                self.assertNotIn("SOURCE_CERT_AND_VENDOR_EMULATION_VERIFIED",
                                 result["status"])

    def test_wrong_private_key_reports_redacted_warning(self):
        different = ec.generate_private_key(ec.SECP256R1())
        bad_key = different.private_bytes(
            serialization.Encoding.DER,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption())
        result = self.health(key=bad_key)
        self.assertEqual(
            result["status"], "SOURCE_TLS_MATERIAL_REMEDIATION_REQUIRED")
        self.assertIn("certificate_key_or_identity_unverified",
                      result["warnings"])
        self.assertNotIn("offline.invalid", str(result))

    def test_missing_san_is_refused(self):
        cert, key = synthetic_pair(include_san=False)
        result = self.health(cert=cert, key=key)
        self.assertFalse(result["source_material_validated"])

    def test_wrong_host_is_refused(self):
        result = self.health(dns=["wrong.invalid"])
        self.assertFalse(result["source_material_validated"])
        self.assertFalse(result["key_or_hostname_exported"])

    def test_invalid_certificate_bytes_refused(self):
        result = self.health(cert=b"not-a-certificate")
        self.assertEqual(result["status"],
                         "SOURCE_TLS_MATERIAL_REMEDIATION_REQUIRED")

    def test_near_expiry_warns(self):
        cert, key = synthetic_pair(days=12)
        result = self.health(cert=cert, key=key)
        self.assertTrue(result["source_material_validated"])
        self.assertIn("certificate_expires_within_30_days", result["warnings"])

    def test_expired_certificate_never_called_verified(self):
        cert, key = synthetic_pair(days=1)
        future = datetime.now(timezone.utc) + timedelta(days=3)
        item = metadata()
        item["certificate"]["size"] = len(cert)
        item["private_key"]["size"] = len(key)
        r = audit_source_material(cert, key, ["offline.invalid"], [], item,
                                  now=future, offline_vendor_handshake=True)
        self.assertNotEqual(r["status"],
                            "SOURCE_CERT_AND_VENDOR_EMULATION_VERIFIED")

    def test_source_never_has_live_actions(self):
        source = (ROOT/"tools/s014_tls_hardening_offline.py").read_text()
        manifest = (ROOT/"MANIFEST.json").read_text()
        controller = (ROOT/"overlay/usr/lib/lua/luci/controller/8311.lua").read_text()
        self.assertNotIn("s014_tls_hardening", manifest)
        self.assertNotIn("s014_tls_hardening", controller)
        for bad in ("subprocess.run(", "os.system(", "os.chmod(", "uci commit ",
                    "reboot", "fw_setenv", "service uhttpd restart"):
            self.assertNotIn(bad, source)


@unittest.skipUnless(
    os.geteuid() == 0 and os.environ.get("AOTT_VENDOR_ROOTFS")
    and (VENDOR/"usr/sbin/uhttpd").is_file()
    and (VENDOR/"usr/sbin/px5g").is_file()
    and shutil.which("qemu-mips-static"),
    "Isolated vendor MIPS/QEMU loopback tests require root and extracted rootfs",
)
class OfflineVendorUhttpdTests(unittest.TestCase):
    def setUp(self):
        self.p = Path(tempfile.mkdtemp(
            prefix="aott-s014-tls-test-", dir="/var/tmp"))
        self.p.chmod(0o700)
        self.key = self.p/KEY_FILENAME
        self.cert = self.p/CERT_FILENAME
        command = [
            "qemu-mips-static", "-L", str(VENDOR),
            str(VENDOR/"usr/sbin/px5g"), "selfsigned",
            "-der", "-days", "60", "-newkey", "ec",
            "-pkeyopt", "ec_paramgen_curve:P-256",
            "-keyout", str(self.key), "-out", str(self.cert),
            "-subj", "/CN=offline.invalid",
            "-addext", "subjectAltName=DNS:offline.invalid",
            "-addext", "subjectAltName=IP:" + LOCAL_TEST_IPV4,
        ]
        completed = subprocess.run(
            command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            timeout=25, check=True)
        self.key.chmod(0o600)
        self.cert.chmod(0o644)

    def tearDown(self):
        shutil.rmtree(self.p, ignore_errors=True)

    def test_on_disk_source_audit_validates_root_only_key(self):
        data = inspect_offline_candidate(str(self.p),
                                         ["offline.invalid"], [LOCAL_TEST_IPV4])
        self.assertTrue(data["source_material_validated"])
        self.assertIn("vendor_tls_load_not_verified", data["warnings"])
        self.assertEqual(self.key.stat().st_mode & 0o777, 0o600)

    def test_native_uhttpd_ssl_handshake_with_0600_private_key(self):
        # Standalone vendor-MIPS uhttpd under QEMU on the Hermes loopback
        # namespace only. No live ONU, public interface or web route.
        with socket.socket() as sock:
            sock.bind((LOCAL_TEST_IPV4, 0))
            port = sock.getsockname()[1]
        argv = [
            "qemu-mips-static", "-L", str(VENDOR),
            str(VENDOR/"usr/sbin/uhttpd"), "-f", "-h", str(self.p),
            "-s", LOCAL_TEST_IPV4 + ":" + str(port),
            "-C", str(self.cert), "-K", str(self.key)
        ]
        service = subprocess.Popen(
            argv, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
            # This synthetic certificate is explicitly trusted only
            # inside this temporary test context.
            context.load_verify_locations(
                cadata=ssl.DER_cert_to_PEM_cert(self.cert.read_bytes()))
            context.verify_mode = ssl.CERT_REQUIRED
            context.check_hostname = True
            receipt = None
            for _ in range(50):
                if service.poll() is not None:
                    break
                try:
                    with socket.create_connection(
                        (LOCAL_TEST_IPV4, port), timeout=0.5
                    ) as channel:
                        with context.wrap_socket(
                            channel, server_hostname=LOCAL_TEST_IPV4
                        ) as tls:
                            fingerprint = tls.getpeercert(binary_form=True)
                            receipt = {
                                "presented_certificate_matches_candidate":
                                    fingerprint == self.cert.read_bytes(),
                                "negotiated_tls": tls.version(),
                                "private_key_mode": self.key.stat().st_mode & 0o777,
                            }
                            break
                except (OSError, ssl.SSLError):
                    time.sleep(0.1)
            self.assertIsNotNone(receipt, "native loopback handshake unavailable")
            self.assertTrue(receipt["presented_certificate_matches_candidate"])
            self.assertEqual(receipt["private_key_mode"], 0o600)
            self.assertIn(receipt["negotiated_tls"], ("TLSv1.2", "TLSv1.3"))
        finally:
            service.terminate()
            try:
                service.wait(timeout=5)
            except subprocess.TimeoutExpired:
                service.kill()
                service.wait(timeout=5)

    def test_root_readonly_key_0400_source_inspection(self):
        self.key.chmod(0o400)
        result = inspect_offline_candidate(
            str(self.p), ["offline.invalid"], [LOCAL_TEST_IPV4])
        self.assertTrue(result["source_material_validated"])
        self.assertEqual(self.key.stat().st_mode & 0o777, 0o400)

    def test_world_readable_key_rejected_before_tls_execution(self):
        self.key.chmod(0o644)
        result = inspect_offline_candidate(str(self.p),
                                           ["offline.invalid"], [LOCAL_TEST_IPV4])
        self.assertEqual(result["status"],
                         "SOURCE_TLS_STORAGE_REMEDIATION_REQUIRED")
        self.assertIn("private_key_not_root_only", result["warnings"])

    def test_wrong_hostname_does_not_pass_offline_source_inspection(self):
        result = inspect_offline_candidate(
            str(self.p), ["not-the-synthetic-host.invalid"],
            [LOCAL_TEST_IPV4])
        self.assertFalse(result["source_material_validated"])
        self.assertIn("certificate_key_or_identity_unverified", result["warnings"])

    def test_symlink_key_rejected_without_read(self):
        original = self.p/"hidden-synthetic-key"
        self.key.rename(original)
        self.key.symlink_to(original)
        result = inspect_offline_candidate(str(self.p),
                                           ["offline.invalid"], [LOCAL_TEST_IPV4])
        self.assertEqual(result["status"],
                         "SOURCE_TLS_STORAGE_REMEDIATION_REQUIRED")
        self.assertIn("unexpected_inode_type", result["warnings"])
        self.assertTrue(original.is_file())


if __name__ == "__main__":
    unittest.main()
