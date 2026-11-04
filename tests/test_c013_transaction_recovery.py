"""C-013: actual isolated Linux file journal with separate-process failure injection.

These are synthetic local configuration values only. No PON/ISP
identity, ONU network interface or firmware bank is involved.
"""
import copy
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from c013_offline_transaction_journal import (
    SourceRecoveryError, initialize_offline_fixture, begin_trial,
    confirm_trial, recover_offline_fixture, read_fixture_status,
    RECEIPT_GUARDS, CONFIRM_GUARDS, _exclusive,
    _config, _check_dir, CURRENT, JOURNAL, BACKUP, CANDIDATE,
)

WORKER = ROOT / "tests/c013_transaction_worker.py"


def guards(keys):
    return {k: True for k in keys}


class SyntheticRecoveryFixture(unittest.TestCase):
    def setUp(self):
        self.path = Path(tempfile.mkdtemp(
            prefix="aott-c013-recovery-test-", dir="/var/tmp"))
        self.path.chmod(0o700)
        initialize_offline_fixture(str(self.path))
        self.initial = (self.path / CURRENT).read_bytes()

    def tearDown(self):
        shutil.rmtree(self.path, ignore_errors=True)

    def run_worker(self, operation, checkpoint="no_crash"):
        return subprocess.run(
            [sys.executable, str(WORKER),
             operation, str(self.path), checkpoint],
            capture_output=True, timeout=20)

    def begin(self):
        return begin_trial(
            str(self.path), {"sampling.interval_seconds": 120},
            1, operator_approved=True,
            guard_receipts=guards(RECEIPT_GUARDS))

    def confirm(self):
        return confirm_trial(
            str(self.path), 2, operator_confirmed=True,
            receipt_guards=guards(CONFIRM_GUARDS))

    def check_clean(self, expected_revision):
        receipt = read_fixture_status(str(self.path))
        self.assertEqual(receipt["revision"], expected_revision)
        self.assertFalse(receipt["has_pending_journal"])
        self.assertEqual(receipt["journal_phase"], "absent")
        self.assertFalse((self.path / BACKUP).exists())
        self.assertFalse((self.path / CANDIDATE).exists())
        self.assertFalse((self.path / JOURNAL).exists())
        for file in (CURRENT, BACKUP, CANDIDATE, JOURNAL):
            self.assertFalse((self.path / (file + ".new")).exists())
        return receipt


