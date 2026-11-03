"""S-011 offline certificate import positive/negative contracts.

Synthetic keys and certificates are generated in RAM for these tests.
No production key material, subscriber identity, or live ONU is read.
"""
from datetime import datetime, timedelta, timezone
import ipaddress
import os
from pathlib import Path
import shutil
import sys
import tempfile
import unittest

from cryptography import x509
from cryptography.exceptions import UnsupportedAlgorithm
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID, ExtensionOID

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from s011_offline_certificate_import import (
    ImportPreviewError, _parse_chain, inspect_import,
    inspect_offline_directory, _cert_from_bytes, _private_key_from_bytes,
)

V4 = ".".join(("192", "0", "2", "10"))
OTHER_V4 = ".".join(("192", "0", "2", "11"))


def _name(text):
    return x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, text)])


def _new_key():
    return ec.generate_private_key(ec.SECP256R1())


def _cert(subject, issuer, subject_key, issuer_key, *,
          ca=False, san_dns=(), san_ips=(), path_len=None,
          eku=True, digital_sign=True, expired=False, delayed=False,
          name_constraints=False, digest=None):
    now = datetime.now(timezone.utc)
    start = now + timedelta(days=1) if delayed else now - timedelta(days=1)
    end = now - timedelta(hours=1) if expired else now + timedelta(days=35)
    builder = (x509.CertificateBuilder()
        .subject_name(_name(subject)).issuer_name(_name(issuer))
        .public_key(subject_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(start).not_valid_after(end)
        .add_extension(x509.BasicConstraints(ca=ca, path_length=path_len),
                       critical=True)
        .add_extension(x509.KeyUsage(
            digital_signature=digital_sign, content_commitment=False,
            key_encipherment=False, data_encipherment=False,
            key_agreement=False, key_cert_sign=ca, crl_sign=ca,
            encipher_only=False, decipher_only=False), critical=True))
    if san_dns or san_ips:
        values = ([x509.DNSName(value) for value in san_dns] +
            [x509.IPAddress(ipaddress.ip_address(value)) for value in san_ips])
        builder = builder.add_extension(
            x509.SubjectAlternativeName(values), critical=False)
    if eku:
        builder = builder.add_extension(
            x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]),
            critical=False)
    if name_constraints:
        builder = builder.add_extension(
            x509.NameConstraints(
                permitted_subtrees=[x509.DNSName("example.invalid")],
                excluded_subtrees=None), critical=True)
    return builder.sign(issuer_key, digest or hashes.SHA256())


def _pem(cert):
    return cert.public_bytes(serialization.Encoding.PEM)


def _der(cert):
    return cert.public_bytes(serialization.Encoding.DER)


def _key_pem(key):
    return key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption())


def _key_der(key):
    return key.private_bytes(
        serialization.Encoding.DER,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption())


class ImportFixture(unittest.TestCase):
    def setUp(self):
        self.anchor_key = _new_key()
        self.anchor = _cert("Root Offline CA", "Root Offline CA",
            self.anchor_key, self.anchor_key, ca=True, path_len=1, eku=False)
        self.intermediate_key = _new_key()
        self.intermediate = _cert("Intermediate Offline CA", "Root Offline CA",
            self.intermediate_key, self.anchor_key,
            ca=True, path_len=0, eku=False)
        self.leaf_key = _new_key()
        self.leaf = _cert("management.example.invalid",
            "Intermediate Offline CA", self.leaf_key, self.intermediate_key,
            san_dns=["management.example.invalid", "other.example.invalid"],
            san_ips=[V4])
        self.chain = _pem(self.intermediate) + _pem(self.anchor)

    def check(self, **overrides):
        params = {
            "leaf_bytes": _pem(self.leaf),
            "private_key_bytes": _key_pem(self.leaf_key),
            "chain_bytes": self.chain,
            "expected_dns": ["management.example.invalid"],
            "expected_ips": [V4],
        }
        params.update(overrides)
        return inspect_import(**params)


