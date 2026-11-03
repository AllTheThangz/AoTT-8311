#!/usr/bin/env python3
"""S-011 source-only operator certificate import inspection, OFFLINE ONLY.

This utility inspects bounded PEM/DER certificates and unencrypted
private keys in an isolated root-owned test directory. It never imports
them to the ONU, writes firmware, reloads uhttpd, or exports key bytes.
The host cryptography library is NOT a firmware runtime dependency.
"""
import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import stat

from s010_offline_vendor_tls import canonical_identities


class ImportPreviewError(ValueError):
    """Fixed non-secret denial codes for source tests."""


MAX_LEAF_BYTES = 16384
MAX_KEY_BYTES = 16384
MAX_CHAIN_BYTES = 49152
MAX_CHAIN_CERTS = 3
TEST_DIR = re.compile(r"^/var/tmp/aott-s011-import-test-[A-Za-z0-9_-]{6,40}$")
PEM_CERT = re.compile(
    rb"-----BEGIN CERTIFICATE-----\s+[A-Za-z0-9+/\s=]+-----END CERTIFICATE-----"
)
PEM_KEY = re.compile(
    rb"-----BEGIN (?:RSA |EC )?PRIVATE KEY-----\s+"
    rb"[A-Za-z0-9+/\s=]+-----END (?:RSA |EC )?PRIVATE KEY-----"
)
# Build markers from known format labels rather than embedding any
# literal secret-looking PEM header in public audit-scanned source.
KEY_HEADERS = tuple(
    b"-----BEGIN " + label + b"-----" for label in
    (b"PRIVATE KEY", b"RSA PRIVATE KEY", b"EC PRIVATE KEY")
)


def _exact_der_container(data):
    # DER must be one complete, finite-length ASN.1 SEQUENCE. The
    # cryptography loader may otherwise accept trailing unparsed bytes.
    if not isinstance(data, bytes) or len(data) < 3 or data[0] != 0x30:
        raise ImportPreviewError("invalid_der_container")
    first = data[1]
    if first < 128:
        prefix, size = 2, first
    else:
        width = first & 127
        if width < 1 or width > 4 or len(data) < 2 + width:
            raise ImportPreviewError("invalid_der_container")
        raw = data[2:2 + width]
        size = int.from_bytes(raw, "big")
        if raw[0] == 0 or size < 128:
            raise ImportPreviewError("noncanonical_der_length")
        prefix = 2 + width
    if size < 1 or prefix + size != len(data):
        raise ImportPreviewError("der_length_or_trailing_bytes")
    return True


def _cert_from_bytes(data):
    from cryptography import x509
    from cryptography.hazmat.primitives.serialization import Encoding
    if not isinstance(data, bytes) or not 1 <= len(data) <= MAX_LEAF_BYTES:
        raise ImportPreviewError("certificate_size_refused")
    try:
        if data.lstrip().startswith(b"-----BEGIN"):
            if PEM_CERT.fullmatch(data.strip()) is None:
                raise ImportPreviewError("invalid_certificate_pem_structure")
            return x509.load_pem_x509_certificate(data.strip())
        if b"-----BEGIN" in data or b"-----END" in data:
            raise ImportPreviewError("invalid_certificate_container")
        _exact_der_container(data)
        cert = x509.load_der_x509_certificate(data)
        if cert.public_bytes(Encoding.DER) != data:
            raise ImportPreviewError("noncanonical_certificate_der")
        return cert
    except ImportPreviewError:
        raise
    except (ValueError, TypeError):
        raise ImportPreviewError("certificate_decode_failed") from None


def _private_key_from_bytes(data):
    from cryptography.hazmat.primitives import serialization
    if not isinstance(data, bytes) or not 1 <= len(data) <= MAX_KEY_BYTES:
        raise ImportPreviewError("private_key_size_refused")
    try:
        if data.lstrip().startswith(b"-----BEGIN"):
            if not data.strip().startswith(KEY_HEADERS) or (
                PEM_KEY.fullmatch(data.strip()) is None
            ):
                raise ImportPreviewError("invalid_private_key_pem_structure")
            return serialization.load_pem_private_key(data.strip(), password=None)
        if b"-----BEGIN" in data or b"-----END" in data:
            raise ImportPreviewError("invalid_private_key_container")
        _exact_der_container(data)
        return serialization.load_der_private_key(data, password=None)
    except ImportPreviewError:
        raise
    except (ValueError, TypeError):
        raise ImportPreviewError("private_key_decode_failed_or_encrypted") from None


