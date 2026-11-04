#!/usr/bin/env python3
"""S-014: OFFLINE read-only TLS private-key and certificate-health audit.

Only named, disposable Hermes test directories are eligible for reads.
The module does not change permissions, reload uhttpd, copy private
keys, apply UCI settings, or modify any ONU firmware bank.
"""
from datetime import datetime, timezone, timedelta
import argparse
import json
import os
from pathlib import Path
import re
import stat

from s011_offline_certificate_import import inspect_import, ImportPreviewError

TEST_DIR = re.compile(r"^/var/tmp/aott-s014-tls-test-[A-Za-z0-9_-]{6,40}$")
CERT_FILENAME = "candidate.crt.der"
KEY_FILENAME = "candidate.key.der"
MAX_CERT = 16384
MAX_KEY = 16384


class TLSAuditError(ValueError):
    pass


def _safe_status(mode, uid, gid, nlink, kind, *, key):
    """Static root-only mode checks, never rewrite an existing inode."""
    errors = []
    if kind != "regular":
        errors.append("unexpected_inode_type")
    if uid != 0 or gid != 0:
        errors.append("not_root_owned")
    if nlink != 1:
        errors.append("multiple_links_or_unknown")
    if type(mode) is not int or mode not in (
        (0o400, 0o600) if key else (0o600, 0o644)):
        errors.append("private_key_not_root_only" if key
                      else "certificate_mode_unqualified")
    return errors


def evaluate_metadata(directory, certificate, private_key):
    """Evaluate only supplied facts, with no filesystem access."""
    if not isinstance(directory, dict) or not isinstance(certificate, dict) \
            or not isinstance(private_key, dict):
        raise TLSAuditError("metadata_required")
    if set(directory) != {"mode", "uid", "gid", "kind"}:
        raise TLSAuditError("directory_metadata_unqualified")
    if set(certificate) != {"mode", "uid", "gid", "nlink", "kind", "size"} or \
            set(private_key) != {"mode", "uid", "gid", "nlink", "kind", "size"}:
        raise TLSAuditError("material_metadata_unqualified")
    issues = []
    if directory["kind"] != "directory" or directory["uid"] != 0 or \
            directory["gid"] != 0 or directory["mode"] != 0o700:
        issues.append("parent_directory_untrusted")
    issues.extend(_safe_status(
        certificate["mode"], certificate["uid"], certificate["gid"],
        certificate["nlink"], certificate["kind"], key=False))
    issues.extend(_safe_status(
        private_key["mode"], private_key["uid"], private_key["gid"],
        private_key["nlink"], private_key["kind"], key=True))
    for label, info, maximum in [
        ("certificate", certificate, MAX_CERT),
        ("private_key", private_key, MAX_KEY),
    ]:
        value = info["size"]
        if type(value) is not int or value < 1 or value > maximum:
            issues.append(label + "_size_unqualified")
    return sorted(set(issues))


def audit_source_material(cert_bytes, key_bytes, dns=(), ips=(),
                          metadata=None, now=None,
                          offline_vendor_handshake=None):
    """Create a privacy-redacted, SOURCE-ONLY health warning receipt.

    The only accepted strong TLS evidence is an independently supplied
    result from the separate vendor-loopback emulator. Even that is not
    proof of live on-stick HTTPS availability, browser trust or WAN reach.
    """
    result = {
        "schema": 1,
        "source_only_not_deployed": True,
        "live_onu_certificate_unverified": True,
        "browser_trust_unverified": True,
        "remote_access_disabled_by_default": True,
        "tls_service_changed": False,
        "private_key_permissions_changed": False,
        "no_uci_or_firmware_write": True,
        "key_or_hostname_exported": False,
    }
    if not isinstance(metadata, dict) or set(metadata) != (
        {"directory", "certificate", "private_key"}
    ):
        raise TLSAuditError("metadata_required")
    issues = evaluate_metadata(
        metadata["directory"], metadata["certificate"],
        metadata["private_key"])
    if issues:
        result.update(status="SOURCE_TLS_STORAGE_REMEDIATION_REQUIRED",
                      warnings=issues, source_material_validated=False)
        return result
    if not isinstance(cert_bytes, bytes) or not isinstance(key_bytes, bytes) \
            or not 1 <= len(cert_bytes) <= MAX_CERT or \
            not 1 <= len(key_bytes) <= MAX_KEY:
        result.update(status="SOURCE_TLS_MATERIAL_UNAVAILABLE",
                      warnings=["invalid_certificate_or_key_bytes"],
                      source_material_validated=False)
        return result
    at = now or datetime.now(timezone.utc)
    if not isinstance(at, datetime) or at.tzinfo is None:
        raise TLSAuditError("aware_validation_time_required")
    try:
        inspection = inspect_import(cert_bytes, key_bytes,
                                    expected_dns=dns, expected_ips=ips, now=at)
    except ImportPreviewError:
        result.update(status="SOURCE_TLS_MATERIAL_REMEDIATION_REQUIRED",
                      warnings=["certificate_key_or_identity_unverified"],
                      source_material_validated=False)
        return result
    warnings = []
    if inspection["status"] != "S011_OFFLINE_IMPORT_PREVIEW_VALIDATED" or \
            not inspection["leaf_signature_cryptographically_verified"]:
        warnings.append("certificate_signature_path_incomplete")
    expiration = datetime.fromisoformat(inspection["expires_utc"])
    remaining = expiration - at
    if remaining <= timedelta(days=30):
        warnings.append("certificate_expires_within_30_days")
    if offline_vendor_handshake is not True:
        warnings.append("vendor_tls_load_not_verified")
    if warnings:
        status = "SOURCE_TLS_REVIEW_REQUIRED"
    else:
        status = "SOURCE_CERT_AND_VENDOR_EMULATION_VERIFIED"
    result.update(status=status, warnings=sorted(warnings),
                  source_material_validated=True,
                  verified_dns_count=inspection["requested_dns_count"],
                  verified_ip_count=inspection["requested_ip_count"],
                  verified_tls_san_matches=inspection["requested_sans_matched"],
                  expires_within_30_days=remaining <= timedelta(days=30),
                  vendor_emulated_tls_load=offline_vendor_handshake is True,
                  cert_key_storage_mode="root_only_0400_or_0600",
                  root_owned_private_key=True)
    return result


