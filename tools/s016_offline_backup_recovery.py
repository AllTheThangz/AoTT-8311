#!/usr/bin/env python3
"""S-016: offline configuration backup, encrypted export and restore planner.

Pure in-memory operations. No filesystem, device, network or firmware I/O.
Uses host Python cryptography only for disposable source validation, not
as an assumed dependency of the residential ONU firmware.
"""
import base64
import binascii
import copy
import hashlib
import json
import os
import re

SCHEMA = 1
ARCHIVE_FORMAT = "aott-s016-private-v1"
AAD = b"AoTT-S016-private-v1"
KDF = "scrypt-n16384-r8-p1"
MAX_DATA_BYTES = 49152
MAX_ARCHIVE_BYTES = 131072
PROFILE_KEYS = frozenset({
    "board_id", "abi", "partition_profile", "optics_profile",
})
BUNDLE_KEYS = frozenset({
    "schema", "profile", "source_bank", "source_firmware_sha256",
    "configuration_revision", "values",
})
TARGET_KEYS = frozenset({
    "profile", "active_bank", "firmware_sha256", "configuration_revision",
})
# These fields are a limited prototype schema, not a claim of complete
# 54-control GUI coverage or a reader for arbitrary vendor UCI files.
FIELDS = {
    "management.hostname": "private",
    "management.ipv4": "private",
    "management.ipv6": "private",
    "management.vlan": "private",
    "pon.serial": "private",
    "pon.loid": "private",
    "pon.registration_password": "private",
    "uhttpd.cert_der": "private",
    "uhttpd.private_key_der": "private",
    "uhttpd.redirect_https": "boolean",
    "telemetry.syslog_destination": "private",
    "telemetry.enabled": "boolean",
    "remote_gui.enabled": "boolean",
    "remote_gui.source_cidrs": "private",
    "sampling.enabled": "boolean",
    "sampling.interval_seconds": "interval",
}
PRIVATE_VALUE_FIELDS = tuple(
    name for name, kind in FIELDS.items() if kind == "private"
)
ENVELOPE_KEYS = frozenset({
    "format", "kdf", "salt", "nonce", "ciphertext",
})
REQUIRED_GUARDS = (
    "independent_recovery_verified",
    "existing_private_backup_verified",
    "known_good_firmware_bank_preserved",
    "configuration_snapshot_verified",
    "management_recovery_path_verified",
    "target_revision_verified",
    "restore_schema_compatible",
)
SHA256 = re.compile(r"^[0-9a-f]{64}$")
NAME = re.compile(r"^[a-z][a-z0-9_.-]{1,63}$")
REVISION_MIN, REVISION_MAX = 1, 1000000


class SourceRecoveryError(ValueError):
    """A fixed, non-secret refusal code."""


def _json_bytes(value):
    return json.dumps(
        value, sort_keys=True, ensure_ascii=True,
        separators=(",", ":"), allow_nan=False
    ).encode("ascii")


def _profile(value):
    if not isinstance(value, dict) or set(value) != PROFILE_KEYS:
        raise SourceRecoveryError("profile_identity_incomplete")
    for key, item in value.items():
        if type(item) is not str or not NAME.fullmatch(item):
            raise SourceRecoveryError("invalid_hardware_profile")
    return dict(value)


def _values(raw):
    if not isinstance(raw, dict) or not raw or len(raw) > len(FIELDS):
        raise SourceRecoveryError("config_values_unqualified")
    validated = {}
    for key, val in raw.items():
        kind = FIELDS.get(key)
        if kind is None:
            raise SourceRecoveryError("unknown_config_field")
        if kind == "boolean":
            if type(val) is not bool:
                raise SourceRecoveryError("invalid_boolean_config_value")
        elif kind == "interval":
            if type(val) is not int or val not in (30, 60, 120, 300):
                raise SourceRecoveryError("unsupported_sampling_interval")
        elif kind == "private":
            max_len = 16384 if key in (
                "uhttpd.cert_der", "uhttpd.private_key_der") else 2048
            if type(val) is not str or not 1 <= len(val) <= max_len:
                raise SourceRecoveryError("invalid_private_config_value")
            if "\x00" in val:
                raise SourceRecoveryError("invalid_private_config_value")
        validated[key] = val
    return validated


def validate_bundle(bundle):
    """Strict source schema for a single device profile and one bank."""
    if not isinstance(bundle, dict) or set(bundle) != BUNDLE_KEYS:
        raise SourceRecoveryError("bundle_schema_mismatch")
    if bundle["schema"] != SCHEMA or type(bundle["schema"]) is not int:
        raise SourceRecoveryError("unsupported_bundle_schema")
    profile = _profile(bundle["profile"])
    bank = bundle["source_bank"]
    if bank not in ("A", "B") or type(bank) is not str:
        raise SourceRecoveryError("invalid_source_bank")
    digest = bundle["source_firmware_sha256"]
    if type(digest) is not str or not SHA256.fullmatch(digest):
        raise SourceRecoveryError("unverified_firmware_fingerprint")
    rev = bundle["configuration_revision"]
    if type(rev) is not int or not REVISION_MIN <= rev <= REVISION_MAX:
        raise SourceRecoveryError("invalid_configuration_revision")
    values = _values(bundle["values"])
    result = {
        "schema": SCHEMA, "profile": profile, "source_bank": bank,
        "source_firmware_sha256": digest,
        "configuration_revision": rev, "values": values,
    }
    if len(_json_bytes(result)) > MAX_DATA_BYTES:
        raise SourceRecoveryError("backup_payload_too_large")
    return result