class BasicTransactionTests(SyntheticRecoveryFixture):
    def test_initial_snapshot_safe_private_and_no_auto_start(self):
        r = self.check_clean(1)
        self.assertTrue(r["source_only_not_deployed"])
        self.assertEqual((self.path / CURRENT).stat().st_mode & 0o777, 0o600)
        self.assertEqual(self.path.stat().st_mode & 0o777, 0o700)

    def test_begin_is_pending_until_explicit_final_confirmation(self):
        r = self.begin()
        self.assertEqual(r["status"], "SOURCE_TRIAL_PENDING")
        self.assertTrue(r["rollback_necessary_without_confirmation"])
        self.assertTrue(r["source_only_not_deployed"])
        receipt = read_fixture_status(str(self.path))
        self.assertEqual(receipt["revision"], 2)
        self.assertEqual(receipt["journal_phase"], "pending")
        self.assertTrue((self.path / BACKUP).exists())
        self.assertNotEqual((self.path / CURRENT).read_bytes(), self.initial)

    def test_unconfirmed_trial_recovered_by_independent_process(self):
        self.begin()
        result = self.run_worker("recover")
        self.assertEqual(result.returncode, 0, result.stderr.decode())
        self.check_clean(1)
        self.assertEqual((self.path / CURRENT).read_bytes(), self.initial)

    def test_explicit_confirm_keeps_new_configuration(self):
        self.begin()
        r = self.confirm()
        self.assertEqual(r["status"], "SOURCE_TRIAL_COMMITTED_SYNTHETIC")
        self.assertTrue(r["no_uci_or_firmware_or_network_write"])
        self.check_clean(2)
        self.assertNotEqual((self.path / CURRENT).read_bytes(), self.initial)
        result = self.run_worker("recover")
        self.assertEqual(result.returncode, 0, result.stderr.decode())
        self.check_clean(2)

    def test_guards_are_required_for_begin_and_confirmation(self):
        with self.assertRaisesRegex(SourceRecoveryError, "approval_required"):
            begin_trial(str(self.path), {"sampling.interval_seconds": 120},
                        1, guard_receipts=guards(RECEIPT_GUARDS))
        with self.assertRaisesRegex(SourceRecoveryError, "recovery_guards_missing"):
            begin_trial(str(self.path), {"sampling.interval_seconds": 120},
                        1, operator_approved=True, guard_receipts={})
        self.check_clean(1)
        self.begin()
        with self.assertRaisesRegex(SourceRecoveryError, "confirmation_required"):
            confirm_trial(str(self.path), 2,
                          receipt_guards=guards(CONFIRM_GUARDS))
        for name in CONFIRM_GUARDS:
            check = guards(CONFIRM_GUARDS)
            check[name] = False
            with self.subTest(guard=name), self.assertRaisesRegex(
                SourceRecoveryError, "recovery_guards_missing"):
                confirm_trial(str(self.path), 2,
                              operator_confirmed=True,
                              receipt_guards=check)
        self.assertEqual(read_fixture_status(str(self.path))["journal_phase"],
                         "pending")
        recover_offline_fixture(str(self.path))
        self.check_clean(1)

    def test_stale_revision_refused_without_writes(self):
        with self.assertRaisesRegex(SourceRecoveryError, "stale_fixture_revision"):
            begin_trial(
                str(self.path), {"sampling.interval_seconds": 120},
                2, operator_approved=True,
                guard_receipts=guards(RECEIPT_GUARDS))
        self.check_clean(1)
        self.assertEqual((self.path / CURRENT).read_bytes(), self.initial)

    def test_second_trial_not_allowed_during_pending(self):
        self.begin()
        with self.assertRaisesRegex(SourceRecoveryError, "prior_trial"):
            begin_trial(
                str(self.path), {"sampling.interval_seconds": 300},
                2, operator_approved=True,
                guard_receipts=guards(RECEIPT_GUARDS))
        self.assertEqual(read_fixture_status(str(self.path))["journal_phase"],
                         "pending")

    def test_unknown_fields_and_changes_forbidden(self):
        for changes in (
            {"pon.serial": "no-subscriber-material"},
            {"management.ipv4": "synthetic"},
            {"remote_gui.enabled": True},
            {"sampling.interval_seconds": 45},
            {"sampling.interval_seconds": True},
        ):
            with self.subTest(changes=changes), self.assertRaises(
                SourceRecoveryError):
                begin_trial(
                    str(self.path), changes, 1,
                    operator_approved=True,
                    guard_receipts=guards(RECEIPT_GUARDS))
        self.check_clean(1)

    def test_noop_not_a_transaction(self):
        with self.assertRaisesRegex(SourceRecoveryError, "no_configuration_change"):
            begin_trial(
                str(self.path), {"sampling.interval_seconds": 60}, 1,
                operator_approved=True,
                guard_receipts=guards(RECEIPT_GUARDS))
        self.check_clean(1)

    def test_wrong_expected_final_revision_refused(self):
        self.begin()
        with self.assertRaisesRegex(SourceRecoveryError, "new_configuration"):
            confirm_trial(str(self.path), 3, operator_confirmed=True,
                          receipt_guards=guards(CONFIRM_GUARDS))
        self.assertEqual(read_fixture_status(str(self.path))["journal_phase"],
                         "pending")

    def test_nested_lock_refusal_keeps_original_owner(self):
        with _exclusive(str(self.path)):
            with self.assertRaisesRegex(SourceRecoveryError, "same_process"):
                with _exclusive(str(self.path)):
                    pass
            # The outer lock is still authoritative, not accidentally
            # released by a second fd being closed within this process.
            result = self.run_worker("begin")
            self.assertNotEqual(result.returncode, 0)
            self.assertIn(b"other_fixture_process_holds_lock", result.stderr)
        self.begin()
        recover_offline_fixture(str(self.path))
        self.check_clean(1)

    def test_lock_file_inode_retained_across_transactions(self):
        lock = self.path / "transaction.lock"
        original_inode = lock.stat().st_ino
        self.begin()
        recover_offline_fixture(str(self.path))
        self.begin()
        self.confirm()
        self.assertEqual(lock.stat().st_ino, original_inode)
        self.assertEqual(lock.stat().st_nlink, 1)
        self.assertEqual(lock.stat().st_mode & 0o777, 0o600)


