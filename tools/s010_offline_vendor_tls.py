#!/usr/bin/env python3
"""S-010 vendor px5g SAN certificate qualification, strictly OFFLINE.

This source tool runs the extracted vendor MIPS generator under QEMU,
writes only to isolated private /var/tmp test directories, and never
installs certificates, changes uhttpd, or accesses live hardware.
"""
import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess


class OfflineTLSError(ValueError):
    pass


CERT_NAME = "candidate.crt.der"
KEY_NAME = "candidate.key.der"
DNS_LABEL = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")
TEST_DIR = re.compile(r"^/var/tmp/aott-s010-cert-test-[A-Za-z0-9_-]{6,40}$")


def canonical_identities(dns=(), ips=()):
    if isinstance(dns, (str, bytes)) or isinstance(ips, (str, bytes)):
        raise OfflineTLSError("identity_collection_required")
    try:
        names = []
        for value in dns:
            if not isinstance(value, str) or not 1 <= len(value) <= 253:
                raise OfflineTLSError("invalid_dns_identity")
            try:
                value.encode("ascii")
            except UnicodeEncodeError:
                raise OfflineTLSError("invalid_dns_identity") from None
            name = value.lower()
            if any(not DNS_LABEL.fullmatch(part) for part in name.split(".")):
                raise OfflineTLSError("invalid_dns_identity")
            if re.fullmatch(r"[0-9.]+", name):
                raise OfflineTLSError("ip_identity_must_use_ip_san")
            names.append(name)
        addresses = []
        for value in ips:
            if not isinstance(value, str) or "%" in value:
                raise OfflineTLSError("invalid_ip_identity")
            try:
                addresses.append(str(ipaddress.ip_address(value)))
            except ValueError:
                raise OfflineTLSError("invalid_ip_identity") from None
    except TypeError:
        raise OfflineTLSError("invalid_identity_collection") from None
    if not 1 <= len(names) + len(addresses) <= 8:
        raise OfflineTLSError("identity_count_out_of_bounds")
    if len(set(names)) != len(names) or len(set(addresses)) != len(addresses):
        raise OfflineTLSError("duplicate_san_identity")
    return tuple(names), tuple(addresses)


def px5g_argv(binary, cert, key, dns=(), ips=(),
              days=365, key_type="ec-p256"):
    names, addresses = canonical_identities(dns, ips)
    if type(days) is not int or not 1 <= days <= 397:
        raise OfflineTLSError("invalid_validity_days")
    if key_type == "ec-p256":
        key_options = ["-newkey", "ec", "-pkeyopt", "ec_paramgen_curve:P-256"]
    elif key_type == "rsa-2048":
        key_options = ["-newkey", "rsa:2048"]
    else:
        raise OfflineTLSError("unsupported_key_type")
    common = names[0] if names else addresses[0]
    argv = [str(binary), "selfsigned", "-der", "-days", str(days),
            *key_options, "-keyout", str(key), "-out", str(cert),
            "-subj", f"/C=ZZ/O=Offline/CN={common}"]
    for name in names:
        argv.extend(["-addext", "subjectAltName=DNS:" + name])
    for address in addresses:
        argv.extend(["-addext", "subjectAltName=IP:" + address])
    return argv


def trusted_test_directory(directory):
    path = Path(directory)
    if not TEST_DIR.fullmatch(str(path)) or path.is_symlink() or \
            path.resolve() != path:
        raise OfflineTLSError("unapproved_offline_directory")
    try:
        st = path.lstat()
    except FileNotFoundError:
        raise OfflineTLSError("offline_directory_missing") from None
    if not stat.S_ISDIR(st.st_mode) or st.st_uid != 0 or st.st_gid != 0 \
            or stat.S_IMODE(st.st_mode) != 0o700:
        raise OfflineTLSError("unsafe_offline_directory")
    return path


def checked_file(path, key_material=False):
    if path.is_symlink():
        raise OfflineTLSError("tls_material_symlink_refused")
    st = path.lstat()
    if not stat.S_ISREG(st.st_mode) or st.st_uid != 0 or st.st_gid != 0 \
            or st.st_nlink != 1 or \
            stat.S_IMODE(st.st_mode) not in ((0o600,) if key_material \
                else (0o600, 0o644)) or not 1 <= st.st_size <= 16384:
        raise OfflineTLSError("unsafe_tls_material")
    return path.read_bytes()


