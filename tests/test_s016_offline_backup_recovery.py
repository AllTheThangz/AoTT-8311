"""S-016 source-only, encrypted config and failure/recovery regression tests.

All values are synthetic. Never load a real ONU config, subscriber
identity, TLS key or password into this test suite or public repo.
"""
import base64
import copy
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from s016_offline_backup_recovery import (
    SourceRecoveryError, validate_bundle, public_redacted_export,
    encrypted_private_export, decrypt_private_archive, plan_restore,
    preview_encrypted_restore, simulate_shadow_restore, REQUIRED_GUARDS,
)

FAKE_ID = "fixture" + "-not-a-subscriber"
FAKE_HOST = "fixture" + ".example.invalid"
FAKE_SECRET = "synthetic" + "-credential-value-not-real"
FAKE_IP = ".".join(("192", "0", "2", "10"))
FAKE_CERT = "synthetic" + "-der-certificate-placeholder"
FAKE_KEY = "synthetic" + "-der-private-key-placeholder"
PASSPHRASE = b"synthetic" + b"-offline-keystore-test-passphrase"


def profile():
    return {
        "board_id": "prx126-research",
        "abi": "mips_24kc_nomips16",
        "partition_profile": "prx300-lab-layout",
        "optics_profile": "ll-xs1010-lab",
    }


def bundle(**replacements):
    data = {
        "schema": 1,
        "profile": profile(),
        "source_bank": "B",
        "source_firmware_sha256": "a" * 64,
        "configuration_revision": 17,
        "values": {
            "pon.serial": FAKE_ID,
            "pon.registration_password": FAKE_SECRET,
            "management.hostname": FAKE_HOST,
            "management.ipv4": FAKE_IP,
            "uhttpd.cert_der": FAKE_CERT,
            "uhttpd.private_key_der": FAKE_KEY,
            "uhttpd.redirect_https": True,
            "sampling.enabled": True,
            "sampling.interval_seconds": 60,
            "telemetry.enabled": False,
            "remote_gui.enabled": False,
        }
    }
    data.update(replacements)
    return data


def target(**updates):
    state = {
        "profile": profile(), "active_bank": "B",
        "firmware_sha256": "a" * 64,
        "configuration_revision": 33,
    }
    state.update(updates)
    return state


def evidence(**updates):
    data = {name: True for name in REQUIRED_GUARDS}
    data.update({
        "tls_pair_and_rollback_verified": True,
        "remote_gui_default_deny_and_rollback_verified": True,
    })
    data.update(updates)
    return data


class ValidateConfig(unittest.TestCase):
    def test_bundle_exact_schema(self):
        self.assertEqual(validate_bundle(bundle())["source_bank"], "B")

    def test_unknown_config_field_refused(self):
        values = bundle()["values"]
        values["shell.raw"] = "ignored?"
        with self.assertRaisesRegex(SourceRecoveryError, "unknown_config_field"):
            validate_bundle(bundle(values=values))

    def test_missing_schema_field_and_extra_key_refused(self):
        b = bundle()
        del b["source_bank"]
        with self.assertRaisesRegex(SourceRecoveryError, "bundle_schema"):
            validate_bundle(b)
        b = bundle()
        b["network_configuration"] = "example"
        with self.assertRaisesRegex(SourceRecoveryError, "bundle_schema"):
            validate_bundle(b)

    def test_invalid_or_changed_hardware_profile_rejected(self):
        b = bundle()
        b["profile"]["abi"] = "a b \n"
        with self.assertRaisesRegex(SourceRecoveryError, "invalid_hardware"):
            validate_bundle(b)

    def test_invalid_hash_and_source_bank(self):
        for bad in ("", "A" * 64, "not-hex"):
            with self.subTest(bad=bad), self.assertRaisesRegex(
                SourceRecoveryError, "fingerprint"
            ):
                validate_bundle(bundle(source_firmware_sha256=bad))
        with self.assertRaisesRegex(SourceRecoveryError, "invalid_source_bank"):
            validate_bundle(bundle(source_bank="C"))

    def test_revision_boolean_and_out_of_bounds_rejected(self):
        for bad in (True, 0, 1000001):
            with self.subTest(value=bad), self.assertRaisesRegex(
                SourceRecoveryError, "invalid_configuration_revision"
            ):
                validate_bundle(bundle(configuration_revision=bad))

    def test_value_type_and_interval_bounds(self):
        vals = bundle()["values"]
        vals["sampling.interval_seconds"] = 75
        with self.assertRaisesRegex(SourceRecoveryError, "unsupported_sampling"):
            validate_bundle(bundle(values=vals))
        vals = bundle()["values"]
        vals["remote_gui.enabled"] = 1
        with self.assertRaisesRegex(SourceRecoveryError, "boolean"):
            validate_bundle(bundle(values=vals))

    def test_private_value_embedded_null_rejected(self):
        vals = bundle()["values"]
        vals["pon.serial"] = FAKE_ID + "\x00"
        with self.assertRaisesRegex(SourceRecoveryError, "private_config"):
            validate_bundle(bundle(values=vals))


