# AoTT-8311 v2r6 source and private hardware release (historical)

> The descriptions of running/committed v2r6 below record its earlier
> acceptance point in time. v2r7 was subsequently accepted and committed
> on the same qualified hardware; v2r6 remains a valid on-device
> alternate. See [v2r7 acceptance](V2R7-HARDWARE-ACCEPTANCE.md).

Product: AoTT-8311
Version: v2
Revision: r6
Machine identity: AoTT-8311-v2r6
Display identity: AoTT-8311-v2 r6
Compatibility profile: potron-prx126-aott-v1
Status: Privately hardware-tested and committed in bank A on one PRX126-SFP-PON ONU. Public repository remains source-only.

## Verified hardware state

AoTT-8311 v2r6 is running and permanently committed on bank A of the
single qualified LL-XS1010 / PRX126-SFP-PON ONU. Bank B contains verified
v2r5 as the valid alternate firmware. There is no pending activation or
running uncommitted trial.

Before staging v2r6, bank A held v2r4 and bank B held committed v2r5.
Both old banks were captured at full volume capacity, independently
reread, hashed, and preserved privately off-device before installation.
The original v2r4 image is now an off-device recovery backup rather
than the on-device bank-A fallback.

Vendor kernel, bootcore, PON/OMCI hardware stack and crypto ABI remain
unchanged. The build source, runtime integrity profile and approval
receipts are retained privately.

## Development changes

The firmware page now describes the consequence of the next reboot,
the committed recovery bank, and whether a one-time trial is pending.
The same preview covers stable operation, a scheduled one-time boot,
and a trial already running. It uses only the existing authenticated
bank-state response and has no new device configuration endpoint.

Browser controls fail closed if the returned boot state has a conflicting
running/committed relationship, an invalid pending trial, a missing bank
record, or an unverified active, saved, or scheduled image. Unverified
data is never represented as a known boot plan.

The interface also shows the age of its last authenticated bank check
and locks actions once that state becomes older than 60 seconds.
Immediately before a firmware-bank action it re-reads the device state,
checks selectors and component receipts against the previously reviewed
status, and requires confirmation again. A failed or changed status read
prevents submission, and unknown actions remain disabled.

v2r6 additionally binds the native firmware-bank state fingerprint to the
authenticated POST and background job request. The guarded bank-control
command recomputes this fingerprint under the firmware and environment
locks before executing the selected action. The fingerprint includes a
kernel boot UUID and five-minute time window, so it becomes invalid after
a reboot or when the next time window starts, even if bank selectors
remain unchanged. Missing, expired or malformed preconditions fail closed. Existing direct administrative CLI operations
remain available for authorized recovery. The state fingerprint is a
concurrency control, not a substitute for authentication or full bank
integrity validation.

An additional source-only release auditor compares two independent
private rootfs images, tarball members and build receipts, including
timestamps, permissions, source-manifest hashes and fixed vendor ABI
pins. It produces checksum evidence, not a cryptographic signature.

The UI does not itself initiate a trial, reboot, write or commit when
the status is rendered.

## Unchanged compatibility boundary

This candidate does not alter the proprietary OMCI process, PON provisioned
identity, kernel, bootcore, bootloader selection contract, cryptographic
shared libraries, SSH/HTTPS authentication, or vendor MIB handling.

In particular, the required OpenSSL libcrypto 1.1 ABI remains present;
it must not be removed or exchanged for an unqualified ABI to save space.

## Completed private offline qualification

The extended v2r6 source passes 284 regression tests with no failures
or skips, including 41 tests executed in real isolated Chromium. Those
browser tests verify pending/committed boot consequences, expired bank
status, fresh pre-action reads, changes by another administrator,
rejected or unavailable server responses, cancellation, component-hash
changes and unknown action names. No browser test performs a real
firmware operation.

Twelve synthetic source-provenance tests reject malformed USTAR member
order, extra files, duplicate names, changed bytes, timestamps, modes,
untrusted symlink inputs and duplicate/hardlinked build artifacts
masquerading as independent outputs. The mandatory CI browser gate covers
both the PON Explorer and firmware management suites. All 29 original
static installer safety checks continue to pass. Shell/Lua syntax,
source manifest and secret-disclosure gates also pass.

