#!/usr/bin/env python3
"""Synthetic-only separate-process C-013 crash/recovery worker.

Test code deliberately terminates itself with os._exit after selected
durable checkpoints. No device path is writable or read by this fixture.
"""
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from c013_offline_transaction_journal import (
    _exclusive, begin_trial, confirm_trial, recover_offline_fixture,
    RECEIPT_GUARDS, CONFIRM_GUARDS,
)


def checklist(keys):
    return {name: True for name in keys}


def main():
    if len(sys.argv) != 4:
        return 2
    operation, directory, crash = sys.argv[1:]

    def checkpoint(label):
        if label == crash:
            os._exit(73)

    if operation == "begin":
        begin_trial(
            directory, {"sampling.interval_seconds": 120},
            1, operator_approved=True,
            guard_receipts=checklist(RECEIPT_GUARDS),
            checkpoint=checkpoint)
    elif operation == "commit":
        confirm_trial(
            directory, 2, operator_confirmed=True,
            receipt_guards=checklist(CONFIRM_GUARDS),
            checkpoint=checkpoint)
    elif operation == "recover":
        recover_offline_fixture(directory, checkpoint=checkpoint)
    elif operation == "hold":
        # Exercise real independent process kernel lock contention.
        with _exclusive(directory):
            print("SOURCE_ONLY_LOCK_HELD", flush=True)
            sys.stdin.readline()
    else:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