class IndependentCrashProcessTests(SyntheticRecoveryFixture):
    def test_all_unconfirmed_writer_crash_points_recover_original(self):
        for stage in ("after_backup", "after_journal",
                      "after_candidate", "after_installed", "after_readback"):
            with self.subTest(crash_at=stage):
                worker = self.run_worker("begin", stage)
                self.assertEqual(worker.returncode, 73,
                                 worker.stderr.decode()[-300:])
                # Kernel lock released by OS after process death. A
                # separate process can independently inspect and revert.
                result = self.run_worker("recover")
                self.assertEqual(result.returncode, 0,
                                 result.stderr.decode()[-300:])
                self.check_clean(1)
                self.assertEqual((self.path / CURRENT).read_bytes(), self.initial)

    def test_crash_after_committed_marker_preserves_new_revision(self):
        self.begin()
        death = self.run_worker("commit", "after_commit_marker")
        self.assertEqual(death.returncode, 73,
                         death.stderr.decode()[-300:])
        self.assertEqual(read_fixture_status(str(self.path))["journal_phase"],
                         "committed")
        self.assertEqual(self.run_worker("recover").returncode, 0)
        self.check_clean(2)
        self.assertNotEqual((self.path / CURRENT).read_bytes(), self.initial)

    def test_crash_during_committed_cleanup_is_idempotent(self):
        for stage in ("after_remove_config.candidate",
                      "after_remove_config.previous",
                      "after_remove_journal"):
            with self.subTest(crash_at=stage):
                self.begin()
                death = self.run_worker("commit", stage)
                self.assertEqual(death.returncode, 73,
                                 death.stderr.decode()[-300:])
                self.assertEqual(self.run_worker("recover").returncode, 0)
                self.check_clean(2)
                # Restore initial state by creating a NEW disposable fixture
                # for the next case, never touching live configuration.
                shutil.rmtree(self.path)
                self.path.mkdir(mode=0o700)
                initialize_offline_fixture(str(self.path))
                self.assertEqual((self.path / CURRENT).read_bytes(), self.initial)

    def test_crash_during_rollback_is_idempotent(self):
        for stage in ("after_restore", "after_rollback_marker",
                      "after_remove_config.candidate",
                      "after_remove_config.previous",
                      "after_remove_journal"):
            with self.subTest(crash_at=stage):
                self.begin()
                death = self.run_worker("recover", stage)
                self.assertEqual(death.returncode, 73,
                                 death.stderr.decode()[-300:])
                self.assertEqual(self.run_worker("recover").returncode, 0)
                self.check_clean(1)
                self.assertEqual((self.path / CURRENT).read_bytes(), self.initial)

    def test_lock_contention_is_real_cross_process(self):
        p = subprocess.Popen(
            [sys.executable, str(WORKER),
             "hold", str(self.path), "no_crash"],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, text=True)
        try:
            self.assertEqual(p.stdout.readline().strip(), "SOURCE_ONLY_LOCK_HELD")
            with self.assertRaisesRegex(
                SourceRecoveryError, "other_fixture_process_holds_lock"):
                self.begin()
            self.assertEqual((self.path / CURRENT).read_bytes(), self.initial)
        finally:
            p.stdin.write("\n")
            p.stdin.flush()
            p.communicate(timeout=8)
        self.begin()
        recover_offline_fixture(str(self.path))
        self.check_clean(1)

    def test_sigkill_releases_kernel_lock_without_claimed_commit(self):
        p = subprocess.Popen(
            [sys.executable, str(WORKER),
             "hold", str(self.path), "no_crash"],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, text=True)
        self.assertEqual(p.stdout.readline().strip(), "SOURCE_ONLY_LOCK_HELD")
        p.kill()
        p.communicate(timeout=8)
        self.begin()
        self.assertEqual(read_fixture_status(str(self.path))["journal_phase"],
                         "pending")
        self.assertEqual(self.run_worker("recover").returncode, 0)
        self.check_clean(1)


