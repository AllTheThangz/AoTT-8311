# S-016: Secure configuration backup and restore, offline source model

**Checkpoint:** November 3, 2026. **Status:** IN_PROGRESS, source-only
proof of redaction, encrypted backup and guarded restore decisions.
No live ONU, user configuration, private key or firmware bank modified.

## Residential intent

Owners should be able to download a safe configuration summary, opt
explicitly into a protected full backup when needed, and recover their
configuration after a firmware update without losing ISP registration,
local HTTPS, or a safe management path. A cross-bank restore must
never be assumed safe merely because two images share a version label.

This first S-016 implementation is **not** an installed backup/restore
feature. It models only a small allowlisted subset of the eventual GUI
settings. A full product backup must independently cover every real
vendor-supported control and service-specific file with a verified
compatibility and recovery plan.

## Source implementation

Code: tools/s016_offline_backup_recovery.py

Tests: tests/test_s016_offline_backup_recovery.py

The implementation is PURE IN-MEMORY and cannot execute system calls,
read /ptconf, write UCI, touch hardware, load subscriber material,
reload uhttpd, stage firmware, change an A/B selector or open a
network port. The test fixtures contain synthetic values only.

### Safe default, redacted export

The default public summary contains a fixed allowlist of generic
configuration field names and safe Boolean/interval values. It replaces
all credential, PON identity, hostname, management IP, TLS material,
syslog destination, VLAN and allowed-source values with [redacted].
It also suppresses the device-profile, bank and firmware fingerprint.
It never exposes raw UCI text, derived hashes of secrets or user
certificate/key contents.

The summary is **not** a usable full restore archive.

### Opt-in protected private backup

A separate function accepts a validated configuration bundle and a
strong passphrase supplied as in-memory bytes, with no CLI flag or
logged password. The entire canonical JSON bundle, including profile,
bank, firmware SHA-256 identity and synthetic secrets, is encrypted
using:

- AES-256-GCM with a fresh random 96-bit nonce
- scrypt KDF with a fresh random 128-bit salt, N=16384, r=8, p=1
- Additional authenticated data identifying the S-016 archive format
- Strict limits on raw configuration data and encrypted archive size
- A fixed canonical envelope schema, no arbitrary Python deserialization
  or executable code, no implicit compression
- Authentication check before the archive is decoded, validated or
  considered for restore

Corrupted, tampered, truncated, oversized, noncanonical and wrong
passphrase archives fail with fixed non-secret error codes. Different
export operations produce distinct salted and nonce-protected
archives even for identical synthetic configuration.

**The encrypted archive is only returned in memory by the source
function.** There is no upload/download route, production key escrow,
recovery code, encrypted file storage, passphrase UI, KDF resource
measurement on the actual PRX126, or cross-device interoperability
claim. The Python cryptography dependency is offline-host-only.
Real subscriber credentials were never used in these tests.

### Guarded restore preview

A restore planning function consumes a decrypted, schema-validated
bundle, checks exact board/ABI/partition/optics profile compatibility,
active bank, firmware fingerprint and target configuration revision,
and refuses without explicit operator authorization.

An **additional** migration approval is required when the source and
target firmware hashes or bank identities differ. Mismatched board
or partition profiles are rejected rather than transformed.
Cross-device, cross-architecture and arbitrary UCI migration are not
supported.

Separate positive receipts must establish, before even planning a
restore:

- Independently proven local management recovery
- An existing private backup and separate snapshot of current config
- A known-good firmware bank preserved for fallback
- Verified target revision and restore schema
- Full alternative recovery and verified restore readiness
- TLS certificate/key validation and rollback when TLS fields change
- Default-deny and rollback proof when remote GUI access changes

The safer integrated call authenticates and decrypts the private
archive *before* running this plan. A redacted public preview or
invalid encrypted archive cannot be used as a restore source.

A source-only shadow-state simulator models applying allowed fields to
an isolated in-memory copy. Injected failures return the identical
original config. This demonstrates the required **logic**, not
real NAND, UBIFS, service restart, file permissions, network recovery,
power-loss resilience or transactional rollback.

The strongest result is
SOURCE_RESTORE_PLAN_READY_NOT_DEPLOYED, not production approval.
No planner returns the decrypted configuration values in its receipt.

## Reproduce safe source tests

~~~sh
python3 -m unittest discover -s tests \
  -p 'test_s016_offline_backup_recovery.py' -v
~~~

These tests cover redaction, synthetic credentials remaining private,
encryption/decryption, nonce and salt randomness, wrong passphrases,
tampered ciphertext, unsupported KDF, rejected malformed/oversized
archives, board mismatch, stale revisions, cross-bank and cross-image
approval, missing recovery guards, TLS and remote-access guards, and
rollback equality after injected partial failures.

## Hardware and release blockers

1. Obtain explicit authorization and recoverable read-only access to
   a specific PRX126. Independently verify bank fingerprints, current
   config storage, paths, ownership and backups without exposing secrets.
2. Build a complete versioned configuration field inventory across
   original/r8 and prospective platforms, including vendor PON/OMCI,
   VLAN, management, HTTPS, saved certificates, syslog, sampling,
   remote controls and documented sensitive identity semantics.
3. Implement a native bounded export and restore agent that uses
   supported on-device crypto libraries and verified memory limits.
   Do not assume Python cryptography or host scrypt capacity exists on
   the actual stick.
4. Implement operator-controlled local encrypted backup download
   with private passphrase entry and no secret leakage to logs,
   browser history, telemetry or the public repository.
5. Implement an independent on-device transaction journal, verified
   rollback/restore and power-loss recovery. Preserve a known-good
   firmware bank and a tested alternate local management path.
6. Test conflicts, schema migrations, cross-bank compatibility,
   certificate/key permissions, service restarts, reboot durability,
   flash wear, forwarding stability and genuine browser acceptance.
7. Do not stage, activate or commit a firmware bank as a side effect of
   restoring ordinary configuration.

**No private production backup has been generated or saved.** All
source evidence remains IN_PROGRESS, not a ready-to-use recovery
feature. ISP registration, PON O5.1 operation, firmware A/B contents,
the current HTTPS service and running network are untouched.