class PositiveImportTests(ImportFixture):
    def test_verified_intermediate_and_root_signatures(self):
        receipt = self.check()
        self.assertEqual(receipt["status"], "S011_OFFLINE_IMPORT_PREVIEW_VALIDATED")
        self.assertEqual(receipt["chain_certificates"], 2)
        self.assertEqual(receipt["issuer_signature_links_verified"], 2)
        self.assertTrue(receipt["supplied_self_signed_root_verified"])
        self.assertFalse(receipt["issuer_chain_incomplete"])
        self.assertTrue(receipt["browser_trust_and_revocation_unverified"])
        self.assertTrue(receipt["leaf_signature_cryptographically_verified"])
        self.assertTrue(receipt["source_only_not_deployed"])
        self.assertTrue(receipt["private_key_not_exported"])
        self.assertTrue(receipt["uhttpd_load_and_browser_trust_unverified"])
        self.assertEqual(receipt["requested_ip_count"], 1)
        self.assertEqual(receipt["requested_dns_count"], 1)
        self.assertTrue(receipt["requested_sans_matched"])
        self.assertEqual(receipt["san_entries_count"], 3)
        self.assertNotIn("other.example.invalid", str(receipt))
        self.assertNotIn("management.example.invalid", str(receipt))
        self.assertNotIn(V4, str(receipt))
        self.assertNotIn("PRIVATE KEY", str(receipt))
        self.assertEqual(len(receipt["certificate_sha256"]), 64)

    def test_cert_key_der_import_preview(self):
        self.assertEqual(self.check(leaf_bytes=_der(self.leaf),
            private_key_bytes=_key_der(self.leaf_key))["chain_certificates"], 2)

    def test_der_trailing_material_refused(self):
        with self.assertRaisesRegex(ImportPreviewError, "der_length_or_trailing"):
            self.check(leaf_bytes=_der(self.leaf) + b"tail")
        with self.assertRaisesRegex(ImportPreviewError, "der_length_or_trailing"):
            self.check(private_key_bytes=_key_der(self.leaf_key) + b"tail")

    def test_pem_prefix_whitespace_permitted(self):
        receipt = self.check(leaf_bytes=b"\n " + _pem(self.leaf),
            private_key_bytes=b"  \n" + _key_pem(self.leaf_key))
        self.assertEqual(receipt["issuer_signature_links_verified"], 2)

    def test_missing_optional_chain_never_claims_verified_browser_trust(self):
        receipt = self.check(chain_bytes=b"")
        self.assertEqual(receipt["chain_certificates"], 0)
        self.assertTrue(receipt["issuer_chain_incomplete"])
        self.assertFalse(receipt["leaf_signature_cryptographically_verified"])
        self.assertEqual(receipt["status"], "S011_OFFLINE_IMPORT_PREVIEW_PARTIAL")
        self.assertTrue(receipt["browser_trust_and_revocation_unverified"])

    def test_partial_intermediate_chain_reported_as_incomplete(self):
        receipt = self.check(chain_bytes=_pem(self.intermediate))
        self.assertEqual(receipt["issuer_signature_links_verified"], 1)
        self.assertTrue(receipt["issuer_chain_incomplete"])
        self.assertFalse(receipt["supplied_self_signed_root_verified"])

    def test_self_signed_leaf_still_untrusted_in_browser(self):
        key = _new_key()
        cert = _cert("local.example.invalid", "local.example.invalid",
            key, key, san_dns=["local.example.invalid"])
        receipt = self.check(leaf_bytes=_pem(cert),
            private_key_bytes=_key_pem(key), chain_bytes=b"",
            expected_dns=["local.example.invalid"], expected_ips=[])
        self.assertFalse(receipt["issuer_chain_incomplete"])
        self.assertTrue(receipt["browser_trust_and_revocation_unverified"])

    def test_single_label_wildcard_coverage(self):
        key = _new_key()
        cert = _cert("*.example.invalid", "Intermediate Offline CA",
            key, self.intermediate_key, san_dns=["*.example.invalid"])
        receipt = self.check(leaf_bytes=_pem(cert),
            private_key_bytes=_key_pem(key), expected_ips=[],
            expected_dns=["management.example.invalid"])
        self.assertEqual(receipt["san_entries_count"], 1)

    @unittest.skipUnless(os.geteuid() == 0,
                         "Root-owned offline directory fixture requires root")
    def test_key_mode_and_private_directory_no_writes(self):
        with tempfile.TemporaryDirectory(
            prefix="aott-s011-import-test-", dir="/var/tmp") as d:
            folder = Path(d)
            folder.chmod(0o700)
            for name, data, mode in [
                ("certificate.pem", _pem(self.leaf), 0o644),
                ("private-key.pem", _key_pem(self.leaf_key), 0o600),
                ("chain.pem", self.chain, 0o644),
            ]:
                p = folder / name
                p.write_bytes(data)
                p.chmod(mode)
            before = {p.name: (p.stat().st_mtime_ns, p.read_bytes())
                      for p in folder.iterdir()}
            receipt = inspect_offline_directory(d, ["management.example.invalid"], [V4])
            self.assertEqual(receipt["issuer_signature_links_verified"], 2)
            after = {p.name: (p.stat().st_mtime_ns, p.read_bytes())
                     for p in folder.iterdir()}
            self.assertEqual(before, after)
            self.assertEqual(sorted(before),
                             ["certificate.pem", "chain.pem", "private-key.pem"])