class UnsafeFilesystemTests(SyntheticRecoveryFixture):
    def test_symlink_replacing_backup_is_refused(self):
        self.begin()
        original = self.path / BACKUP
        original.rename(self.path / "inert-backup")
        original.symlink_to(self.path / "inert-backup")
        with self.assertRaisesRegex(SourceRecoveryError, "unsafe_fixture_file_inode"):
            recover_offline_fixture(str(self.path))
        self.assertTrue((self.path / "inert-backup").is_file())

    def test_hardlink_backup_refused(self):
        self.begin()
        os.link(self.path / BACKUP, self.path / "inert-copy")
        with self.assertRaisesRegex(SourceRecoveryError, "unsafe_fixture_file_inode"):
            recover_offline_fixture(str(self.path))

    def test_corrupted_backup_prevents_unsafe_rollback(self):
        self.begin()
        backup = self.path / BACKUP
        backup.write_bytes(b"wrong-synthetic-backup")
        with self.assertRaisesRegex(SourceRecoveryError, "unverified_recovery_backup"):
            recover_offline_fixture(str(self.path))
        self.assertEqual(read_fixture_status(str(self.path))["journal_phase"],
                         "pending")

    def test_unknown_current_bytes_prevent_overwrite(self):
        self.begin()
        current = self.path / CURRENT
        current.write_bytes(
            b'{"revision":2,"schema":1,"values":{"sampling.enabled":false}}')
        # Valid shape but unknown digest, so do not replace current silently.
        with self.assertRaisesRegex(SourceRecoveryError, "unknown_interrupted"):
            recover_offline_fixture(str(self.path))

    def test_modified_directory_mode_blocks_all_reads(self):
        self.path.chmod(0o755)
        try:
            with self.assertRaisesRegex(SourceRecoveryError, "unsafe_fixture_directory"):
                read_fixture_status(str(self.path))
        finally:
            self.path.chmod(0o700)

    def test_symlinked_or_unapproved_directory_refused(self):
        link = Path(str(self.path) + "-link")
        self.assertFalse(link.exists())
        link.symlink_to(self.path)
        try:
            with self.assertRaisesRegex(SourceRecoveryError, "unsafe_fixture_directory"):
                read_fixture_status(str(link))
        finally:
            link.unlink()
        with self.assertRaisesRegex(SourceRecoveryError, "unapproved_offline_fixture"):
            read_fixture_status("/etc")

    def test_orphan_partial_temp_file_is_not_trusted(self):
        (self.path / (CURRENT + ".new")).write_bytes(b"junk synthetic temp")
        (self.path / (CURRENT + ".new")).chmod(0o600)
        with self.assertRaisesRegex(SourceRecoveryError, "unrecovered_partial"):
            self.begin()
        recover_offline_fixture(str(self.path))
        self.check_clean(1)

    def test_no_real_firmware_overlay_or_live_access(self):
        src = (ROOT / "tools/c013_offline_transaction_journal.py").read_text()
        manifest = (ROOT / "MANIFEST.json").read_text()
        ctl = (ROOT / "overlay/usr/lib/lua/luci/controller/8311.lua").read_text()
        self.assertNotIn("c013_offline_transaction_journal", manifest)
        self.assertNotIn("c013_offline_transaction_journal", ctl)
        for token in ("subprocess.run(", "socket.connect(",
                      "fw_setenv", "uci commit", "mtd write",
                      "pon psg", "/dev/mtd"):
            self.assertNotIn(token, src)


if __name__ == "__main__":
    unittest.main()