Two separately built 1 MiB XZ SquashFS images match byte-for-byte.
Both private five-member firmware archives match byte-for-byte and pass
independent extraction, runtime qualification and source-pair provenance
checks. The aligned rootfs is 5,689,344 bytes inside the fixed
6,221,824-byte volume, leaving 532,480 bytes (520 KiB) of headroom.
The private upgrade archive is 13,414,400 bytes. Exactly twelve runtime
files differ from committed v2r5, with no new or removed paths.
The firmware integrity profile now protects 135 selected records,
including new candidate pins for the job worker and native bank control.
Neither the checksum report nor this testing constitutes a
cryptographically signed release attestation.

These checks verify offline packaging, source contracts and browser
behavior. The native MIPS32r2 BusyBox shell and Lua source also pass
non-executing syntax checks under QEMU. Nine reference-model tests cover
receipt changes, reboot identity and expiry boundaries, while additional
source-contract tests verify the same lock-bound guard is required by
queued firmware installations as well as bank operations.

The native shared bank-state fingerprint was verified under isolated
target-MIPS emulation, including expiry and altered-receipt cases. The
actual guarded bank-control commit was subsequently exercised once
on the supported device under an independently issued approval.
The entire web-upload installer write path was not separately exercised
on the live v2r6 system and remains a specific integration-test limit.

The v2r5-to-v2r6 candidate-policy bridge was reviewed offline: 63 common
integrity records remain unchanged, nine existing candidate pins change,
and two additional records protect the bank-control utility and job worker.
At the time of initial v2r6 staging, the inactive slot was bank A,
which held v2r4. The stage operation replaced its on-device recovery
image only after the full off-device backup and independent policy
bridge were verified. v2r6 then passed a separately approved one-shot
trial and permanent commit. The current inactive slot is bank B,
containing v2r5, which must be preserved until a separately approved
future release can be qualified.

## Completed hardware acceptance

The reviewed private v2r6 archive was written into inactive bank A
using a v2r5-compatible, no-reboot, no-commit staging procedure with
an independently pinned candidate policy. The operation was followed
by full bank-A and bank-B readbacks and live optical, WAN and
management verification.

A second approval selected a one-shot boot of v2r6 in bank A while
v2r5 remained committed in bank B. Postboot checks confirmed the
new boot identity, correct bank selectors, PON O5.1, a negotiated
10 Gbps host Ethernet link, accessible HTTPS management, persistent
root and SSH recovery, pinned WAN egress, and both bank contents.

A third distinct approval executed one native guarded commit of the
running bank A. No reboot or firmware flash occurred during this
operation. A separate independent readback confirmed active A,
committed A, no pending activation, both banks complete and valid,
and continued connectivity.

Detailed sanitized evidence and limits are in
[V2R6-HARDWARE-ACCEPTANCE.md](V2R6-HARDWARE-ACCEPTANCE.md).
Long-term stress and uptime are still not qualified.

## Qualification requirements

The public source overlay must pass release-identity and manifest checks,
privacy screening, shell and Lua syntax, headless-browser tests with real
Chromium, static bank-control tests, and comparison against the committed
v2r5 baseline.

Any private firmware archive must also pass deterministic rootfs build,
rootfs extraction, byte-level runtime differences, fixed 6,221,824-byte
volume capacity, and kernel/bootcore compatibility checks. Source tests
do not establish real-world boot reliability or WAN operation.

The frozen v2r6 private build was created as
UNTRIALED_OFFLINE_ONLY with safe_for_live_install=false. Those
historical fields describe its original offline build qualification,
not the later successful private hardware trial and commit. Do not
rewrite the signed-off source or archive manifest to erase that
build history. A checksum report is not a signing attestation.

Staging, a one-shot trial and the permanent commit each received
a separate approval and independent hardware verification. The
same independent-approval requirement applies to future firmware
writes, disruptive boots and commits. A private hardware acceptance
does not authorize publication of proprietary vendor binaries.

## Redistribution

This source tree contains text overlays, test fixtures and documentation
only, not private firmware images, device captures, production network
identifiers, subscriber credentials, or protected vendor binaries.
Documentation belongs in the source repository, not the ONU rootfs.

See [V2R6-BOOT-PLAN.md](V2R6-BOOT-PLAN.md) and the [v2r6 hardware acceptance](V2R6-HARDWARE-ACCEPTANCE.md).