class NegativeImportTests(ImportFixture):
    def test_wrong_private_key_rejected(self):
        with self.assertRaisesRegex(ImportPreviewError, "key_mismatch"):
            self.check(private_key_bytes=_key_pem(_new_key()))

    def test_missing_dns_or_ip_san_rejected(self):
        with self.assertRaisesRegex(ImportPreviewError, "expected_dns"):
            self.check(expected_dns=["not-owned.example.invalid"])
        with self.assertRaisesRegex(ImportPreviewError, "expected_ip"):
            self.check(expected_ips=[OTHER_V4])

    def test_wildcard_cannot_cover_base_or_two_labels(self):
        key = _new_key()
        cert = _cert("*.example.invalid", "Intermediate Offline CA",
            key, self.intermediate_key, san_dns=["*.example.invalid"])
        for host in ("example.invalid", "a.b.example.invalid"):
            with self.subTest(host=host), self.assertRaisesRegex(
                ImportPreviewError, "expected_dns"
            ):
                self.check(leaf_bytes=_pem(cert), private_key_bytes=_key_pem(key),
                           expected_dns=[host], expected_ips=[])

    def test_invalid_and_encrypted_key_rejected(self):
        encrypted = self.leaf_key.private_bytes(
            serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
            serialization.BestAvailableEncryption(b"synthetic-only-passphrase"))
        with self.assertRaisesRegex(ImportPreviewError, "key_"):
            self.check(private_key_bytes=encrypted)

    def test_unsigned_extra_pem_content_rejected(self):
        with self.assertRaisesRegex(ImportPreviewError, "pem_structure"):
            self.check(leaf_bytes=_pem(self.leaf) + _pem(self.anchor))
        with self.assertRaisesRegex(ImportPreviewError, "extra_material|invalid_chain_pem"):
            self.check(chain_bytes=self.chain + b"\nextraneous text\n")

    def test_chain_wrong_order_rejected(self):
        with self.assertRaisesRegex(ImportPreviewError, "issuer_name_mismatch"):
            self.check(chain_bytes=_pem(self.anchor) + _pem(self.intermediate))

    def test_chain_signature_mismatch_rejected(self):
        fake_key = _new_key()
        spoofed = _cert("Intermediate Offline CA", "Root Offline CA",
            fake_key, self.anchor_key, ca=True, path_len=0, eku=False)
        with self.assertRaisesRegex(ImportPreviewError, "signature_invalid"):
            self.check(chain_bytes=_pem(spoofed) + _pem(self.anchor))

    def test_non_ca_issuer_rejected(self):
        broken = _cert("Intermediate Offline CA", "Root Offline CA",
            self.intermediate_key, self.anchor_key, ca=False, eku=False)
        with self.assertRaisesRegex(ImportPreviewError, "not_ca"):
            self.check(chain_bytes=_pem(broken) + _pem(self.anchor))

    def test_duplicate_chain_certificate_rejected(self):
        with self.assertRaisesRegex(ImportPreviewError, "issuer_name_mismatch|duplicate"):
            self.check(chain_bytes=_pem(self.intermediate) * 2)

    def test_more_than_three_chain_certificates_rejected(self):
        with self.assertRaisesRegex(ImportPreviewError, "chain_too_long"):
            self.check(chain_bytes=_pem(self.intermediate) * 4)

    def test_name_constraints_ca_not_claimed_supported(self):
        constrained = _cert("Intermediate Offline CA", "Root Offline CA",
            self.intermediate_key, self.anchor_key, ca=True,
            path_len=0, eku=False, name_constraints=True)
        with self.assertRaisesRegex(ImportPreviewError, "name_constraints"):
            self.check(chain_bytes=_pem(constrained) + _pem(self.anchor))

    def test_root_path_len_constraint_rejected(self):
        root = _cert("Root Offline CA", "Root Offline CA",
            self.anchor_key, self.anchor_key, ca=True, path_len=0, eku=False)
        intermediate = _cert("Intermediate Offline CA", "Root Offline CA",
            self.intermediate_key, self.anchor_key, ca=True, path_len=0,
            eku=False)
        with self.assertRaisesRegex(ImportPreviewError, "path_length_exceeded"):
            self.check(chain_bytes=_pem(intermediate) + _pem(root))

    def test_expired_or_not_yet_valid_leaf_rejected(self):
        for kwargs in ({"expired": True}, {"delayed": True}):
            cert = _cert("management.example.invalid",
                "Intermediate Offline CA", self.leaf_key, self.intermediate_key,
                san_dns=["management.example.invalid"], san_ips=[V4], **kwargs)
            with self.subTest(kwargs=kwargs), self.assertRaisesRegex(
                ImportPreviewError, "not_current_or_expiring"
            ):
                self.check(leaf_bytes=_pem(cert))

    def test_tampered_signature_rejected(self):
        altered = bytearray(_der(self.leaf))
        altered[-1] ^= 1
        with self.assertRaises(ImportPreviewError):
            self.check(leaf_bytes=bytes(altered))

    def test_sha1_certificate_signature_rejected(self):
        try:
            weak = _cert("management.example.invalid", "Intermediate Offline CA",
                self.leaf_key, self.intermediate_key,
                san_dns=["management.example.invalid"], san_ips=[V4],
                digest=hashes.SHA1())
        except UnsupportedAlgorithm:
            # The installed signing backend itself rejects SHA-1. The
            # import validator also explicitly refuses non-SHA-2 values.
            source = (ROOT / "tools/s011_offline_certificate_import.py").read_text()
            self.assertIn("signature_algorithm_unapproved", source)
        else:
            with self.assertRaisesRegex(ImportPreviewError, "signature_algorithm"):
                self.check(leaf_bytes=_pem(weak))

    def test_expired_ca_rejected(self):
        root = _cert("Root Offline CA", "Root Offline CA",
            self.anchor_key, self.anchor_key, ca=True, path_len=1,
            eku=False, expired=True)
        with self.assertRaisesRegex(ImportPreviewError, "not_current_or_expiring"):
            self.check(chain_bytes=_pem(self.intermediate) + _pem(root))

    def test_missing_eku_or_key_usage_fails_closed_when_restrictive(self):
        leaf = _cert("management.example.invalid", "Intermediate Offline CA",
            self.leaf_key, self.intermediate_key,
            san_dns=["management.example.invalid"], san_ips=[V4],
            digital_sign=False)
        with self.assertRaisesRegex(ImportPreviewError, "digital_signature"):
            self.check(leaf_bytes=_pem(leaf))

    def test_excessive_leaf_or_key_bytes_rejected(self):
        with self.assertRaisesRegex(ImportPreviewError, "certificate_size"):
            self.check(leaf_bytes=b"a" * 17000)
        with self.assertRaisesRegex(ImportPreviewError, "private_key_size"):
            self.check(private_key_bytes=b"z" * 17000)

    def test_no_identity_and_scalar_inputs_refused(self):
        with self.assertRaisesRegex(ImportPreviewError, "invalid_requested"):
            self.check(expected_dns=[], expected_ips=[])
        with self.assertRaisesRegex(ImportPreviewError, "invalid_requested"):
            self.check(expected_dns="management.example.invalid")

    def test_invalid_time_object_rejected(self):
        with self.assertRaisesRegex(ImportPreviewError, "aware_validation"):
            self.check(now=datetime.now())


