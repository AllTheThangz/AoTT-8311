# AoTT-8311 v2r8 persistent monitoring configuration design

Status: **qualified design direction, NOT yet implemented or deployed**. The first r8 monitoring candidate remains a draft and does not yet guarantee monitoring settings survive a reboot or A/B bank transition.

## Why this is required

The qualified vendor rootfs contains `/lib/8311-upgrade-lib.sh`, which explicitly documents that the stock boot process can delete `rootfs_data` while the UBIFS `/ptconf` partition survives. The first r8 candidate writes monitoring options to `system.@system[0]` through UCI. This may work for the running boot, but UCI configuration in disposable rootfs data is **not a sufficient durability guarantee**.

The extracted vendor boot sequence also confirms:

- `/lib/preinit/90_8311_mounts` mounts `ubi0:ptconf` at `/ptconf` during preinit.
- `/etc/init.d/boot` runs at startup 10, generates UCI defaults, and calls `uci_apply_defaults`.
- `/etc/init.d/log` starts at 12 and consumes UCI `system` settings for remote syslog.
- `/etc/init.d/rpcd` also starts at 12, so an earlier restoration step must use the native UCI CLI, not assume the LuCI/ubus model is ready.
- `/etc/uci-defaults/zzz-8311` sets hostname/timezone and commits `system` without intentionally removing unrelated logging options.

These are static observations of the extracted firmware, not proof of persistent behavior on the running stick.

## Proposed authoritative storage

Store a **small, canonical configuration record** in the existing persistent volume:

- Directory: `/ptconf/8311-monitoring`, root owned, mode 0700, no symlinks.
- File: `/ptconf/8311-monitoring/config.json`, root owned, regular, mode 0600, bounded to 2 KiB.
- Schema version 1, with only the following string settings: `log_remote`, `log_ip`, `log_port`, `log_proto`, `aott_metrics`, `aott_metrics_client`, `aott_metrics_sha256`.
- `aott_metrics_sha256` holds only a domain-separated SHA-256 digest. The 256-bit plaintext bearer credential must never be written there, included in logs, or embedded into the firmware.
- There are no collector defaults, network addresses, operator hostnames, or organization-specific labels in the image.
- Atomic update using a unique 0600 temporary file in the same directory, verified bytes/mode, filesystem rename, synchronization, and a readback. Reject symlinks, incorrect ownership, malformed schema, unknown keys and partial records. Writes occur **only on administrator configuration changes**, not at scrape time.

JSON is a proposed storage representation rather than a committed wire format. The extracted image contains `jsonfilter`, `uci`, `logd`, `logread`, Lua 5.1 and LuCI, so restoring the small record should require no additional runtime or daemon.

## Boot restoration

An isolated startup restore would run **after stock startup 10** and **before logger startup 12**. It must:

1. Confirm `/ptconf` is mounted as the expected persistent UBIFS volume; otherwise leave remote monitoring **disabled** and report a safe error.
2. Validate the private directory and record type, ownership, mode, schema, complete field list, and bounded size. Never `source` configuration data into a shell.
3. Validate every destination, port, protocol and collector IPv4 field before any UCI write. A metrics-enabled record without a valid digest and exact collector IP is rejected, not guessed.
4. Update only the allowlisted `system.@system[0]` logging/monitoring keys, commit through the vendor UCI CLI, and confirm the effective settings. Do not change IP routing, firewall zones, login accounts, PON/OMCI state, firmware selectors or credentials.
5. Let the existing OpenWrt logger start normally. No additional logging daemon, flash-backed log history, periodic polling or auto-reboot is created.

All restoration behavior must remain fail closed on malformed or missing persistent state.

## Security-sensitive transition ordering

**Collector authentication must check both the durable record and the live UCI settings.** If either is missing, unreadable or inconsistent, the read-only endpoint denies the request. It must additionally require HTTPS, the configured exact peer IPv4, the actual management destination and the correct token digest.

- **Enable:** commit a valid durable record first, then apply UCI and verify both. The collector route stays denied until both records agree.
- **Rotate:** atomically install the new digest in durable storage, then live UCI. Return the one-time token only after both records are verified. On any error, do not expose the new token or assume old credentials were revoked.
- **Revoke:** durably write a disabled/tombstoned record **before** changing live UCI. The dual-record authorization check immediately rejects the old token even if live UCI restoration fails. Do not roll back a completed durable revocation into an enabled record.
- **Change syslog:** validate and durably stage the intended record, apply only logger-relevant changes and read back effective UCI. On failure, report whether durable or live state changed rather than silently claiming full rollback.
- **Reboot/bank switch:** restore to UCI from durable state, then independently verify collector denial/acceptance, local logging, and A/B management operation. An older firmware bank that does not implement the interface should not attempt to parse or rewrite the durable record.

The above is a design contract to be implemented and independently qualified, not a claim that existing draft source currently enforces dual-record consistency.

## Offline evidence and next tests

- The real vendor LuCI UCI model and uhttpd handler have been exercised with synthetic requests using host Lua 5.1 and the vendor MIPS Lua interpreter in QEMU. No live network or ONU was contacted.
- The vendor MIPS `uci` binary correctly parsed a synthetic, root-only UCI configuration under a disposable test directory.
- The vendor boot/start ordering and persistent-volume behavior were reviewed statically.

Required before merging:

- Prototype the exact persistent schema and fail-closed restore in a disposable rootfs, using real vendor UCI/jsonfilter binaries where feasible.
- Test missing/corrupt file, symlink/permission attacks, partial write, interrupted rotation/revocation, repeated boot, changed management IP, and A/B downgrade/return.
- Add negative authorization tests for a mismatched durable/live record and a failed restoration.
- Rebuild the private image independently, verify manifest/runtime pins and flash headroom, and perform separately authorized hardware acceptance.

No persistent configuration should be written on a production device merely to test this design.