def public_redacted_export(bundle):
    """Safe-by-default JSON, no secret, host, IP, MAC or value-derived hash."""
    validated = validate_bundle(bundle)
    data = {
        "schema": SCHEMA,
        "kind": "aott_s016_redacted_public_preview",
        "source_only_not_live": True,
        "no_credentials_or_device_identity_included": True,
        "configuration_values": {},
        "configuration_field_count": len(validated["values"]),
        "private_fields_redacted": 0,
        "source_profile_redacted": True,
        "source_bank_redacted": True,
        "firmware_identity_redacted": True,
    }
    for name, val in sorted(validated["values"].items()):
        if FIELDS[name] == "private":
            data["configuration_values"][name] = "[redacted]"
            data["private_fields_redacted"] += 1
        else:
            data["configuration_values"][name] = val
    return _json_bytes(data)


def _passphrase(passphrase):
    if type(passphrase) is not bytes or not 12 <= len(passphrase) <= 512:
        raise SourceRecoveryError("strong_in_memory_passphrase_required")
    return passphrase


def _derive_key(passphrase, salt):
    from cryptography.hazmat.primitives.kdf.scrypt import Scrypt
    return Scrypt(salt=salt, length=32, n=16384, r=8, p=1).derive(
        _passphrase(passphrase)
    )


def _b64(binary):
    return base64.b64encode(binary).decode("ascii")


def _unb64(encoded, expected=None, maximum=MAX_ARCHIVE_BYTES):
    if type(encoded) is not str or len(encoded) > maximum * 2:
        raise SourceRecoveryError("invalid_encrypted_archive")
    try:
        raw = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError):
        raise SourceRecoveryError("invalid_encrypted_archive") from None
    if len(raw) > maximum or (expected is not None and len(raw) != expected):
        raise SourceRecoveryError("invalid_encrypted_archive")
    return raw


def encrypted_private_export(bundle, passphrase):
    """AEAD archive returned as bytes. Never log, save, or print its contents."""
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    validated = validate_bundle(bundle)
    _passphrase(passphrase)
    salt, nonce = os.urandom(16), os.urandom(12)
    raw = _json_bytes(validated)
    ciphertext = AESGCM(_derive_key(passphrase, salt)).encrypt(
        nonce, raw, AAD
    )
    envelope = {
        "format": ARCHIVE_FORMAT,
        "kdf": KDF, "salt": _b64(salt),
        "nonce": _b64(nonce), "ciphertext": _b64(ciphertext),
    }
    encoded = _json_bytes(envelope)
    if len(encoded) > MAX_ARCHIVE_BYTES:
        raise SourceRecoveryError("encrypted_archive_too_large")
    return encoded


def decrypt_private_archive(archive, passphrase):
    """Bounded authenticated decryption before parsing any user configuration."""
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    from cryptography.exceptions import InvalidTag
    _passphrase(passphrase)
    if type(archive) is not bytes or not 1 <= len(archive) <= MAX_ARCHIVE_BYTES:
        raise SourceRecoveryError("invalid_encrypted_archive")
    try:
        header = json.loads(archive)
    except (ValueError, UnicodeError):
        raise SourceRecoveryError("invalid_encrypted_archive") from None
    if not isinstance(header, dict) or set(header) != ENVELOPE_KEYS or \
            header["format"] != ARCHIVE_FORMAT or header["kdf"] != KDF:
        raise SourceRecoveryError("unsupported_archive_format")
    # Refuse duplicate keys, non-canonical serialization, unsanctioned
    # KDF parameters and trailing JSON before attempting any key derivation.
    if _json_bytes(header) != archive:
        raise SourceRecoveryError("noncanonical_encrypted_archive")
    salt = _unb64(header["salt"], expected=16)
    nonce = _unb64(header["nonce"], expected=12)
    payload = _unb64(header["ciphertext"], maximum=MAX_DATA_BYTES + 32)
    if len(payload) < 17:
        raise SourceRecoveryError("invalid_encrypted_archive")
    try:
        plaintext = AESGCM(_derive_key(passphrase, salt)).decrypt(
            nonce, payload, AAD
        )
    except (InvalidTag, ValueError):
        raise SourceRecoveryError("archive_authentication_failed") from None
    if len(plaintext) > MAX_DATA_BYTES:
        raise SourceRecoveryError("archive_payload_too_large")
    try:
        data = json.loads(plaintext)
    except (ValueError, UnicodeError):
        raise SourceRecoveryError("invalid_decrypted_payload") from None
    if _json_bytes(data) != plaintext:
        raise SourceRecoveryError("noncanonical_decrypted_payload")
    return validate_bundle(data)