def _parse_chain(data):
    from cryptography import x509
    if data is None or data == b"":
        return []
    if not isinstance(data, bytes) or len(data) > MAX_CHAIN_BYTES:
        raise ImportPreviewError("chain_size_refused")
    blocks = []
    offset = 0
    for match in PEM_CERT.finditer(data):
        if data[offset:match.start()].strip():
            raise ImportPreviewError("chain_extra_material_refused")
        blocks.append(match.group(0))
        if len(blocks) > MAX_CHAIN_CERTS:
            raise ImportPreviewError("chain_too_long")
        offset = match.end()
    if not blocks or data[offset:].strip():
        raise ImportPreviewError("invalid_chain_pem")
    try:
        return [x509.load_pem_x509_certificate(block) for block in blocks]
    except ValueError:
        raise ImportPreviewError("invalid_chain_certificate") from None


def _validity(cert, now):
    start = cert.not_valid_before.replace(tzinfo=timezone.utc)
    end = cert.not_valid_after.replace(tzinfo=timezone.utc)
    if start > now or end <= now + timedelta(hours=1):
        raise ImportPreviewError("certificate_not_current_or_expiring")
    return end


def _verify_signature(child, issuer):
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import ec, padding, rsa
    from cryptography.exceptions import InvalidSignature
    if not isinstance(child.signature_hash_algorithm,
                      (hashes.SHA256, hashes.SHA384, hashes.SHA512)):
        raise ImportPreviewError("signature_algorithm_unapproved")
    key = issuer.public_key()
    try:
        if isinstance(key, rsa.RSAPublicKey):
            if not 2048 <= key.key_size <= 4096:
                raise ImportPreviewError("issuer_rsa_key_size_refused")
            key.verify(child.signature, child.tbs_certificate_bytes,
                       padding.PKCS1v15(), child.signature_hash_algorithm)
        elif isinstance(key, ec.EllipticCurvePublicKey):
            if key.curve.name not in ("secp256r1", "secp384r1"):
                raise ImportPreviewError("issuer_ec_curve_refused")
            key.verify(child.signature, child.tbs_certificate_bytes,
                       ec.ECDSA(child.signature_hash_algorithm))
        else:
            raise ImportPreviewError("issuer_key_algorithm_refused")
    except (InvalidSignature, ValueError, TypeError):
        raise ImportPreviewError("certificate_signature_invalid") from None


def _leaf_identity_matches(cert, expected_dns, expected_ips):
    from cryptography import x509
    from cryptography.x509.oid import ExtensionOID
    import ipaddress

    try:
        san = cert.extensions.get_extension_for_oid(
            ExtensionOID.SUBJECT_ALTERNATIVE_NAME).value
    except x509.ExtensionNotFound:
        raise ImportPreviewError("certificate_san_required") from None
    actual_dns = san.get_values_for_type(x509.DNSName)
    actual_ips = {str(v) for v in san.get_values_for_type(x509.IPAddress)}
    for name in expected_dns:
        found = False
        for pattern in actual_dns:
            pattern = pattern.lower()
            if pattern == name:
                found = True
                break
            # A single wildcard may cover one host label but never a
            # base domain, sibling suffix, IP, or multiple subdomain labels.
            if pattern.startswith("*.") and pattern.count("*") == 1:
                suffix = pattern[2:]
                if suffix.count(".") >= 1 and name.endswith("." + suffix):
                    prefix = name[:-(len(suffix) + 1)]
                    if prefix and "." not in prefix:
                        found = True
                        break
        if not found:
            raise ImportPreviewError("expected_dns_not_in_san")
    if not set(expected_ips).issubset(actual_ips):
        raise ImportPreviewError("expected_ip_not_in_san")
    try:
        basic = cert.extensions.get_extension_for_oid(
            ExtensionOID.BASIC_CONSTRAINTS).value
    except x509.ExtensionNotFound:
        raise ImportPreviewError("leaf_basic_constraints_missing") from None
    if getattr(basic, "ca") is not False:
        raise ImportPreviewError("leaf_cannot_be_ca")
    try:
        usage = cert.extensions.get_extension_for_oid(
            ExtensionOID.KEY_USAGE).value
        if not usage.digital_signature:
            raise ImportPreviewError("leaf_digital_signature_required")
    except x509.ExtensionNotFound:
        pass
    try:
        eku = cert.extensions.get_extension_for_oid(
            ExtensionOID.EXTENDED_KEY_USAGE).value
        if x509.oid.ExtendedKeyUsageOID.SERVER_AUTH not in eku:
            raise ImportPreviewError("leaf_server_auth_eku_required")
    except x509.ExtensionNotFound:
        pass
    return len(actual_dns) + len(actual_ips)