class RedactedPublicPreview(unittest.TestCase):
    def test_default_public_export_redacts_every_sensitive_value(self):
        output = public_redacted_export(bundle())
        text = output.decode("ascii")
        for secret in (FAKE_ID, FAKE_HOST, FAKE_SECRET, FAKE_IP,
                       FAKE_CERT, FAKE_KEY, "a" * 64):
            with self.subTest(label=secret[:4]):
                self.assertNotIn(secret, text)
        data = json.loads(output)
        self.assertTrue(data["no_credentials_or_device_identity_included"])
        self.assertTrue(data["source_profile_redacted"])
        self.assertTrue(data["source_bank_redacted"])
        self.assertTrue(data["firmware_identity_redacted"])
        self.assertEqual(
            data["configuration_values"]["pon.registration_password"],
            "[redacted]")
        self.assertTrue(data["configuration_values"]["sampling.enabled"])
        self.assertEqual(data["configuration_values"]["sampling.interval_seconds"], 60)

    def test_public_export_deterministic_without_value_hashes(self):
        b = bundle()
        a = public_redacted_export(b)
        b["values"]["pon.serial"] = "different" + "-synthetic"
        b["values"]["management.ipv4"] = ".".join(("198", "51", "100", "10"))
        other = public_redacted_export(b)
        self.assertEqual(a, other)

    def test_public_preview_not_decryptable_private_archive(self):
        preview = public_redacted_export(bundle())
        with self.assertRaises(SourceRecoveryError):
            decrypt_private_archive(preview, PASSPHRASE)


class EncryptedPrivateBackup(unittest.TestCase):
    def test_encrypted_roundtrip_preserves_full_synthetic_config(self):
        original = bundle()
        archive = encrypted_private_export(original, PASSPHRASE)
        self.assertEqual(decrypt_private_archive(archive, PASSPHRASE), original)
        for value in (FAKE_SECRET, FAKE_ID, FAKE_HOST, FAKE_KEY):
            self.assertNotIn(value.encode(), archive)
        self.assertNotIn(b"prx126-research", archive)
        obj = json.loads(archive)
        self.assertEqual(set(obj), {"format", "kdf", "salt", "nonce", "ciphertext"})
        self.assertFalse(any(secret in str(obj) for secret in (
            FAKE_SECRET, FAKE_HOST, FAKE_ID)))

    def test_salted_archive_is_not_deterministic(self):
        a = encrypted_private_export(bundle(), PASSPHRASE)
        b = encrypted_private_export(bundle(), PASSPHRASE)
        self.assertNotEqual(a, b)
        self.assertEqual(decrypt_private_archive(a, PASSPHRASE),
                         decrypt_private_archive(b, PASSPHRASE))

    def test_wrong_passphrase_fails_authenticated(self):
        archive = encrypted_private_export(bundle(), PASSPHRASE)
        with self.assertRaisesRegex(SourceRecoveryError, "authentication_failed"):
            decrypt_private_archive(archive, b"wrong" + b"-synthetic-passphrase")

    def test_empty_or_short_passphrase_refused(self):
        for bad in (None, "string-not-bytes", b"", b"x" * 11, b"x" * 513):
            with self.subTest(length=len(bad) if bad is not None else -1):
                with self.assertRaisesRegex(SourceRecoveryError, "passphrase"):
                    encrypted_private_export(bundle(), bad)

    def test_ciphertext_tampering_fails(self):
        a = encrypted_private_export(bundle(), PASSPHRASE)
        obj = json.loads(a)
        payload = bytearray(base64.b64decode(obj["ciphertext"]))
        payload[-1] ^= 1
        obj["ciphertext"] = base64.b64encode(payload).decode()
        damaged = json.dumps(obj, sort_keys=True, separators=(",", ":")).encode()
        with self.assertRaisesRegex(SourceRecoveryError, "authentication_failed"):
            decrypt_private_archive(damaged, PASSPHRASE)

    def test_wrong_kdf_not_executed(self):
        a = json.loads(encrypted_private_export(bundle(), PASSPHRASE))
        a["kdf"] = "legacy-insecure"
        with self.assertRaisesRegex(SourceRecoveryError, "unsupported_archive"):
            decrypt_private_archive(
                json.dumps(a, sort_keys=True, separators=(",", ":")).encode(),
                PASSPHRASE)

    def test_corrupted_nonce_and_salt_refused(self):
        a = json.loads(encrypted_private_export(bundle(), PASSPHRASE))
        for name in ("nonce", "salt"):
            b = dict(a)
            b[name] = base64.b64encode(b"tiny").decode()
            with self.subTest(name=name), self.assertRaisesRegex(
                SourceRecoveryError, "invalid_encrypted_archive"
            ):
                decrypt_private_archive(
                    json.dumps(b, sort_keys=True, separators=(",", ":")).encode(),
                    PASSPHRASE)

    def test_duplicate_json_key_noncanonical_archive_refused(self):
        a = encrypted_private_export(bundle(), PASSPHRASE)
        with self.assertRaisesRegex(SourceRecoveryError, "noncanonical"):
            decrypt_private_archive(a.replace(b",", b", ", 1), PASSPHRASE)

    def test_additional_archive_field_refused(self):
        a = json.loads(encrypted_private_export(bundle(), PASSPHRASE))
        a["password_hint"] = FAKE_HOST
        with self.assertRaisesRegex(SourceRecoveryError, "unsupported_archive"):
            decrypt_private_archive(
                json.dumps(a, sort_keys=True, separators=(",", ":")).encode(),
                PASSPHRASE)

    def test_excessive_archive_refused_before_scrypt(self):
        with self.assertRaisesRegex(SourceRecoveryError, "invalid_encrypted_archive"):
            decrypt_private_archive(b"x" * 140000, PASSPHRASE)

    def test_in_memory_only_no_password_cli(self):
        source = (ROOT / "tools/s016_offline_backup_recovery.py").read_text()
        for forbidden in ("argparse", "subprocess.run(", "os.system(",
                          "os.chmod(", "open(", "ssh ", "uci commit",
                          "fw_setenv", "mtd write", "private_key.pem"):
            self.assertNotIn(forbidden, source)


