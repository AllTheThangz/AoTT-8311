# AoTT-8311 v2r5 hardware trial readiness

Status: Private offline verification passed. Live inactive-bank staging has not
been authorized or performed. The stage worker and its approval request are
not complete, so the present private stage folder is not executable.

## Hardware baseline and protection

- The supported PRX126-SFP-PON device runs committed v2r4 from bank A.
- Bank B contains valid v2r3 prior to the next firmware staging operation.
- Independent full-capacity off-device backups of both firmware banks and all
  six UBI volumes were captured and verified before any prospective write.
- The private v2r5 archive passed independent extraction, kernel/bootcore
  identity checks, rootfs checksum and capacity checks, and deterministic
  archive reproduction.
- Archive backup material, firmware binaries, device state and site-specific
  diagnostic values remain outside this public source-only project.

## Candidate runtime policy compatibility

The v2r4 installer normally checks candidate runtime contents against its
currently trusted integrity policy. The v2r5 rootfs intentionally changes
the CGI executable and four release identity files, so the unmodified v2r4
policy rejects v2r5.

An offline bridge using the original verified upgrade library and the
separately verified v2r5 runtime policy passed all these checks:

1. The existing v2r4 rootfs passes the common runtime-policy checks.
2. The candidate v2r5 rootfs passes common and candidate checks.
3. The old v2r4 policy rejects the intentionally changed v2r5 candidate.
4. Four isolated corruption tests were rejected for CGI, release metadata,
   OMCI and the shared upgrade library. The original files were restored
   after each test.

Only the five expected v2r4-to-v2r5 candidate policy records differ.
The common profile records, original kernel, bootcore, vendor PON stack,
bank control and installer remain unchanged. A read-only offline policy
check is not evidence that the live UBI write or read-only mounted-bank
qualification will succeed.

An additional source-only audit passes 29 installer contract conditions,
including active/committed-bank matching, pending trial rejection, selecting
the inactive bank, invalidating the target before writing, flash hash
readback, mounted runtime qualification, and opt-in reboot/trial controls.
Thirteen regression tests cover the validated contract and deliberately
broken variants. All 207 source regression tests now pass when Chromium is
required, with no skipped tests. The real browser ran 10 synthetic PON
Explorer cases, including out-of-order replies and unauthorized response
handling. The private MIPS CGI executable passed 36 isolated input checks
in QEMU. No operational bank-B worker or flash approval was created.

## Required inactive-bank staging workflow

The active v2r4 bank A must remain committed and untouched. A separately
approved stage-only operation, if later prepared and explicitly authorized,
would replace the three firmware volumes in inactive bank B. The existing
installer marks that bank incomplete before writing and complete only after
verifying flash content and mounted runtime files.

The install must never automatically reboot, select a one-shot activation,
commit bank B or alter provider provisioning. A detached approved worker
must verify exact device identity, root credential persistence, recovery SSH
access, pre-existing bank receipts, current boot state and the complete
private backups. It must reject changed inputs and unknown previous attempts.

The preflash procedure must use the qualified candidate runtime policy to
verify v2r5, while preserving the common runtime contract of the running
bank A. It must not permanently overwrite the running firmware's policy.

## Important recovery consequence

Once bank B is overwritten with v2r5, v2r3 no longer remains an immediately
bootable on-device fallback. The committed v2r4 bank A is the immediate
fallback. The previously captured v2r3 full-bank backup can support a
separately qualified, explicitly approved restoration if needed.

The full-capacity v2r4 and v2r3 recovery images were independently unpacked
from their private backups. Both SquashFS filesystems extracted successfully;
their essential OMCI and bank-control binaries matched. All 63 common
runtime-integrity entries were identical, while nine expected candidate
entries differed by revision. Both extracted filesystems passed their
corresponding candidate integrity policy, and both passed the shared v2r4
common policy. This provides filesystem-level recovery evidence, but
actual flash restoration and boot recovery have not been tested.

Any later one-shot boot of v2r5 and any permanent v2r5 commit require
independent approvals and verification of PON O5.1, host Ethernet, primary
WAN, authenticated management, credential persistence and recovery.

## Outstanding gates

- Finish and independently test the exact stage-only bank-B worker.
- Browser-specific tests are complete offline. Preserve the required CI
  browser gate and repeat it after any interface source changes.
- Request a separately issued target approval for the first flash write.
- Verify stage-only bank B readback while bank A remains committed.
- Authorize and test a one-shot v2r5 boot separately.
- Authorize any permanent commit only after full hardware acceptance.

No full firmware image, private backup, credentials, secret values or live
device identifiers belong in this document or the public repository.
