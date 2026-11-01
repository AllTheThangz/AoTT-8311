# v2r6 protected hardware-staging prerequisites

Historical pre-stage review. The privately approved stage, one-shot
trial, and independent bank-A commit have since completed. The latest
current-state evidence and qualification limits are documented in
[V2R6-HARDWARE-ACCEPTANCE.md](V2R6-HARDWARE-ACCEPTANCE.md).
The remainder of this file preserves the original pre-stage risk gates.

## Production status at the offline review

The sole qualified production baseline remains AoTT-8311-v2r5, active and
committed in firmware bank B. Bank A contains the independently verified
v2r4 recovery image. The PRX126 device is registered at PON O5.1 with a
10 Gbps host Ethernet link.

This document is an offline deployment-risk assessment, not a live
installation request or permission to write firmware.

## Why the policy handoff requires explicit review

The v2r5 runtime integrity profile has 133 pinned file/link records.
The reviewed v2r6 candidate profile has 135. All 63 common records and
the original kernel/bootcore compatibility pins are identical.

Nine existing candidate-file pins differ for reviewed v2r6 source,
release-label, shared firmware library and installer changes. Two additional candidate pins protect the firmware
bank-control utility and the background web job worker. The candidate
filesystem matches all its reviewed file pins, but the existing v2r5
candidate policy intentionally rejects files it does not recognize.

A future hardware staging procedure must use an independently pinned
candidate runtime policy. It must not replace the running v2r5 system
policy, trust a random uploaded archive to authorize itself, or skip
candidate readback verification. The installer library and its lock
contract remain separately protected.

The current offline policy comparison is recorded privately in
`reports/v2r6-sharedguard-policy-bridge.json` on a private build host.

## Recovery consequence of writing bank A

The next inactive bank is **A**, not B. Bank A currently holds the on-device
v2r4 recovery image. Replacing A with v2r6 would remove that immediate
on-device v2r4 fallback. Committed v2r5 in bank B must remain untouched
throughout staging, boot selection and the initial one-shot trial.

Fresh full-bank recovery captures for the current v2r4 bank A and
committed v2r5 bank B were completed privately on a private build host, including all
six full-capacity UBI volumes and independent readback verification.
The captured archives were subsequently rehashed and their tar members,
sizes and image prefixes independently checked. The backup completion
receipt remains private, not in this source tree.

Before any v2r6 staging authorization:

1. Capture fresh private full-volume backups of BOTH bank A (v2r4) and
   bank B (v2r5) to private off-device storage, including the six UBI components and the
   boot environment.
2. Independently verify all captured bytes, hashes, lengths, receipt
   records, and restoration/extraction feasibility.
3. Confirm valid and complete A/B receipts; a running and committed B
   selector; no pending boot; stable credentials, SSH, PON O5.1, Ethernet
   and primary WAN access.
4. Recheck the exact private v2r6 archive, component hashes, fixed bank
   capacity, target board/firmware profile, and candidate policy bridge.
   The v2r6 web installer requires the reviewed active/target bank pair
   and short-lived, reboot-aware bank-state fingerprint, both rechecked
   under firmware/environment locks before any incomplete receipt or
   flash write. When first installing v2r6 from v2r5, these v2r6
   safeguards are not yet running and cannot be relied upon. An
   independently approved v2r5-compatible staging procedure is needed. The first-stage
   target should remain A; a changed active bank must abort before writing.
5. Qualify the native guarded bank-control command and the expanded
   install-target preconditions in an isolated
   compatible environment. Static tests, browser mocks and syntax-only
   QEMU checks do not satisfy this integration requirement.
6. Use a separately approved, non-rebooting stage-only operation. It
   must target A, mark it incomplete before any write, read back every
   flashed component, and complete its receipt only after full checks.
7. Verify bank B remains running and committed, both image receipts
   remain valid, and optical/WAN/HTTPS/SSH services continue to work.
8. Separately approve any one-shot trial boot of A. Observe its live
   hardware behavior before considering another approval to commit A.

Neither the initial backup activity, a stage write, a trial reboot, nor a
permanent commit is authorized by this document.

## Outstanding integration limitation

The expanded v2r6 candidate adds a server-bound bank fingerprint that
includes bank selectors, image receipts, the kernel boot UUID and a
five-minute time bucket. Authenticated firmware-install jobs additionally
carry an expected active/target pair, checked by the installer after it
takes its firmware locks. This ensures that a queued web job cannot
silently overwrite the opposite bank after another administrator changes
the active firmware. The native code has passed syntax checks under
a MIPS32r2 BusyBox and Lua runtime, and pure reference models test reboot
and expiry invalidation. However, the complete guarded command execution
path has not been exercised against a compatible isolated environment.

Do not advertise the candidate as hardware-qualified or safe for live
installation until that gate and the recovery requirements above are met.

Keep subscriber-specific backup files, boot variables, credentials and
device identifiers out of the public source repository and CI logs.