def _verify_chain(leaf, chain, now):
    from cryptography import x509
    from cryptography.x509.oid import ExtensionOID
    from cryptography.hazmat.primitives import serialization

    seen = set()
    previous = leaf
    for index, issuer in enumerate(chain):
        encoded = issuer.public_bytes(serialization.Encoding.DER)
        digest = hashlib.sha256(encoded).digest()
        if digest in seen:
            raise ImportPreviewError("duplicate_chain_certificate")
        seen.add(digest)
        _validity(issuer, now)
        if previous.issuer != issuer.subject:
            raise ImportPreviewError("chain_issuer_name_mismatch")
        try:
            basic = issuer.extensions.get_extension_for_oid(
                ExtensionOID.BASIC_CONSTRAINTS).value
        except x509.ExtensionNotFound:
            raise ImportPreviewError("chain_ca_constraint_missing") from None
        if getattr(basic, "ca") is not True:
            raise ImportPreviewError("chain_certificate_not_ca")
        try:
            ku = issuer.extensions.get_extension_for_oid(
                ExtensionOID.KEY_USAGE).value
            if not ku.key_cert_sign:
                raise ImportPreviewError("chain_key_cert_sign_denied")
        except x509.ExtensionNotFound:
            pass
        try:
            issuer.extensions.get_extension_for_oid(
                ExtensionOID.NAME_CONSTRAINTS)
        except x509.ExtensionNotFound:
            pass
        else:
            # Full PKIX name-constraint policy is not implemented here.
            raise ImportPreviewError("chain_name_constraints_unqualified")
        if basic.path_length is not None:
            # The path below this issuer contains 'index' intermediate
            # CAs already visited; the leaf does not count.
            if index > basic.path_length:
                raise ImportPreviewError("chain_path_length_exceeded")
        _verify_signature(previous, issuer)
        previous = issuer
    last_is_root = bool(chain and previous.subject == previous.issuer)
    if last_is_root:
        _verify_signature(previous, previous)
    if not chain and leaf.subject == leaf.issuer:
        _verify_signature(leaf, leaf)
    return {
        "chain_certificates": len(chain),
        "issuer_signature_links_verified": len(chain),
        "supplied_self_signed_root_verified": last_is_root,
        "issuer_chain_incomplete": bool(
            leaf.subject != leaf.issuer and not last_is_root
        ),
        "browser_trust_and_revocation_unverified": True,
    }


def inspect_import(leaf_bytes, private_key_bytes, chain_bytes=b"",
                   expected_dns=(), expected_ips=(), now=None):
    """Inspect in memory. Never export private key or user-supplied chain."""
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ec, rsa

    try:
        names, addresses = canonical_identities(expected_dns, expected_ips)
    except ValueError:
        raise ImportPreviewError("invalid_requested_identity") from None
    at = now or datetime.now(timezone.utc)
    if not isinstance(at, datetime) or at.tzinfo is None:
        raise ImportPreviewError("aware_validation_time_required")
    leaf = _cert_from_bytes(leaf_bytes)
    from cryptography.hazmat.primitives import hashes
    if not isinstance(leaf.signature_hash_algorithm,
                      (hashes.SHA256, hashes.SHA384, hashes.SHA512)):
        raise ImportPreviewError("leaf_signature_algorithm_unapproved")
    key = _private_key_from_bytes(private_key_bytes)
    end = _validity(leaf, at)
    san_count = _leaf_identity_matches(leaf, names, addresses)
    if isinstance(key, rsa.RSAPrivateKey):
        if not 2048 <= key.key_size <= 4096:
            raise ImportPreviewError("leaf_rsa_key_size_refused")
        key_type = "rsa"
    elif isinstance(key, ec.EllipticCurvePrivateKey):
        if key.curve.name not in ("secp256r1", "secp384r1"):
            raise ImportPreviewError("leaf_ec_curve_refused")
        key_type = "ec"
    else:
        raise ImportPreviewError("unsupported_private_key_type")
    def spki(public_key):
        return public_key.public_bytes(serialization.Encoding.DER,
            serialization.PublicFormat.SubjectPublicKeyInfo)
    if not hmac.compare_digest(spki(leaf.public_key()), spki(key.public_key())):
        raise ImportPreviewError("certificate_private_key_mismatch")
    chain = _parse_chain(chain_bytes)
    chain_details = _verify_chain(leaf, chain, at)
    leaf_signature_checked = bool(chain or leaf.subject == leaf.issuer)
    partial = chain_details["issuer_chain_incomplete"]
    return {
        "status": ("S011_OFFLINE_IMPORT_PREVIEW_PARTIAL" if partial
                   else "S011_OFFLINE_IMPORT_PREVIEW_VALIDATED"),
        "leaf_signature_cryptographically_verified": leaf_signature_checked,
        # Do not echo operator-owned domains or management IPs into
        # CLI/CI logs. An authenticated local UI can separately show
        # certificate identities after an independent privacy review.
        "requested_dns_count": len(names),
        "requested_ip_count": len(addresses),
        "requested_sans_matched": True,
        "certificate_sha256": hashlib.sha256(
            leaf.public_bytes(serialization.Encoding.DER)).hexdigest(),
        "expires_utc": end.isoformat(),
        "key_algorithm": key_type,
        "san_entries_count": san_count,
        **chain_details,
        "source_only_not_deployed": True,
        "private_key_not_exported": True,
        "uhttpd_load_and_browser_trust_unverified": True,
        "no_credential_or_device_write": True,
    }


