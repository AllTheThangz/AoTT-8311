# AoTT-8311 v2r8 persistent monitoring configuration design

Status: **implemented as a source-only offline r8 candidate, not hardware-qualified or deployed**. The protected record, early startup restore, and dual-record access check require independent UBIFS, boot and bank-transition acceptance.

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

The draft implements a canonical JSON record and validates every field, size, owner, file mode and mount source. Only existing Lua 5.1, nixio, LuCI JSONC, UCI and BusyBox functionality is used. The running rootfs carries no collector-specific values.

## Boot restoration

An r8 startup restore runs at START=11 after the stock START=10 boot and before the vendor START=12 logger. The existing UCI defaults enable the hook and invoke a first-boot restore. Its implementation:

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
- **Interrupted revocation:** reject ordinary settings saves and credential
  rotation while durable and active settings disagree. Otherwise stale UCI
  could reinstate a revoked token. Revocation remains an available recovery
  operation. Other changes require reviewed reconciliation of the intended
  durable state.
- **Failed boot restore:** reject pre-existing unrelated staged UCI edits,
  revert newly staged monitoring changes if set/commit fails, and preserve
  prior committed system values. A failed revert is an explicit error.

This order is implemented in the draft offline source and verified with deterministic failure-injection tests. Actual UBIFS persistence and live boot timing have not been qualified.

### Exact vendor UCI test isolation

The vendor CLI accepts -p to add a staging search path and -P to set the
default staging path, but these options do not fully eliminate fallback to
the built-in /tmp/.uci path. A naive offline test can mistakenly inspect
uncommitted values and claim a successful commit.

The r8 test harness therefore executes the actual MIPS UCI binary inside
a **private, temporary vendor-rootfs chroot**, with its own default
staging directory. /proc is bound only inside a child mount namespace
because UCI's commit implementation needs /proc/self/fd. The harness
reads the **physical committed config file** and verifies staged deltas
are empty after success or recovery; the host staging directory is
independently checked for changes.

Five deterministic tests cover successful restore and repetition,
no-record refusal, pending unrelated edits, failed mid-set recovery
and failed commit recovery. This procedure is a development test only
and does not mount or write the production /ptconf volume.

## Offline evidence and next tests

- The real vendor LuCI UCI model and uhttpd handler have been exercised with synthetic requests using host Lua 5.1 and the vendor MIPS Lua interpreter in QEMU. No live network or ONU was contacted.
- The vendor MIPS `uci` binary correctly parsed a synthetic, root-only UCI configuration under a disposable test directory.
- The vendor boot/start ordering and persistent-volume behavior were reviewed statically.

Required before merging:

- Offline canonical-record and boot-restore fixtures pass; independently confirm the implementation on real UBIFS and the exact kernel/boot service ordering before hardware acceptance.
- Test missing/corrupt file, symlink/permission attacks, partial write, interrupted rotation/revocation, repeated boot, changed management IP, and A/B downgrade/return.
- Add negative authorization tests for a mismatched durable/live record and a failed restoration.
- Rebuild the private image independently, verify manifest/runtime pins and flash headroom, and perform separately authorized hardware acceptance.

**Fallback caveat:** v2r7 lacks the r8 durable token and collector security policy. Switching to the older bank restores its inherited behavior, including the legacy metrics route, so external management firewall controls must remain in place. A/B fallback cannot be claimed to preserve r8 endpoint authorization on older firmware.

No persistent configuration should be written on a production device merely to test this design.