def _target(target):
    if not isinstance(target, dict) or set(target) != TARGET_KEYS:
        raise SourceRecoveryError("target_descriptor_unqualified")
    profile = _profile(target["profile"])
    bank = target["active_bank"]
    if type(bank) is not str or bank not in ("A", "B"):
        raise SourceRecoveryError("target_bank_unqualified")
    sha = target["firmware_sha256"]
    if type(sha) is not str or not SHA256.fullmatch(sha):
        raise SourceRecoveryError("target_firmware_hash_unqualified")
    rev = target["configuration_revision"]
    if type(rev) is not int or not REVISION_MIN <= rev <= REVISION_MAX:
        raise SourceRecoveryError("target_revision_unqualified")
    return dict(target, profile=profile)


def plan_restore(bundle, target, expected_revision, guard_receipts,
                 operator_approved=False, migration_approved=False):
    """No writes; fail closed if target, fallback or operator evidence absent."""
    data = validate_bundle(bundle)
    dest = _target(target)
    if operator_approved is not True:
        raise SourceRecoveryError("restore_requires_explicit_operator_authorization")
    if type(expected_revision) is not int or \
            expected_revision != dest["configuration_revision"]:
        raise SourceRecoveryError("target_configuration_revision_changed")
    if data["profile"] != dest["profile"]:
        raise SourceRecoveryError("different_board_or_partition_profile")
    migrates = (
        data["source_bank"] != dest["active_bank"] or
        data["source_firmware_sha256"] != dest["firmware_sha256"]
    )
    if migrates and migration_approved is not True:
        raise SourceRecoveryError("cross_bank_or_firmware_migration_not_approved")
    if not isinstance(guard_receipts, dict):
        guard_receipts = {}
    missing = [
        name for name in REQUIRED_GUARDS
        if guard_receipts.get(name) is not True
    ]
    values = data["values"]
    if "uhttpd.private_key_der" in values or \
            "uhttpd.cert_der" in values:
        if guard_receipts.get("tls_pair_and_rollback_verified") is not True:
            missing.append("tls_pair_and_rollback_verified")
    if values.get("remote_gui.enabled") is True:
        if guard_receipts.get("remote_gui_default_deny_and_rollback_verified") is not True:
            missing.append("remote_gui_default_deny_and_rollback_verified")
    if missing:
        return {
            "status": "SOURCE_RESTORE_BLOCKED",
            "missing_guards": sorted(missing),
            "source_only_not_deployed": True,
            "no_restore_or_flash_write": True,
        }
    return {
        "status": "SOURCE_RESTORE_PLAN_READY_NOT_DEPLOYED",
        "requires_dedicated_production_approval": True,
        "migration_requested": bool(migrates),
        "planned_field_count": len(values),
        "sensitive_fields_present": any(k in PRIVATE_VALUE_FIELDS for k in values),
        "source_only_not_deployed": True,
        "no_restore_or_flash_write": True,
        "no_reboot_or_bank_commit": True,
    }


def preview_encrypted_restore(archive, passphrase, target,
                              expected_revision, guard_receipts,
                              operator_approved=False,
                              migration_approved=False):
    """Authenticate/decrypt first, then evaluate exact restore guards.

    The public redacted preview, untrusted plaintext and tampered
    archives cannot be used as an authenticated restore source.
    No caller receives the decrypted secret-bearing configuration.
    """
    payload = decrypt_private_archive(archive, passphrase)
    return plan_restore(
        payload, target, expected_revision, guard_receipts,
        operator_approved=operator_approved,
        migration_approved=migration_approved)


def simulate_shadow_restore(current, replacement, fail_after=None):
    """Model failure/rollback without mutating the caller's dictionaries."""
    prior = copy.deepcopy(current)
    if not isinstance(prior, dict) or not isinstance(replacement, dict):
        raise SourceRecoveryError("shadow_config_required")
    if any(k not in FIELDS for k in prior) or any(k not in FIELDS for k in replacement):
        raise SourceRecoveryError("shadow_unknown_field")
    if fail_after is not None and (type(fail_after) is not int or fail_after < 0):
        raise SourceRecoveryError("invalid_failure_injection")
    shadow = copy.deepcopy(prior)
    for i, (key, val) in enumerate(sorted(replacement.items())):
        if fail_after is not None and i >= fail_after:
            return {
                "status": "SOURCE_SHADOW_ROLLBACK_VERIFIED",
                "result": prior, "rolled_back": True,
                "source_only_not_deployed": True,
            }
        shadow[key] = val
    _values(shadow)
    return {
        "status": "SOURCE_SHADOW_COMMIT_SYNTHETIC_ONLY",
        "result": shadow, "rolled_back": False,
        "source_only_not_deployed": True,
    }