class RestoreAdmission(unittest.TestCase):
    def test_authenticated_archive_to_restore_plan(self):
        encrypted = encrypted_private_export(bundle(), PASSPHRASE)
        receipt = preview_encrypted_restore(
            encrypted, PASSPHRASE, target(), 33, evidence(),
            operator_approved=True)
        self.assertEqual(
            receipt["status"], "SOURCE_RESTORE_PLAN_READY_NOT_DEPLOYED")
        self.assertNotIn(FAKE_SECRET, str(receipt))
        self.assertNotIn(FAKE_ID, str(receipt))
        self.assertTrue(receipt["no_restore_or_flash_write"])

    def test_unverified_archive_refused_before_restore_plan(self):
        encrypted = encrypted_private_export(bundle(), PASSPHRASE)
        with self.assertRaisesRegex(SourceRecoveryError, "authentication_failed"):
            preview_encrypted_restore(
                encrypted, b"wrong" + b"-synthetic-passphrase",
                target(), 33, evidence(), operator_approved=True)
        with self.assertRaises(SourceRecoveryError):
            preview_encrypted_restore(
                public_redacted_export(bundle()), PASSPHRASE,
                target(), 33, evidence(), operator_approved=True)

    def test_same_bank_source_plan_never_applies_changes(self):
        receipt = plan_restore(bundle(), target(), 33, evidence(),
                               operator_approved=True)
        self.assertEqual(receipt["status"], "SOURCE_RESTORE_PLAN_READY_NOT_DEPLOYED")
        self.assertFalse(receipt["migration_requested"])
        self.assertTrue(receipt["requires_dedicated_production_approval"])
        self.assertTrue(receipt["no_reboot_or_bank_commit"])
        self.assertTrue(receipt["no_restore_or_flash_write"])
        self.assertNotIn(FAKE_SECRET, str(receipt))

    def test_explicit_restore_approval_required(self):
        with self.assertRaisesRegex(SourceRecoveryError, "explicit_operator"):
            plan_restore(bundle(), target(), 33, evidence())

    def test_stale_revision_rejected(self):
        with self.assertRaisesRegex(SourceRecoveryError, "revision_changed"):
            plan_restore(bundle(), target(), 32, evidence(), operator_approved=True)

    def test_board_profile_mismatch_rejected(self):
        t = target()
        t["profile"]["partition_profile"] = "different-revision"
        with self.assertRaisesRegex(SourceRecoveryError, "different_board"):
            plan_restore(bundle(), t, 33, evidence(), operator_approved=True)

    def test_cross_bank_requires_separate_migration_approval(self):
        t = target(active_bank="A")
        with self.assertRaisesRegex(SourceRecoveryError, "migration_not_approved"):
            plan_restore(bundle(), t, 33, evidence(), operator_approved=True)
        receipt = plan_restore(bundle(), t, 33, evidence(),
                               operator_approved=True, migration_approved=True)
        self.assertTrue(receipt["migration_requested"])
        self.assertEqual(receipt["status"], "SOURCE_RESTORE_PLAN_READY_NOT_DEPLOYED")

    def test_new_firmware_hash_requires_migration_approval(self):
        t = target(firmware_sha256="b" * 64)
        with self.assertRaisesRegex(SourceRecoveryError, "migration_not_approved"):
            plan_restore(bundle(), t, 33, evidence(), operator_approved=True)

    def test_unverified_recovery_guard_blocks(self):
        for name in REQUIRED_GUARDS:
            checks = evidence()
            checks[name] = False
            with self.subTest(name=name):
                result = plan_restore(bundle(), target(), 33, checks,
                                      operator_approved=True)
                self.assertEqual(result["status"], "SOURCE_RESTORE_BLOCKED")
                self.assertIn(name, result["missing_guards"])

    def test_missing_tls_pair_rollback_guard_blocks(self):
        checks = evidence(tls_pair_and_rollback_verified=False)
        r = plan_restore(bundle(), target(), 33, checks, operator_approved=True)
        self.assertIn("tls_pair_and_rollback_verified", r["missing_guards"])

    def test_remote_management_restore_requires_separate_guard(self):
        b = bundle()
        b["values"]["remote_gui.enabled"] = True
        checks = evidence(remote_gui_default_deny_and_rollback_verified=False)
        r = plan_restore(b, target(), 33, checks, operator_approved=True)
        self.assertIn("remote_gui_default_deny_and_rollback_verified",
                      r["missing_guards"])

    def test_invalid_or_missing_guards_refuse(self):
        for evidence_input in (None, [], "yes"):
            with self.subTest(value=str(evidence_input)):
                r = plan_restore(bundle(), target(), 33, evidence_input,
                                 operator_approved=True)
                self.assertEqual(r["status"], "SOURCE_RESTORE_BLOCKED")

    def test_shadows_simulate_commit_without_mutating_current(self):
        original = copy.deepcopy(bundle()["values"])
        changes = {"sampling.interval_seconds": 120,
                   "remote_gui.enabled": False}
        result = simulate_shadow_restore(original, changes)
        self.assertEqual(result["status"], "SOURCE_SHADOW_COMMIT_SYNTHETIC_ONLY")
        self.assertEqual(result["result"]["sampling.interval_seconds"], 120)
        self.assertEqual(original["sampling.interval_seconds"], 60)

    def test_injected_failures_restore_identical_original(self):
        original = copy.deepcopy(bundle()["values"])
        original_copy = copy.deepcopy(original)
        changes = {
            "management.hostname": FAKE_HOST + "new",
            "sampling.enabled": False,
            "sampling.interval_seconds": 300,
        }
        for step in (0, 1, 2):
            with self.subTest(step=step):
                out = simulate_shadow_restore(original, changes, fail_after=step)
                self.assertTrue(out["rolled_back"])
                self.assertEqual(out["result"], original_copy)
        self.assertEqual(original, original_copy)

    def test_unqualified_config_change_refused(self):
        with self.assertRaisesRegex(SourceRecoveryError, "shadow_unknown_field"):
            simulate_shadow_restore({}, {"execute.shell": "blocked"})

    def test_static_not_deployed(self):
        manifest = (ROOT / "MANIFEST.json").read_text()
        controller = (ROOT / "overlay/usr/lib/lua/luci/controller/8311.lua").read_text()
        self.assertNotIn("s016_offline_backup_recovery", manifest)
        self.assertNotIn("s016_offline_backup_recovery", controller)
        self.assertEqual(len(json.loads((ROOT / "MANIFEST.json").read_text())[
            "overlay_files"]), 81)


if __name__ == "__main__":
    unittest.main()
