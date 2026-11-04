#!/usr/bin/env python3
"""C-013: offline-only durable configuration transaction crash harness.

Works only in disposable synthetic /var/tmp/aott-c013-recovery-test-*
directories. Not installed, no device, firmware, UCI, rootfs or PON I/O.
This tests Linux file/lock/fsync ordering on a development host, NOT
physical PRX126 NAND, UBIFS, power-loss, or subscriber service behavior.
"""
from contextlib import contextmanager
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import stat

DIR_PATTERN = re.compile(r"^/var/tmp/aott-c013-recovery-test-[A-Za-z0-9_-]{6,40}$")
SCHEMA = 1
CURRENT = "config.current"
BACKUP = "config.previous"
JOURNAL = "transaction.journal"
CANDIDATE = "config.candidate"
LOCK = "transaction.lock"
MAX_FILE = 16384
ALLOWED = {
    "sampling.enabled": bool,
    "sampling.interval_seconds": int,
    "telemetry.enabled": bool,
}
RECEIPT_GUARDS = (
    "known_good_bank_preserved",
    "independent_backup_verified",
    "alternate_management_recovery_verified",
)
CONFIRM_GUARDS = (
    "effective_state_readback_verified",
    "service_restart_verified",
    "local_recovery_path_verified",
    "independent_rollback_ready",
)
_OWNED = set()


class SourceRecoveryError(ValueError):
    """Non-secret, constant error codes for an offline fixture."""


def _canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=True,
                      separators=(",", ":"), allow_nan=False).encode("ascii")


def _sha(data):
    return hashlib.sha256(data).hexdigest()


def _valid_values(values):
    if not isinstance(values, dict) or not values or set(values) - set(ALLOWED):
        raise SourceRecoveryError("unapproved_fixture_field")
    answer = {}
    for name, value in values.items():
        expected = ALLOWED[name]
        if type(value) is not expected:
            raise SourceRecoveryError("incorrect_fixture_value_type")
        if name == "sampling.interval_seconds" and value not in (30, 60, 120, 300):
            raise SourceRecoveryError("invalid_sampling_interval")
        answer[name] = value
    return answer


def _valid_config(data):
    if not isinstance(data, dict) or set(data) != {"schema", "revision", "values"}:
        raise SourceRecoveryError("unexpected_fixture_schema")
    if type(data["schema"]) is not int or data["schema"] != SCHEMA:
        raise SourceRecoveryError("invalid_fixture_schema")
    if type(data["revision"]) is not int or not 1 <= data["revision"] <= 999999:
        raise SourceRecoveryError("invalid_fixture_revision")
    return {"schema": SCHEMA, "revision": data["revision"],
            "values": _valid_values(data["values"])}


def _valid_journal(data):
    keys = {"schema", "phase", "before_sha256", "after_sha256",
            "before_revision", "after_revision"}
    if not isinstance(data, dict) or set(data) != keys or \
            type(data["schema"]) is not int or data["schema"] != SCHEMA or \
            data["phase"] not in ("pending", "committed", "rolled_back"):
        raise SourceRecoveryError("invalid_fixture_journal")
    for key in ("before_sha256", "after_sha256"):
        v = data[key]
        if type(v) is not str or not re.fullmatch(r"[0-9a-f]{64}", v):
            raise SourceRecoveryError("invalid_fixture_journal_hash")
    before, after = data["before_revision"], data["after_revision"]
    if type(before) is not int or type(after) is not int or \
            not 1 <= before < after <= 999999 or after != before + 1:
        raise SourceRecoveryError("invalid_fixture_journal_revision")
    return data


def _check_dir(directory):
    if type(directory) is not str or not DIR_PATTERN.fullmatch(directory):
        raise SourceRecoveryError("unapproved_offline_fixture_directory")
    folder = Path(directory)
    try:
        info = folder.lstat()
    except OSError:
        raise SourceRecoveryError("offline_fixture_directory_unavailable") from None
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.geteuid() or \
            stat.S_IMODE(info.st_mode) != 0o700:
        raise SourceRecoveryError("unsafe_fixture_directory")
    return folder, (info.st_dev, info.st_ino)


def _directory_fsync(folder):
    fd = os.open(folder, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC |
                 os.O_NOFOLLOW)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _check_identity(folder, initial):
    st = folder.lstat()
    if (st.st_dev, st.st_ino) != initial or \
            st.st_uid != os.geteuid() or \
            not stat.S_ISDIR(st.st_mode) or \
            stat.S_IMODE(st.st_mode) != 0o700:
        raise SourceRecoveryError("fixture_directory_changed")