def inspect_der_pair(cert_der, key_der, dns=(), ips=(), now=None):
    """Verify exact SAN, DER key pair, key size and expiry without any writes."""
    from cryptography import x509
    from cryptography.hazmat.primitives import serialization, hashes
    from cryptography.hazmat.primitives.asymmetric import ec, rsa, padding
    from cryptography.exceptions import InvalidSignature
    from cryptography.x509.oid import ExtensionOID

    names, addresses = canonical_identities(dns, ips)
    if len(cert_der) > 16384 or len(key_der) > 16384:
        raise OfflineTLSError("tls_material_too_large")
    try:
        cert = x509.load_der_x509_certificate(cert_der)
        key = serialization.load_der_private_key(key_der, password=None)
        san = cert.extensions.get_extension_for_oid(
            ExtensionOID.SUBJECT_ALTERNATIVE_NAME).value
        got_dns = san.get_values_for_type(x509.DNSName)
        got_ips = [str(v) for v in san.get_values_for_type(x509.IPAddress)]
        encode = lambda p: p.public_bytes(serialization.Encoding.DER,
            serialization.PublicFormat.SubjectPublicKeyInfo)
        if encode(cert.public_key()) != encode(key.public_key()):
            raise OfflineTLSError("tls_certificate_key_mismatch")
        if sorted(got_dns) != sorted(names) or sorted(got_ips) != sorted(addresses):
            raise OfflineTLSError("tls_san_mismatch")
        constraint = cert.extensions.get_extension_for_oid(
            ExtensionOID.BASIC_CONSTRAINTS).value
        if (getattr(constraint,"ca") is not False or
                getattr(cert,"issuer") != getattr(cert,"subject")):
            raise OfflineTLSError("tls_not_self_signed_leaf")
        if not isinstance(cert.signature_hash_algorithm, hashes.SHA256):
            raise OfflineTLSError("tls_signature_algorithm_unapproved")
        if isinstance(key, ec.EllipticCurvePrivateKey):
            if key.curve.name != "secp256r1":
                raise OfflineTLSError("tls_curve_unapproved")
            algorithm = "ec-p256"
        elif isinstance(key, rsa.RSAPrivateKey):
            if key.key_size != 2048:
                raise OfflineTLSError("tls_rsa_size_unapproved")
            algorithm = "rsa-2048"
        else:
            raise OfflineTLSError("tls_key_algorithm_unapproved")
        # "Same issuer and subject" is not proof that a certificate was
        # actually signed by its own public key. Verify the signature.
        if isinstance(cert.public_key(), ec.EllipticCurvePublicKey):
            cert.public_key().verify(
                cert.signature, cert.tbs_certificate_bytes,
                ec.ECDSA(cert.signature_hash_algorithm))
        else:
            cert.public_key().verify(
                cert.signature, cert.tbs_certificate_bytes,
                padding.PKCS1v15(), cert.signature_hash_algorithm)
        at = now or datetime.now(timezone.utc)
        start = cert.not_valid_before.replace(tzinfo=timezone.utc)
        end = cert.not_valid_after.replace(tzinfo=timezone.utc)
        if start > at + timedelta(minutes=5) or \
                end <= at + timedelta(hours=12) or \
                end - start > timedelta(days=398):
            raise OfflineTLSError("tls_certificate_invalid_validity")
    except OfflineTLSError:
        raise
    except (ValueError, TypeError, InvalidSignature, x509.ExtensionNotFound):
        raise OfflineTLSError("tls_certificate_parse_failed") from None
    return {
        "status": "S010_OFFLINE_VENDOR_CERT_VERIFIED",
        "dns": list(names), "ips": list(addresses),
        "key_type": algorithm, "expires_utc": end.isoformat(),
        "certificate_sha256": hashlib.sha256(cert_der).hexdigest(),
        "source_only_not_deployed": True,
        "live_https_and_hardware_not_tested": True,
        "no_firmware_or_isp_configuration_change": True,
    }


def generate_offline(vendor_rootfs, directory, dns=(), ips=(),
                     days=365, key_type="ec-p256"):
    if os.geteuid() != 0:
        raise OfflineTLSError("offline_root_required")
    names, addresses = canonical_identities(dns, ips)
    output = trusted_test_directory(directory)
    cert, key = output / CERT_NAME, output / KEY_NAME
    if cert.exists() or key.exists() or cert.is_symlink() or key.is_symlink():
        raise OfflineTLSError("candidate_already_exists")
    root = Path(vendor_rootfs)
    binary = root / "usr/sbin/px5g"
    if not binary.is_file() or not (root / "lib/ld-musl-mips-sf.so.1").exists():
        raise OfflineTLSError("offline_vendor_mips_px5g_unavailable")
    qemu = shutil.which("qemu-mips-static")
    if not qemu:
        raise OfflineTLSError("offline_qemu_unavailable")
    command = [qemu, "-L", str(root), *px5g_argv(binary, cert, key,
                names, addresses, days, key_type)]
    # RSA generation under MIPS emulation can take longer depending on
    # host entropy/CPU contention. Both algorithms retain hard bounds.
    offline_timeout = 60 if key_type == "rsa-2048" else 20
    try:
        subprocess.run(command, cwd="/", env={"PATH": "/usr/bin:/bin"},
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                       check=True, timeout=offline_timeout)
    except subprocess.TimeoutExpired:
        raise OfflineTLSError("vendor_generator_timeout") from None
    except subprocess.CalledProcessError:
        raise OfflineTLSError("vendor_generator_failed") from None
    report = inspect_der_pair(checked_file(cert), checked_file(key, key_material=True),
                              names, addresses)
    report["key_mode"] = "0600"
    report["vendor_px5g_sha256"] = hashlib.sha256(binary.read_bytes()).hexdigest()
    report["candidate_only_no_install_or_reload"] = True
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--vendor-rootfs", required=True)
    parser.add_argument("--offline-test-dir", required=True)
    parser.add_argument("--dns", action="append", default=[])
    parser.add_argument("--ip", action="append", default=[])
    parser.add_argument("--days", type=int, default=365)
    parser.add_argument("--key-type", choices=("ec-p256", "rsa-2048"),
                        default="ec-p256")
    args = parser.parse_args()
    try:
        receipt = generate_offline(
            args.vendor_rootfs, args.offline_test_dir, args.dns, args.ip,
            args.days, args.key_type)
    except (OfflineTLSError, OSError) as error:
        reason = str(error) if isinstance(error, OfflineTLSError) \
            else "offline_validation_unavailable"
        print(json.dumps({"status": "REFUSED", "reason": reason,
                          "device_not_modified": True}))
        return 1
    print(json.dumps(receipt, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
