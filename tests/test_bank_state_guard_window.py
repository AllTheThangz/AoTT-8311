"""Pure, synthetic reference tests for the v2r6 reboot-aware state guard.

No real ONU access or bank-control command is used. These tests model the
exact byte sequence specified in the reviewed shell source.
"""
import hashlib
import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
SHELL = ROOT / "overlay/lib/8311-upgrade-lib.sh"
PREFIX = b"aott-8311-bank-state-guard-v2\n"
WINDOW = 300
BOOT_A = "11111111-2222-4333-8444-555555555555"
BOOT_B = "aaaaaaa1-bbbb-4ccc-8ddd-eeeeeeeeeeee"


def raw_snapshot(*, committed="B", pending=None, rootfs="a" * 64):
    state = {
        "schema": 1, "active": "B", "committed": committed,
        "pending": pending, "running_trial": committed != "B",
        "boot_contract": True, "banks": {
            "A": {"valid": True, "receipt": "complete",
                  "components": {"rootfs": {"bytes": 100, "sha256": rootfs}}},
            "B": {"valid": True, "receipt": "complete",
                  "components": {"rootfs": {"bytes": 100, "sha256": "b" * 64}}}
        }
    }
    return (json.dumps(state, separators=(",", ":")) + "\n").encode()


def reference_fingerprint(snapshot, boot_id, epoch):
    if not snapshot.endswith(b"\n") or type(epoch) is not int or epoch < 0:
        raise ValueError("Malformed synthetic input")
    metadata = ("boot-id=" + boot_id + "\nfive-minute-window=" +
                str(epoch // WINDOW) + "\n").encode("ascii")
    return hashlib.sha256(PREFIX + snapshot + metadata).hexdigest()


class BankStateGuardWindowReferenceTests(unittest.TestCase):
    def test_within_one_time_window_and_boot_identity_stays_stable(self):
        state = raw_snapshot()
        self.assertEqual(reference_fingerprint(state, BOOT_A, 1500),
                         reference_fingerprint(state, BOOT_A, 1799))

    def test_exact_five_minute_boundary_invalidates_old_queue_request(self):
        state = raw_snapshot()
        self.assertNotEqual(reference_fingerprint(state, BOOT_A, 1799),
                            reference_fingerprint(state, BOOT_A, 1800))

    def test_reboot_into_same_bank_invalidates_earlier_confirmation(self):
        state = raw_snapshot()
        self.assertNotEqual(reference_fingerprint(state, BOOT_A, 1502),
                            reference_fingerprint(state, BOOT_B, 1502))

    def test_changed_bank_receipt_invalidates_earlier_confirmation(self):
        before = raw_snapshot()
        after = raw_snapshot(rootfs="c" * 64)
        self.assertNotEqual(reference_fingerprint(before, BOOT_A, 1500),
                            reference_fingerprint(after, BOOT_A, 1500))

    def test_changed_committed_selection_invalidates_earlier_confirmation(self):
        self.assertNotEqual(reference_fingerprint(raw_snapshot(committed="B"), BOOT_A, 1500),
                            reference_fingerprint(raw_snapshot(committed="A"), BOOT_A, 1500))

    def test_guard_domain_separation_is_explicit(self):
        state = raw_snapshot()
        legacy = hashlib.sha256(state).hexdigest()
        new = reference_fingerprint(state, BOOT_A, 1500)
        self.assertNotEqual(legacy, new)
        self.assertEqual(len(new), 64)
        self.assertEqual(set(new).issubset(set("0123456789abcdef")), True)

    def test_shell_uses_same_field_order_and_window_policy(self):
        text = SHELL.read_text()
        start = text.index("bank_state_fingerprint() {")
        stop = text.index("\n}\n", start) + 2
        code = text[start:stop]
        for phrase in ("print_bank_status > \"$WORKDIR/state-snapshot\"",
                       "cat /proc/sys/kernel/random/boot_id",
                       "epoch=$(date +%s)",
                       "bucket=$((epoch / 300))",
                       "aott-8311-bank-state-guard-v2",
                       'cat "$WORKDIR/state-snapshot"',
                       "boot-id=%s\\nfive-minute-window=%s\\n",
                       'sha_file "$WORKDIR/state-precondition"'):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, code)

    def test_fingerprint_does_not_add_secrets_or_personal_provisioning(self):
        text = SHELL.read_text()
        start = text.index("bank_state_fingerprint() {")
        stop = text.index("\n}\n", start) + 2
        code = text[start:stop]
        self.assertNotIn("root_pwhash", code)
        self.assertNotIn("pon_serial", code)
        self.assertNotIn("fw_printenv", code)
        self.assertNotIn("/ptconf", code)

    def test_malformed_synthetic_reference_input_is_rejected(self):
        for snapshot, epoch in ((b"{}", 1500), (raw_snapshot(), -1),
                                (raw_snapshot(), 1.1)):
            with self.subTest(epoch=epoch):
                with self.assertRaises(ValueError):
                    reference_fingerprint(snapshot, BOOT_A, epoch)


if __name__ == "__main__":
    unittest.main()
