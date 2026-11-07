# C-014: Bounded native recovery-worker supervision and restart

**Checkpoint:** November 4, 2026, Eastern time. **Scope:** local source integration on disposable synthetic configuration copies. Not installed on the ONU.

## Integration milestone

`prototypes/configuration/8311/recovery_supervisor.lua` supervises the existing native `recovery_admission` worker and `vlan_transaction` recovery implementation. It does not recreate the rollback algorithm or invoke a caller-supplied shell command. The native parent forks its own worker, verifies that readiness belongs to that exact child process incarnation, and monitors both process state and admission health.

A killed worker is replaced without the test harness manually launching a successor. A stopped or stale-heartbeat worker is terminated and reaped before a replacement is started. The new worker obtains a fresh recovery epoch and uses the existing journal and acknowledgement protocol; an old apply proof does not transfer to it.

The accompanying tests exercise actual extracted vendor-MIPS Lua processes, nixio locks, UCI candidate preparation, and the existing persisted-file rollback path. They do not contact the production ONU or apply a real network configuration.

## Bounded lifecycle

A separate stable `recovery.supervisor.lock` prevents duplicate supervisors in a workspace. Recursive entry is rejected before another descriptor can be opened. The worker closes its inherited supervisor-lock descriptor and runs at lower process priority. Only unreaped direct children are signalled, so the supervisor does not kill an unrelated process merely because a numeric PID is reused or appears in a file.

The supervisor retains a canonical, synchronized launch record with boot identity, initial monotonic time, fixed session deadline, launch count and phase. A session allows at most four worker launches, meaning one initial launch and at most three automatic restarts. Increasing minimum launch spacing is enforced using the prior launch timestamp. Neither a supervisor restart nor a worker restart resets the retained deadline or launch budget.

An interrupted, malformed, altered, exhausted or completed launch record is not silently reset. A changed record during an owned session is rejected. When trusted ownership still permits it, a fatal supervised failure attempts the existing verified restoration rather than simply abandoning a pending change. This does not authorize blind recovery when directory, lock, journal or backup validation fails.

A caller can request a checked stop using a fixed, root-only record. The worker first releases its admission ownership and attempts recovery; the supervisor allows a bounded drain period and then escalates termination of its own child if necessary. Final restoration and terminal state are verified through the transaction implementation.

## Parent loss and shutdown

The extracted vendor nixio signal API accepts default/ignore dispositions, not Lua callback functions. The implementation does not pretend that a Lua signal handler exists. Cooperative shutdown uses the validated stop request. Unexpected supervisor termination or suspension is detected by the worker through its parent PID and process-leader incarnation/state; the worker revokes its admission and attempts bounded recovery before exiting.

Tests verify restoration after the supervisor receives SIGKILL or SIGTERM and after the supervisor is suspended. They also kill both caller and worker after the first package replacement while leaving the supervisor alive; the automatically launched replacement restores the previous configuration pair.

If both the supervisor and worker die, this component cannot launch itself. An external restart is still necessary. A separately restarted supervisor resumes the existing finite launch budget rather than receiving a new one. If the session is expired, exhausted, unsafe or partially recorded, it refuses automatic restart and requires explicit recovery/inspection.

## Terminal-state handoff

The transaction caller may write a confirmed or rolled-back marker before releasing its transaction lock. A worker can observe that marker and exit while the caller still holds the lock. The supervisor must wait for this legitimate handoff instead of reporting failure or launching another worker. A deterministic barrier test holds the confirmation caller at that point and verifies the supervisor waits and later checks the completed state.

The supervisor never treats a terminal label alone as proof of intact active files. It uses the transaction's verified recovery/terminal-state path before reporting completion. Explicitly confirmed candidate files remain in place; unconfirmed pending changes are restored when shutdown, expiry or recovery requires it.

## Security and scope boundaries

Only exact private synthetic transaction paths and the `offline_synthetic` mode are accepted. Directory and lock identity, ownership, modes, regular-file type, link count and bounded record sizes are checked. Stop and lifecycle metadata contain no configuration values, credentials, addresses or package contents. Unsafe symlinks, hard links, FIFOs, modes, malformed records and unexpected record changes are refused.

The new admission helper `matches_process` checks a supervisor's private proof against the expected child PID and leader start identity without disclosing those fields or changing ownership. A valid proof for another process does not satisfy this check.

These controls assume trusted, cooperating root-owned code and private workspaces. They are not protection against a malicious privileged process. The existing vendor filesystem interface does not establish modern open-at/no-follow isolation, and these development-host tests do not establish NAND/UBIFS power-loss behavior.

The session is explicitly bounded and initially low priority, but physical ONU CPU, memory, descriptor usage and sustained-load behavior remain unqualified. The supervisor is not an installed procd/boot service or a guarantee that all simultaneous process failures recover without an external service manager.

## Focused verification

The final focused run passed **56 distinct tests, zero failures, zero errors and zero skips**:

- 30 new supervisor tests covering automatic restart, restart limits, retained budgets, parent loss, stop/drain, lock handoff, child identity, duplicate ownership, private descriptor closure, unsafe records and integrated recovery.
- 26 existing admission tests against the updated admission module, including process/lifetime evidence and transaction-specific acknowledgement checks.

The test source hashes were captured before execution and verified afterward. Saved receipts enumerate the distinct test IDs. The tool transport returned an error and left two complete passing run records; both are retained, but the test count is **56**, not doubled. The final saved log, receipt and source hashes were independently reread. No matching focused test process remained active.

Selected focused-run log SHA-256: `5972525540fd09d79fb42f2b1aaa2c2c56d236136ca56578e42acaddef23dfa7`.

Consolidated focused-receipt SHA-256: `5e3a1a1c0b8c0ca298099d41c0860a0439a2e32bfda9da03b07347a6f4b6e365`.

```sh
AOTT_VENDOR_ROOTFS=/path/to/private/vendor/rootfs \
  python3 -m unittest discover -s tests -p 'test_c014_recovery_*.py' -v
```

## Subsequent completed regression and storage follow-up

This supervisor checkpoint (`0c15e114392b49c622765518469bd5514ec5358d`) subsequently passed its approved full regression: **1,042 tests**, zero failures, errors or skips, exit code 0, without timeout. Its saved log SHA-256 is `f22cd6429fe065be25cd90eca767d2a46a39341f51607cced89e044c287f2fca`. All 351 tracked files and executable modes were independently checked afterward.

The [protected-storage and boot-order follow-up](C-014-PROTECTED-STORAGE-BOOT.md) strengthens retained-file admission and identifies early/late configuration consumers that must be reconciled before device installation. The current native supervisor implementation is unchanged; a process-observation test race was corrected without altering runtime supervision. The parent's 1,042-test result does not certify the follow-up tree.

## Next gate and remaining work

At this document's original focused-test checkpoint, a source-pinned combined host/vendor-MIPS/Chromium regression had not run. The subsequently completed result is recorded above. The prior 1,012-test full pass belongs to admission commit `9770eeaa47807a72b15e1edeeacb40f53e1366f6`, not this supervision revision. A fresh target-issued approval is required for the new full run.

Publication remains blocked from the preceding checkpoint. No alternate upload route is used. The new supervisor and prior native components remain local and undeployed. The deployable firmware overlay and manifest stay unchanged at 83 entries.

Production service installation and boot recovery, protected configuration backups, actual service/health hooks, authenticated GUI integration, hardware persistence and management/forwarding acceptance remain open. No actual ONU settings, credentials, management interface, HTTPS service, ISP provisioning, firmware bank or boot selector were accessed or changed by this work.
