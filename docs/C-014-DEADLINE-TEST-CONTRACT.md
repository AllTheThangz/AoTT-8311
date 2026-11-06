# C-014: Confirmation-deadline test contract correction

**Checkpoint:** November 4, 2026. **Scope:** tests and documentation only. The transaction implementation, staging guard, Lua planner and deployable overlay are unchanged.

## Approved regression did not pass

The approval-bound combined host/vendor-MIPS/Chromium run of commit `ce99e3e8a2f6281da304fd3b02791edc1c9f4cc1`, tree `1e851dea2a188ae748da6687c6c9044bd308bfb3`, completed 982 tests with **one failure, zero errors and zero skips**, exit code 1, without a timeout. The failed test was `test_confirmation_after_deadline_rolls_back_instead`.

Original full-run log SHA-256: `ff811896a480fe4e441e89f7026443242f6f677a4ab7b431269a6c81c0fbccd4`.

The test requested a one-second confirmation lifetime, then asserted that apply must return pending before checking expiry. Instead it received `SOURCE_TXN_ROLLED_BACK`. The implementation already checks the deadline before returning from apply. Expiration during activation or its verification is a valid reason to restore the previous files immediately; the test must not assume that a very short real deadline always leaves time for a pending response.

The failed approved run and its log are preserved. It is not relabeled successful because a later focused test passes.

## Reproduction against the unchanged implementation

Using the existing synthetic apply fixture, a vendor-MIPS caller was paused after the second active-file replacement and released only after the real monotonic deadline had expired. The unchanged transaction core returned `SOURCE_TXN_ROLLED_BACK`, and both previous configuration files were restored byte-for-byte. The original mandatory-pending assertion would reject this correct result.

Transaction core SHA-256: `8ab1af27524c192d4c75e92af8594c03a75ef7166737033fe1c8145bea087472`.

This reproduces the recorded assertion outcome as an invalid test expectation. It does not establish that every possible rollback or timing defect is absent, and it is not physical hardware qualification.

## Corrected and extended tests

Confirmation boundary tests now first establish a pending transaction with a normal lifetime, then supply a controlled monotonic reading through a hook confined to the test fixture. They exercise the unchanged implementation immediately before the deadline, exactly at it, and after it. The earlier-before-boundary case may confirm; the equal/after cases must roll back.

A separate test retains the real monotonic clock and explicit apply barrier. It intentionally lets the deadline expire during apply and requires a verified, byte-identical rollback rather than a pending response. No real deadline check is removed or weakened in the implementation.

The existing real-time independent-worker test accepts either safe ordering: caller rollback when expiry occurs before apply returns, or worker rollback after a pending response. That is not a blanket acceptance of unavailable or failed operations. Both paths must finish rolled back with the original bytes. A new barrier-synchronized test separately requires the caller to return pending before releasing an independent worker at its controlled deadline; that worker must restore the same transaction. This ensures the worker-only path is actually exercised rather than hidden by early caller rollback.

The fixture clock hooks are not an API or production option. There is no change to transaction timeout bounds, health checks, confirmation consent, recovery ordering, file identity checks, error handling or publication permissions.

## Verified local results

- Corrected transaction suite: **44 tests passed, zero skips and zero failures**. This includes the existing 40 transaction tests and four new deadline/worker cases.
- Focused log SHA-256: `cb3aac39e960b72e7e97a0ec10c5ed739565c09af7f148813703c84429d8944d`.
- Repeatability: six deadline/worker scenarios were each executed three times, for **18 passing test executions**, zero errors or skips. These repetitions are not additional distinct tests.
- Repeatability log SHA-256: `644138a53bc0bb95f8c84be60175b867343b4761e7540f43ddd324a7351e5789`.

The focused command's transport response was interrupted. Its complete saved log was read independently, the matching test process was confirmed finished, and implementation/test hashes were checked. The repeatability run verified the changed test hashes before and after execution and completed with exit code zero.

The larger combined suite has not been rerun against this corrected tree. The earlier 942-test passing checkpoint and the 982-test failed run are historical evidence for their respective source revisions, not substitutes for the new full regression.

## Remaining boundary

A new full combined run requires a fresh target-issued approval bound to this corrected source revision. The previous approval was consumed by the original failed run. No approval is reused and no safety gate is bypassed.

Source publication remains unresolved. Neither the native components nor this test correction is installed on the ONU. No live configuration, credentials, management interface, HTTPS service, ISP provisioning, firmware bank or boot selector was accessed or changed. The deployable overlay and manifest remain unchanged at 83 entries.