def _file_bytes(folder, name, initial, *, optional=False):
    if name not in (CURRENT, BACKUP, JOURNAL, CANDIDATE, LOCK) and not name.endswith(".new"):
        raise SourceRecoveryError("unapproved_fixture_filename")
    path = folder / name
    try:
        before = path.lstat()
    except FileNotFoundError:
        if optional:
            return None
        raise SourceRecoveryError("required_fixture_file_missing") from None
    if not stat.S_ISREG(before.st_mode) or before.st_uid != os.geteuid() or \
            before.st_nlink != 1 or stat.S_IMODE(before.st_mode) != 0o600 or \
            before.st_size > MAX_FILE or before.st_size < 0:
        raise SourceRecoveryError("unsafe_fixture_file_inode")
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC |
                 os.O_NONBLOCK)
    try:
        opened = os.fstat(fd)
        if (opened.st_dev, opened.st_ino) != (before.st_dev, before.st_ino) or \
                opened.st_size != before.st_size or opened.st_uid != before.st_uid or \
                opened.st_nlink != 1 or stat.S_IMODE(opened.st_mode) != 0o600:
            raise SourceRecoveryError("fixture_inode_changed_during_read")
        data = os.read(fd, MAX_FILE + 1)
        after = path.lstat()
        if (after.st_dev, after.st_ino) != (before.st_dev, before.st_ino) or \
                after.st_size != before.st_size or \
                stat.S_IMODE(after.st_mode) != 0o600 or \
                after.st_nlink != 1 or len(data) != before.st_size:
            raise SourceRecoveryError("fixture_read_changed")
        _check_identity(folder, initial)
        return data
    finally:
        os.close(fd)


def _safe_remove(folder, name, initial):
    _check_identity(folder, initial)
    content = _file_bytes(folder, name, initial, optional=True)
    if content is not None:
        os.unlink(folder / name)
        _directory_fsync(folder)


def _atomic_write(folder, name, data, initial):
    if name not in (CURRENT, BACKUP, JOURNAL, CANDIDATE):
        raise SourceRecoveryError("unapproved_atomic_target")
    if type(data) is not bytes or not 1 <= len(data) <= MAX_FILE:
        raise SourceRecoveryError("invalid_durable_data")
    _check_identity(folder, initial)
    # Refuse an existing unsafe destination; no symlink following.
    _file_bytes(folder, name, initial, optional=True)
    stage = folder / (name + ".new")
    fd = os.open(stage, os.O_WRONLY | os.O_CREAT | os.O_EXCL |
                 os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "wb", closefd=False) as output:
            output.write(data)
            output.flush()
        os.fsync(fd)
    finally:
        os.close(fd)
    _check_identity(folder, initial)
    _file_bytes(folder, name + ".new", initial)
    os.replace(stage, folder / name)
    _directory_fsync(folder)
    if _file_bytes(folder, name, initial) != data:
        raise SourceRecoveryError("atomic_write_readback_mismatch")


def _record(folder, initial):
    raw = _file_bytes(folder, JOURNAL, initial, optional=True)
    if raw is None:
        return None
    try:
        value = json.loads(raw)
    except (UnicodeError, ValueError):
        raise SourceRecoveryError("malformed_recovery_journal") from None
    if _canonical(value) != raw:
        raise SourceRecoveryError("noncanonical_recovery_journal")
    return _valid_journal(value)


def _config(folder, initial):
    raw = _file_bytes(folder, CURRENT, initial)
    try:
        value = json.loads(raw)
    except (UnicodeError, ValueError):
        raise SourceRecoveryError("malformed_current_configuration") from None
    if _canonical(value) != raw:
        raise SourceRecoveryError("noncanonical_current_configuration")
    return _valid_config(value), raw


