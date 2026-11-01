# v2r6 server-bound firmware state preconditions

Post-qualification update: the state-guarded native bank-control
commit was executed successfully on the privately qualified PRX126
device, followed by independent verification of both banks. The
complete v2r6 web-upload installer write path has not been separately
exercised on hardware. Historical offline-test limits below describe
the source qualification period before the staged trial and commit.

## The original gap

The v2r6 browser already rechecked bank status before a firmware action.
However, that check occurred before a separate HTTP POST, job enqueue,
worker start and firmware lock acquisition. A concurrent administrator
could change the bank selection or image receipts between those steps.
A browser confirmation alone cannot eliminate that race.

## The new guarded flow

1. The native bank-status utility takes the firmware and environment locks.
2. It serializes its exact live selectors, validity flags, bank receipts
   and component digests, the kernel's per-boot UUID, and a five-minute
   UTC epoch window. It hashes the domain-separated byte sequence into a
   lowercase SHA-256 state fingerprint.
3. The authenticated HTTP response is explicitly marked no-store.
4. The browser verifies the fingerprint format and includes it in the
   reviewed-state signature.
5. Before a bank action, the browser fetches fresh status, compares it with
   the reviewed snapshot, shows the consequence and asks for confirmation.
6. The authenticated POST carries the 64-character state fingerprint.
7. The LuCI controller validates the field and binds it to the queued job.
8. The job worker rejects absent or malformed fingerprints, then passes
   the exact value to the native guarded bank-control command.
9. The native bank-control script acquires the firmware and environment
   locks, checks the trusted boot contract, serializes its CURRENT state,
   and compares the fingerprint before any selected operation proceeds.
10. The same fingerprint routine is now shared by bank control and the
    native firmware installer, preventing two implementations from drifting.
11. Authenticated firmware installations bind the confirmed active/target
    bank pair and the fresh fingerprint through the queued web worker.
12. The installer checks both the fingerprint and bank pair under the
    firmware/environment locks, and independently rechecks the fingerprint
    immediately before the first incomplete receipt or image write.

The controller's CSRF and session checks remain required. The fingerprint
is a concurrency precondition, not a password, secret, or access token.
The original local administrator bank-control CLI remains available for
authorized recovery and diagnosis.

## Failure behavior

A mismatch is rejected before the selected operation. The browser must
display the changed selection and require an entirely new review. Old
queued jobs cannot run without the guarded fingerprint. Unknown actions,
malformed hashes, inconsistent selectors and incomplete required bank
receipts fail closed.

A reboot changes the kernel boot UUID even if all bank selectors and
receipts remain identical. Five-minute time buckets ensure a queued
fingerprint does not remain valid indefinitely. The fingerprint expires
at the NEXT bucket boundary, so a newly fetched status can expire sooner
than five minutes if the request approaches that boundary. Network time
adjustments may also invalidate it. The correct response to expiry is
a fresh status review, never an automatic retry or an unchecked fallback.

No operation is automatically retried after an ambiguous failure, and
there is no automatic reboot or commit from status polling.

The guard compares trusted bank selector metadata and receipt hashes.
It does not rehash the entire NAND flash on every status request. Full
bank integrity verification remains a separate operation.

The guarded firmware installer refuses a fingerprint without a complete
opposite-bank A/B target pair, and refuses a target pair without a
well-formed fingerprint. Archive validation alone does not accept a
write precondition. Existing direct administrator stage-only commands
can omit the optional precondition for authorized recovery procedures.

These are v2r6 runtime improvements. The initial stage of v2r6 from a
running v2r5 instance cannot assume that v2r6 source code is already
active. That first stage still needs its own independently authorized,
verified policy bridge and recovery protections.

## Limits and acceptance

The lock-bound check covers other operations that cooperate with the
same firmware and environment locks. It is not a defense against a
privileged actor deliberately bypassing both locks.

Source, pure reference-model and real-browser regression tests cover
status formats, missing and modified fingerprints, selector changes,
reboots into the same bank, five-minute boundary expiry, confirmation
and stale-request rejection.
Shell/Lua syntax, archive qualification and static source contracts
have passed offline. The complete guarded command path has not yet
been exercised in an isolated device-compatible runtime; no hardware
trial or production installation is authorized by this document.

A future hardware trial must qualify the new native bank-control utility
and job worker, retain an independently verified fallback bank, and take
fresh off-device full-bank backups before changing inactive flash.