def _offline_dir(directory):
    if type(directory) is not str or not TEST_DIR.fullmatch(directory):
        raise TLSAuditError("unapproved_offline_test_directory")
    folder = Path(directory)
    try:
        st = folder.lstat()
    except OSError:
        raise TLSAuditError("offline_directory_unavailable") from None
    if not stat.S_ISDIR(st.st_mode) or st.st_uid != 0 or st.st_gid != 0 \
            or stat.S_IMODE(st.st_mode) != 0o700:
        raise TLSAuditError("untrusted_offline_test_directory")
    return folder, st


def _fixed_file(folder, folder_stat, basename, max_size, *, key):
    path = folder / basename
    try:
        before = path.lstat()
    except OSError:
        raise TLSAuditError("offline_tls_material_unavailable") from None
    fields = {
        "mode": stat.S_IMODE(before.st_mode),
        "uid": before.st_uid,
        "gid": before.st_gid,
        "nlink": before.st_nlink,
        "kind": "regular" if stat.S_ISREG(before.st_mode) else "other",
        "size": before.st_size,
    }
    # Never read/echo private data when metadata is already unsafe.
    if _safe_status(fields["mode"], fields["uid"], fields["gid"],
                    fields["nlink"], fields["kind"], key=key) or \
            not 1 <= fields["size"] <= max_size:
        return None, fields
    fd = -1
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW |
                     os.O_NONBLOCK | os.O_CLOEXEC)
        opened = os.fstat(fd)
        if (opened.st_ino, opened.st_dev) != (before.st_ino, before.st_dev) or \
                opened.st_nlink != 1 or \
                stat.S_IMODE(opened.st_mode) != fields["mode"] or \
                opened.st_size != before.st_size:
            raise TLSAuditError("unsafe_tls_inode_changed")
        raw = os.read(fd, max_size + 1)
        after = path.lstat()
        current = folder.lstat()
        if (after.st_ino, after.st_dev) != (before.st_ino, before.st_dev) or \
           (after.st_uid, after.st_gid, after.st_nlink, after.st_size) != \
               (before.st_uid, before.st_gid, before.st_nlink, before.st_size) or \
           stat.S_IMODE(after.st_mode) != fields["mode"] or \
           (current.st_ino, current.st_dev) != (folder_stat.st_ino, folder_stat.st_dev) or \
           stat.S_IMODE(current.st_mode) != 0o700 or \
           len(raw) != fields["size"] or len(raw) > max_size:
            raise TLSAuditError("unsafe_tls_readback_changed")
        return raw, fields
    except OSError:
        raise TLSAuditError("tls_material_read_failed") from None
    finally:
        if fd >= 0:
            os.close(fd)


def inspect_offline_candidate(directory, dns=(), ips=(), now=None):
    """Read only fixed disposable candidate files. No chmod or reload."""
    if os.geteuid() != 0:
        raise TLSAuditError("root_owned_fixture_required")
    folder, st = _offline_dir(directory)
    cert, cmeta = _fixed_file(folder, st, CERT_FILENAME, MAX_CERT, key=False)
    key, kmeta = _fixed_file(folder, st, KEY_FILENAME, MAX_KEY, key=True)
    meta = {
        "directory": {"mode": stat.S_IMODE(st.st_mode), "uid": st.st_uid,
                      "gid": st.st_gid, "kind": "directory"},
        "certificate": cmeta,
        "private_key": kmeta,
    }
    # Always record offline evidence only. The reader cannot infer a
    # real uhttpd handshake merely because the certificate parses.
    return audit_source_material(cert, key, dns, ips, meta, now)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--offline-candidate-dir", required=True)
    parser.add_argument("--dns", action="append", default=[])
    parser.add_argument("--ip", action="append", default=[])
    opts = parser.parse_args()
    try:
        outcome = inspect_offline_candidate(
            opts.offline_candidate_dir, opts.dns, opts.ip)
        print(json.dumps(outcome, sort_keys=True))
        return 0 if outcome["source_material_validated"] else 2
    except (TLSAuditError, OSError):
        print(json.dumps({
            "status": "SOURCE_TLS_UNVERIFIED",
            "source_only_not_deployed": True,
            "no_uci_or_firmware_write": True,
        }))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