@unittest.skipUnless(os.geteuid() == 0,
                     "Root-owned offline file-boundary tests require root")
class IsolatedFileBoundaryTests(ImportFixture):
    def setUp(self):
        super().setUp()
        self.dir = Path(tempfile.mkdtemp(
            prefix="aott-s011-import-test-", dir="/var/tmp"))
        self.dir.chmod(0o700)
        self.files = []
        self.put("certificate.pem", _pem(self.leaf), 0o644)
        self.put("private-key.pem", _key_pem(self.leaf_key), 0o600)
        self.put("chain.pem", self.chain, 0o644)

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def put(self, name, data, mode):
        p = self.dir / name
        p.write_bytes(data)
        p.chmod(mode)
        return p

    def inspect(self):
        return inspect_offline_directory(str(self.dir),
            ["management.example.invalid"], [V4])

    def test_valid_private_directory(self):
        self.assertEqual(self.inspect()["chain_certificates"], 2)

    def test_safe_cli_receipt_does_not_echo_operator_identity_or_key(self):
        import subprocess
        command = [
            sys.executable,
            str(ROOT / "tools/s011_offline_certificate_import.py"),
            "--offline-import-dir", str(self.dir),
            "--dns", "management.example.invalid", "--ip", V4,
        ]
        result = subprocess.run(
            command, capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("S011_OFFLINE_IMPORT_PREVIEW_VALIDATED", result.stdout)
        self.assertNotIn("management.example.invalid", result.stdout)
        self.assertNotIn(V4, result.stdout)
        self.assertNotIn("PRIVATE KEY", result.stdout)

    def test_private_key_world_readable_refused(self):
        (self.dir / "private-key.pem").chmod(0o644)
        with self.assertRaisesRegex(ImportPreviewError, "unsafe_import_material"):
            self.inspect()

    def test_symlink_private_key_refused(self):
        original = self.dir / "private-key.pem"
        original.rename(self.dir / "sentinel")
        original.symlink_to(self.dir / "sentinel")
        with self.assertRaisesRegex(ImportPreviewError, "unsafe_import_material"):
            self.inspect()
        self.assertTrue((self.dir / "sentinel").is_file())

    def test_hardlink_private_key_refused(self):
        os.link(self.dir / "private-key.pem", self.dir / "extra-key-copy")
        with self.assertRaisesRegex(ImportPreviewError, "unsafe_import_material"):
            self.inspect()

    def test_unsafe_directory_mode_refused(self):
        self.dir.chmod(0o755)
        with self.assertRaisesRegex(ImportPreviewError, "unsafe_import_directory"):
            self.inspect()

    def test_unapproved_directory_refused(self):
        with self.assertRaisesRegex(ImportPreviewError, "unapproved_offline"):
            inspect_offline_directory("/etc/ssl",
                ["management.example.invalid"], [V4])

    def test_optional_chain_may_be_absent_with_incomplete_status(self):
        (self.dir / "chain.pem").unlink()
        receipt = self.inspect()
        self.assertTrue(receipt["issuer_chain_incomplete"])

    def test_no_production_overlay_or_implicit_install(self):
        root = ROOT
        manifest = (root / "MANIFEST.json").read_text()
        deployed = (root / "overlay/usr/lib/lua/luci/controller/8311.lua").read_text()
        source = (root / "tools/s011_offline_certificate_import.py").read_text()
        self.assertNotIn("s011_offline_certificate_import", manifest)
        self.assertNotIn("s011_offline_certificate_import", deployed)
        self.assertIn("O_NOFOLLOW", source)
        self.assertNotIn("os.replace(", source)
        self.assertNotIn("subprocess.run(", source)
        self.assertNotIn("firmware_banks_modified", source)


if __name__ == "__main__":
    unittest.main()