@contextmanager
def _exclusive(directory):
    folder, initial = _check_dir(directory)
    path = folder / LOCK
    # Stable file inode must never be unlinked, including after SIGKILL.
    # POSIX record locks are process-scoped: opening/closing another
    # descriptor for the same inode can release the process's lock.
    # Refuse recursive entry before even opening a second descriptor.
    if str(path) in _OWNED:
        raise SourceRecoveryError("same_process_fixture_lock_held")
    fd = -1
    newly_created = False
    owned_acquired = False
    try:
        try:
            fd = os.open(path, os.O_RDWR | os.O_CREAT | os.O_EXCL |
                         os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
            newly_created = True
        except FileExistsError:
            fd = os.open(path, os.O_RDWR | os.O_NOFOLLOW | os.O_CLOEXEC)
        before = os.fstat(fd)
        if not stat.S_ISREG(before.st_mode) or before.st_uid != os.geteuid() or \
                before.st_nlink != 1 or stat.S_IMODE(before.st_mode) != 0o600 or \
                before.st_size != 0:
            raise SourceRecoveryError("unsafe_fixture_lock_inode")
        if (folder / LOCK).lstat().st_ino != before.st_ino:
            raise SourceRecoveryError("fixture_lock_replaced")
        try:
            fcntl.lockf(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise SourceRecoveryError("other_fixture_process_holds_lock") from None
        _OWNED.add(str(path))
        owned_acquired = True
        if newly_created:
            _directory_fsync(folder)
        _check_identity(folder, initial)
        yield folder, initial
    finally:
        if owned_acquired:
            _OWNED.discard(str(path))
        if fd >= 0:
            os.close(fd)


def _checkpoint(hook, name):
    if hook is not None:
        hook(name)


def initialize_offline_fixture(directory, values=None, revision=1):
    with _exclusive(directory) as (folder, initial):
        if any((folder / name).exists() for name in
               (CURRENT, BACKUP, JOURNAL, CANDIDATE)):
            raise SourceRecoveryError("fixture_already_initialized")
        raw = _canonical(_valid_config({
            "schema": 1, "revision": revision,
            "values": values or {"sampling.enabled": True,
                                 "sampling.interval_seconds": 60},
        }))
        _atomic_write(folder, CURRENT, raw, initial)
    return {"status": "SOURCE_FIXTURE_INITIALIZED",
            "source_only_not_deployed": True}


def _guards(receipts, required):
    if type(receipts) is not dict or any(
        receipts.get(key) is not True for key in required
    ):
        raise SourceRecoveryError("independent_synthetic_recovery_guards_missing")


def begin_trial(directory, changes, expected_revision, *,
                operator_approved=False, guard_receipts=None, checkpoint=None):
    """Start a synthetic transaction; never auto-confirm or delete rollback."""
    if operator_approved is not True:
        raise SourceRecoveryError("synthetic_operator_approval_required")
    _guards(guard_receipts, RECEIPT_GUARDS)
    with _exclusive(directory) as (folder, initial):
        current, before = _config(folder, initial)
        if type(expected_revision) is not int or current["revision"] != expected_revision:
            raise SourceRecoveryError("stale_fixture_revision")
        if _record(folder, initial) is not None or any(
            (folder / name).exists() for name in (BACKUP, CANDIDATE)
        ):
            raise SourceRecoveryError("prior_trial_or_recovery_pending")
        for name in (CURRENT, BACKUP, JOURNAL, CANDIDATE):
            if (folder / (name + ".new")).exists():
                raise SourceRecoveryError("unrecovered_partial_stage")
        if not isinstance(changes, dict) or not changes or set(changes) - set(ALLOWED):
            raise SourceRecoveryError("unapproved_fixture_change")
        new_values = dict(current["values"])
        new_values.update(changes)
        proposed = _valid_config({
            "schema": SCHEMA,
            "revision": current["revision"] + 1,
            "values": new_values,
        })
        if proposed["values"] == current["values"]:
            raise SourceRecoveryError("no_configuration_change")
        after = _canonical(proposed)
        log = {
            "schema": SCHEMA, "phase": "pending",
            "before_sha256": _sha(before), "after_sha256": _sha(after),
            "before_revision": current["revision"],
            "after_revision": proposed["revision"],
        }
        _atomic_write(folder, BACKUP, before, initial)
        _checkpoint(checkpoint, "after_backup")
        _atomic_write(folder, JOURNAL, _canonical(log), initial)
        _checkpoint(checkpoint, "after_journal")
        _atomic_write(folder, CANDIDATE, after, initial)
        _checkpoint(checkpoint, "after_candidate")
        _atomic_write(folder, CURRENT, after, initial)
        _checkpoint(checkpoint, "after_installed")
        if _config(folder, initial)[1] != after:
            raise SourceRecoveryError("candidate_readback_failed")
        _checkpoint(checkpoint, "after_readback")
        return {"status": "SOURCE_TRIAL_PENDING",
                "revision": proposed["revision"],
                "rollback_necessary_without_confirmation": True,
                "source_only_not_deployed": True,
                "no_uci_or_firmware_or_network_write": True}


def _set_phase(folder, initial, log, phase):
    record = dict(log, phase=phase)
    _atomic_write(folder, JOURNAL, _canonical(record), initial)
    return record


def _cleanup(folder, initial, checkpoint=None):
    for name in (CANDIDATE, BACKUP):
        _safe_remove(folder, name, initial)
        _checkpoint(checkpoint, "after_remove_" + name)
    _safe_remove(folder, JOURNAL, initial)
    _checkpoint(checkpoint, "after_remove_journal")


def _cleanup_temps(folder, initial):
    for name in (CURRENT, BACKUP, JOURNAL, CANDIDATE):
        _safe_remove(folder, name + ".new", initial)


def recover_offline_fixture(directory, *, checkpoint=None):
    """Independent process recovery; unconfirmed trial always rolls back."""
    with _exclusive(directory) as (folder, initial):
        _cleanup_temps(folder, initial)
        journal = _record(folder, initial)
        current, raw = _config(folder, initial)
        if journal is None:
            backup = _file_bytes(folder, BACKUP, initial, optional=True)
            candidate = _file_bytes(folder, CANDIDATE, initial, optional=True)
            if backup is not None and backup != raw:
                raise SourceRecoveryError("untracked_backup_mismatch")
            _cleanup(folder, initial)
            return {"status": "SOURCE_NO_PENDING_TRIAL",
                    "source_only_not_deployed": True}
        if journal["phase"] == "pending":
            backup = _file_bytes(folder, BACKUP, initial)
            if _sha(backup) != journal["before_sha256"]:
                raise SourceRecoveryError("unverified_recovery_backup")
            if _sha(raw) not in (
                journal["before_sha256"], journal["after_sha256"]
            ):
                raise SourceRecoveryError("unknown_interrupted_configuration")
            if _sha(raw) != journal["before_sha256"]:
                _atomic_write(folder, CURRENT, backup, initial)
            _checkpoint(checkpoint, "after_restore")
            if _sha(_config(folder, initial)[1]) != journal["before_sha256"]:
                raise SourceRecoveryError("rollback_readback_failed")
            journal = _set_phase(folder, initial, journal, "rolled_back")
            _checkpoint(checkpoint, "after_rollback_marker")
            result = "SOURCE_ROLLBACK_VERIFIED_SYNTHETIC"
        elif journal["phase"] == "rolled_back":
            if _sha(raw) != journal["before_sha256"]:
                raise SourceRecoveryError("rolled_back_config_changed")
            result = "SOURCE_ROLLBACK_RECOVERY_COMPLETED"
        else:
            if _sha(raw) != journal["after_sha256"]:
                raise SourceRecoveryError("committed_fixture_config_changed")
            result = "SOURCE_COMMITTED_CLEANUP_COMPLETED"
        _cleanup(folder, initial, checkpoint)
        return {"status": result, "source_only_not_deployed": True,
                "no_uci_or_firmware_or_network_write": True}


def confirm_trial(directory, expected_revision, *, operator_confirmed=False,
                  receipt_guards=None, checkpoint=None):
    if operator_confirmed is not True:
        raise SourceRecoveryError("final_operator_confirmation_required")
    _guards(receipt_guards, CONFIRM_GUARDS)
    with _exclusive(directory) as (folder, initial):
        journal = _record(folder, initial)
        if journal is None or journal["phase"] != "pending":
            raise SourceRecoveryError("no_pending_trial_to_confirm")
        current, raw = _config(folder, initial)
        if type(expected_revision) is not int or \
           expected_revision != journal["after_revision"] or \
           current["revision"] != journal["after_revision"] or \
           _sha(raw) != journal["after_sha256"]:
            raise SourceRecoveryError("new_configuration_readback_unverified")
        backup = _file_bytes(folder, BACKUP, initial)
        if _sha(backup) != journal["before_sha256"]:
            raise SourceRecoveryError("backup_readback_unverified")
        journal = _set_phase(folder, initial, journal, "committed")
        _checkpoint(checkpoint, "after_commit_marker")
        _cleanup(folder, initial, checkpoint)
        return {"status": "SOURCE_TRIAL_COMMITTED_SYNTHETIC",
                "source_only_not_deployed": True,
                "no_uci_or_firmware_or_network_write": True}


def read_fixture_status(directory):
    with _exclusive(directory) as (folder, initial):
        config, raw = _config(folder, initial)
        journal = _record(folder, initial)
        return {"status": "SOURCE_SYNTHETIC_READBACK",
                "revision": config["revision"],
                "field_count": len(config["values"]),
                "has_pending_journal": journal is not None,
                "journal_phase": journal["phase"] if journal else "absent",
                "source_only_not_deployed": True}
