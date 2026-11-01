# AoTT-8311 v2r8 inactive-bank staging readiness

Status: **offline kit reviewed, hardware staging NOT authorized**.

This document describes a guarded preparation process for the qualified
LL-XS1010 / PRX126-SFP-PON firmware family. No private archive, full flash
backup, device registration identifier, monitoring destination, credential,
actual network topology or hardware approval ID is published here.

## Latest hardware evidence and conditional bank plan

The last independently verified private hardware acceptance recorded a
committed **v2r7 in bank B**, with valid **v2r6 in bank A**. This is a
**historical record, not a fresh bank-state readback**.

If a fresh read-only inventory confirms that same running/committed state,
a stage-only r8 installation would:

- **Preserve bank B:** currently committed and running v2r7, including its
  complete recovery receipt and unchanged selector.
- **Overwrite bank A:** inactive v2r6 after the complete old bank has been
  independently backed up and verified off-device.
- **Leave boot selectors alone:** stage-only must not activate a trial,
  reboot or change the permanent committed-bank pointer.

If current state differs or any bank is incomplete, **stop and redesign the
plan**. Never infer present selectors from earlier trial notes. Never reuse
an expired native bank-state fingerprint or a former revision's approval.

## Offline preparation completed

- Exact private candidate label: `AoTT-8311-v2r8`, qualified target
  `WAS-110` and hardware profile `potron-prx126-aott-v1`.
- Two independently assembled rootfs images matched byte-for-byte.
- Two private five-member upgrade archives matched byte-for-byte.
- The archive's kernel and bootcore match the previously qualified vendor
  components. The aligned rootfs occupies **5,697,536 of 6,221,824 bytes**,
  leaving **524,288 bytes (512 KiB)** free.
- The current r7 upgrade script's **validation-only** path accepted the
  r8 archive within an isolated MIPS chroot, with no accessible UBI device
  nodes or network connectivity. No live flash command ran.
- The r7 runtime candidate qualifier accepted r8 **only when supplied
  the independently refreshed r8 candidate profile**. Its stale r7 profile
  correctly rejected the changed r8 runtime file pins. Staging must
  therefore use a separately reviewed candidate profile rather than
  assuming the installed profile is sufficient.
- A private off-device kit now holds only the exact hashed candidate
  archive and required local policy inputs. Its offline checker verifies
  file hashes, modes, archive component set, bank direction and
  non-authorized status. Attempts to reverse bank direction, modify a
  policy file, introduce a symlink or claim authorization fail closed.
- The private kit checker cannot transfer, stage, flash, reboot, approve
  or contact a device. No executable flash command is included in this
  public document.

## Mandatory live gates before *any* stage

1. Obtain fresh independently verified firmware, PON, host-link, management
   and full A/B bank readbacks. Confirm running=committed, no pending
   selection, healthy receipts and verified native state-guard support.
2. Capture fresh **complete backups of both firmware banks** to private
   off-device storage. Rehash and verify all components. Backups from a
   pre-r7 state do not replace a backup of the currently committed r7 bank.
3. Independently confirm the preserved running bank's kernel, bootcore,
   rootfs, management identity and recovery access. Verify the backup
   and local recovery procedure before touching an inactive bank.
4. Confirm the exact candidate SHA, r8 candidate runtime profile, board
   identity, partition/UBI geometry, flash headroom and installer binary
   compatibility. The native bank-state fingerprint must be freshly
   generated immediately before the single guarded stage action.
5. Obtain a **new target-issued approval for stage-only**. That approval
   does not authorize reboot, one-shot trial, permanent commit or other
   storage changes. Record all command status and complete readbacks.
6. Only after the inactive bank has been staged and independently verified,
   consider a second, separately approved one-shot boot. Preserve the
   previously committed bank. A third distinct authorization would be
   required for permanent commit after posttrial acceptance.

Every failing, inconsistent, missing or timed-out step is a **stop**,
not permission for unattended retry or automatic rollback.

## Remaining release qualifications

A validated private archive is not a booted firmware. Real UBIFS
restoration under power loss, collector authorization and firewall
ingress, syslog delivery, PON/OMCI registration, WAN, management,
CPU/RAM load and recovery behavior remain hardware-specific unknowns.

Earlier firmware banks can retain older monitoring authorization
behavior. Firewall-isolated management must remain part of the recovery
contract even after a successful r8 one-shot boot.

See the [boot-readiness audit](V2R8-BOOT-READINESS-AUDIT.md) and the
[complete r8 plan](V2R8-PLAN.md). This document grants **no** authority
to stage or deploy an image.
