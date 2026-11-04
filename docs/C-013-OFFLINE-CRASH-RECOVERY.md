# C-013: Offline crash-safe configuration transaction and recovery matrix

**Checkpoint:** November 3, 2026. **Status:** IN_PROGRESS, source-only
Linux filesystem/process testing. Physical PRX126 persistence and
rollback are **NOT** qualified. No live ONU operation occurred.

## Why this matters

C-012 tests all 54 GUI fields against an offline setter and readback
fixture. C-011 currently offers source readback for 45 of 54 fields.
Neither proves that a setting survives a service restart, reboot, A/B
transition, interrupted flash write or power outage. S-016 introduces a
limited, encrypted configuration backup/restore model, but does not
implement an on-device transaction journal or independent watchdog.

C-013 begins closing that gap **without taking risks on the only
production ONU**. This tranche tests an actual Linux file transaction
and kernel process lock in a disposable synthetic test directory on
Hermes, including new independent-process recovery after an
interrupted operation.

## Source-only implementation

- tools/c013_offline_transaction_journal.py
- tests/c013_transaction_worker.py
- tests/test_c013_transaction_recovery.py

The fixture accepts ONLY an exact path pattern under /var/tmp/ with
the aott-c013-recovery-test- prefix. The directory must belong to the
current user and be mode 0700. It never reads /ptconf, /etc/config,
U-Boot, NAND/MTD, subscriber registration, ISP identity, or real
certificates/keys. Synthetic fixture keys are limited to benign
sampling and telemetry flags/intervals. The test process cannot
configure an ONU or change an actual web/forwarding service.

A real, nonblocking Linux fcntl process lock is held throughout each
isolated operation. The lock file is created mode 0600 and is never
unlinked. Recursive same-process ownership is refused BEFORE opening
a second lock fd, avoiding the POSIX close-unlocks-existing-owner
pitfall. Concurrent independent processes cannot silently write
another candidate.

The transaction uses fixed, root-of-fixture names for the current
configuration, previous verified copy, candidate and journal. Data
uses bounded, canonical JSON. The file transaction orders durable
writes as follows:

1. Verify active fixture revision, explicit synthetic operator consent,
   independent recovery/known-good bank receipts, directory and inode
   permissions, and absence of a prior pending transaction.
2. Create and fsync the **previous** configuration snapshot.
3. Write and fsync a canonical pending journal containing source/
   candidate revision numbers and SHA-256 checksums.
4. Stage the candidate and fsync the file and parent directory.
5. Atomically replace and read back the current fixture configuration.
6. Leave the transaction **pending**, without automatically treating
   new values as permanently committed.
7. On a **separate** explicit confirmation with positive service,
   effective-state, alternate-access and rollback readiness receipts,
   write the durable committed journal marker before cleanup.
8. Remove candidate/backup files and journal, with directory fsync.

Without final confirmation, an independent process reads the verified
journal and previous snapshot and restores the old configuration,
then persists a rolled_back marker before cleanup. A crash after
the commit marker retains the newly confirmed revision, while
unconfirmed crashes restore the previous revision. Interrupted
cleanup can be resumed idempotently. An orphan stage created before
a journal is recovered only if the previous copy matches the current
file; other unknown states are refused, not overwritten.

**This is not a cryptographically authenticated journal.** Checksums
detect accidental corruption, not a malicious privileged writer.
All data in these tests is synthetic and non-sensitive; the prototype
must not receive real credentials. A production implementation would
also require an encrypted and verified secret-safe backup format,
board-specific write ordering, fsync/UBIFS proof and a separately
running watchdog independent of a web-browser session.

## Offline verification and fault injection

Run from a checked-out source directory:

~~~sh
python3 -m unittest discover -s tests \
  -p 'test_c013_transaction_recovery.py' -v
~~~

The test worker is a separate Python OS process. It deliberately exits
with a fixed synthetic crash status at each of these checkpoints:

- After the previous snapshot is durable
- After the pending journal is durable
- After the candidate is staged
- After installing the candidate
- After verifying the candidate's readback
- After the committed marker is durable
- During candidate/previous/journal cleanup
- After restoring the previous configuration
- After the durable rollback marker and during rollback cleanup

Additional tests exercise actual independent-process lock contention,
SIGKILL release, nested lock refusal, stale revision, refused unknown
settings and missing authorization/verification receipts, unexpected
file symlinks/hard links, a modified directory, corrupted backups,
unknown current config content and orphan temporary files.

All tested crash recoveries use real filesystem writes and process
exits **only in the disposable Hermes fixture**. They are not actual
power-cut, cold-boot, uhttpd service restart, bank switch or production
NAND endurance tests. A source test result must never be labeled
DONE_HARDWARE merely because the fixture is crash-consistent.

## Production gates still required

1. The [nine sensitive readbacks](C-011-SENSITIVE-IDENTITY-READBACK.md) now
   close stored-source coverage to 54/54. Qualify their actual native
   consumers and privacy on the target without exposing raw material.
2. Map all 54 source setters to actual board-dependent persistence,
   effective consumer state, correct redaction and per-field rollback.
3. Inspect a separately authorized and recoverable PRX126's real
   configuration storage, journal options, root-owned paths, filesystem
   semantics, flash write endurance and per-bank persistence.
4. Implement a native on-device transaction journal with encrypted
   or otherwise protected secret material, strict process ownership,
   validated file/fsync order, a separately verified backup and a
   trusted independent recovery watchdog.
5. Prove fallback management access, negative/delayed service readiness,
   explicit confirmation, actual uhttpd/service restart, reboot,
   A/B transition where appropriate, and power-cut recovery.
6. Confirm O5.1 optical registration, 10G host Ethernet, ISP Internet
   service, IPv4/IPv6 and VLAN/bridge forwarding remain stable.
7. Require separate explicit authorization before any device
   configuration write, stage, boot, or permanent firmware commit.

**No deployment:** no firmware overlay file, LuCI controller, UCI
commit, uhttpd restart, firewall operation, ONT/ONU management write,
network command or A/B bank change occurred in this source tranche.
