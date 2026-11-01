# v2r6 firmware bank status and reboot-consequence preview

## Motivation

A two-bank firmware installation has distinct active, committed and pending
selectors. Confusing these during a trial can unintentionally restart the
previous firmware, or give the impression a trial is already committed.

The v2r6 web page explains the *next reboot*, not an invented automatic
rollback timer. The existing trusted bank-state response is the only source
of the displayed plan. No additional server API or PON/OMCI operation is
introduced.

## UI scenarios

| Firmware state | Next reboot preview | Saved recovery |
| --- | --- | --- |
| Running bank B, committed B, no pending trial | Bank B (committed) | Bank B (committed) |
| Running A, committed A, pending trial B | Bank B (one-time boot) | Bank A (saved) |
| Running trial B, committed A | Bank A (saved) | Bank A (saved) |
| Contradictory, missing, or incomplete bank information | Unknown, refresh required | Unverified |

The preview does not claim that any particular bank will successfully boot.
Image validity flags and receipts remain separate from direct firmware
integrity verification.

The firmware upload panel also displays the exact inactive bank that
the current verified state would overwrite, and explicitly warns that
fresh, independently verified off-device full-bank backups are required.
Installation is disabled when bank status is stale, or when a trial or
pending boot is active. Archive validation and upload discard remain
available as non-flashing operations.

Before confirmation, the browser checks bank status again and rejects
a changed active/target selection or altered upload. The authenticated
web installation job carries both expected bank selectors, and the
native installer checks them while holding the firmware locks before
any target receipt or flash writes. This is an overwrite-destination
precondition, not proof that any off-device backup exists.

## Safety invariants

1. Only a schema-1 response with a verified boot contract is accepted.
2. The running/committed relationship must agree with the trial flag.
3. Pending trial selection must reference the other bank while the current
   running bank is committed and no trial is already running.
4. Every bank involved in the running, committed, or pending path must
   have a complete receipt and a valid image flag.
5. Both A/B records must be present and have typed validity and receipt fields.
6. Invalid or missing responses clear previous bank labels, show an unverified
   reboot consequence and lock firmware-bank controls.
7. Bank state older than 60 seconds is explicitly marked stale and locks
   firmware-bank actions until a successful live refresh.
8. The firmware page re-reads authenticated bank status immediately before
   confirming an operation. It compares active/committed/pending selectors,
   trial status, image validity, receipts and component hashes to the state
   the operator previously inspected.
9. A conflicting or failed read aborts the operation without sending a POST.
   Failed status reads clear the previous authorization rather than enabling
   a repeated action against stale information.
10. The confirmation dialog appears only after a fresh matching read. A
    cancellation never submits a firmware operation.
11. Unknown bank actions are disabled rather than allowed by default.
12. All displayed status text uses DOM text APIs, never HTML injection or
    live shell data. No action executes automatically during page refresh.

The 60-second limit is a local browser freshness interval, not a claim
about when the ONU last checked its flash. The authenticated status
response includes a SHA-256 fingerprint of the native bank state,
both firmware receipts, the current kernel boot UUID, and a five-minute
time window. The controller binds it to the queued job, and
the native guarded bank-control command verifies an exact match under
the existing firmware/environment locks before changing selectors or
requesting a reboot. This closes the gap between browser confirmation
and delayed job execution for cooperating firmware commands.

The fingerprint is not a secret or authorization token, and it does
not replace the backend's CSRF checks, full flash checks or recovery
safety rules. See V2R6-STATE-GUARD.md for limits and qualification gates.

## Testing

The isolated headless Chromium suite checks stable operation, one-time
selection, active trial, contradictions, missing fields, invalid target
images and malicious selector text. Additional cases exercise expired
bank-state authorization, an unexpected bank change before submission,
a changed component digest, a second administrator's commit, a failed
live-status request, an invalid response, cancellation, an unknown
action and exactly one explicit submission after an identical fresh read.

All requests to unapproved origins are blocked. No test operates on
the real ONU or submits a live firmware job.

Server-side bank-control rules, flash verification, recovery, and bootloader
behavior remain independently enforced. This is additional UI defense, not
a replacement for the device's transaction and boot contract checks.

## Deployment boundary

Private firmware images and any hardware trial are out of scope for this
source document. A real deployment must retain an independently verified
fallback bank, fresh off-device backups, optical registration, WAN service
and a separate approval for each disruptive operation.