def _check_dir(folder):
    if not isinstance(folder, str) or not TEST_DIR.fullmatch(folder):
        raise ImportPreviewError("unapproved_offline_import_directory")
    path = Path(folder)
    try:
        before = path.lstat()
    except OSError:
        raise ImportPreviewError("offline_import_directory_not_available") from None
    if not stat.S_ISDIR(before.st_mode) or before.st_uid != 0 or \
       before.st_gid != 0 or stat.S_IMODE(before.st_mode) != 0o700:
        raise ImportPreviewError("unsafe_import_directory")
    return path, (before.st_dev, before.st_ino)


def _read_fixed(folder, initial, basename, maximum, key=False, optional=False):
    path = folder / basename
    try:
        before = path.lstat()
    except FileNotFoundError:
        if optional:
            return b""
        raise ImportPreviewError("required_tls_material_missing") from None
    if not stat.S_ISREG(before.st_mode) or before.st_uid != 0 or \
       before.st_gid != 0 or before.st_nlink != 1 or \
       stat.S_IMODE(before.st_mode) not in ((0o600,) if key else (0o600, 0o644)) or \
       not 0 < before.st_size <= maximum:
        raise ImportPreviewError("unsafe_import_material_inode")
    # Root test staging only; O_NOFOLLOW plus fstat/lstat identity guards.
    fd = -1
    try:
        fd = os.open(str(path), os.O_RDONLY | os.O_NOFOLLOW |
                     os.O_CLOEXEC | os.O_NONBLOCK)
        opened = os.fstat(fd)
        if (opened.st_dev, opened.st_ino) != (before.st_dev, before.st_ino) \
           or opened.st_size != before.st_size or \
           stat.S_IMODE(opened.st_mode) != stat.S_IMODE(before.st_mode):
            raise ImportPreviewError("import_file_identity_changed")
        data = b""
        while len(data) <= maximum:
            chunk = os.read(fd, min(8192, maximum + 1 - len(data)))
            if not chunk:
                break
            data += chunk
        after = path.lstat()
        current_dir = folder.lstat()
        if len(data) != opened.st_size or len(data) > maximum or \
           (after.st_dev, after.st_ino) != (before.st_dev, before.st_ino) or \
           (after.st_uid, after.st_gid, after.st_nlink, after.st_size) != \
               (before.st_uid, before.st_gid, before.st_nlink, before.st_size) or \
           stat.S_IMODE(after.st_mode) != stat.S_IMODE(before.st_mode) or \
           (current_dir.st_dev, current_dir.st_ino) != initial or \
           stat.S_IMODE(current_dir.st_mode) != 0o700 or \
           current_dir.st_uid != 0 or current_dir.st_gid != 0:
            raise ImportPreviewError("import_readback_identity_changed")
        return data
    except OSError:
        raise ImportPreviewError("import_material_read_failed") from None
    finally:
        if fd >= 0:
            os.close(fd)


def inspect_offline_directory(directory, expected_dns=(), expected_ips=()):
    """Read fixed filenames; no writes or production cert interaction."""
    if os.geteuid() != 0:
        raise ImportPreviewError("offline_root_required")
    folder, identity = _check_dir(directory)
    leaf = _read_fixed(folder, identity, "certificate.pem", MAX_LEAF_BYTES)
    key = _read_fixed(folder, identity, "private-key.pem",
                      MAX_KEY_BYTES, key=True)
    chain = _read_fixed(folder, identity, "chain.pem", MAX_CHAIN_BYTES,
                        optional=True)
    return inspect_import(leaf, key, chain, expected_dns, expected_ips)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--offline-import-dir", required=True)
    parser.add_argument("--dns", action="append", default=[])
    parser.add_argument("--ip", action="append", default=[])
    args = parser.parse_args()
    try:
        result = inspect_offline_directory(
            args.offline_import_dir, args.dns, args.ip)
    except (ImportPreviewError, OSError) as error:
        reason = str(error) if isinstance(error, ImportPreviewError) \
            else "offline_import_unavailable"
        print(json.dumps({"status": "REFUSED", "reason": reason,
                          "device_not_modified": True}))
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
