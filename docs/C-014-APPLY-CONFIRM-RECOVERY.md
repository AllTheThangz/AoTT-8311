# C-014: Integrated native staging, apply, confirmation and recovery

**Checkpoint:** November 4, 2026. **Scope:** disposable synthetic configuration files on the development host. No on-device installation or actual network activation.

## Integration rather than another isolated save model

`prototypes/configuration/8311/vlan_transaction.lua` composes the existing Lua transition planner and single-owner staging guard into one transaction. The same candidate that passes native UCI staging and persisted-file checks is retained, applied to a separate synthetic active directory, then explicitly confirmed or restored by an independent process. The Python journal prototype is not substituted for native execution.

The accepted transaction and staging roots have separate exact `/var/tmp` fixture prefixes with unpredictable suffixes. Both active configuration files have generated synthetic package names, not the host's or ONU's actual `network` and `firewall` packages. Production paths and modes are rejected. The only real mutations are private test files.

## Ordered transaction

1. Read and hash both active fixture packages under a stable kernel fcntl lock. A private preview revision binds the operation to those exact bytes; stale previews are refused.
2. Check the native source snapshot, take the existing staging-owner lock and prepare the reviewed Lua plan. Retain synchronized, verified previous-file copies before staging.
3. Execute the real guarded UCI candidate transition. Read both persisted candidate files while the staging handle is still valid and compare their parsed contents to the reviewed plan. Retain synchronized candidate copies and hashes, then recheck that the active source did not change.
4. Write a canonical pending recovery journal before replacing either active file. It records a transaction identifier, boot identity, monotonic confirmation deadline and before/after SHA-256 values for both files.
5. Replace the two synthetic active files one at a time using bounded private scratch files, file sync, rename, directory sync and readback. This is explicitly **not an atomic two-file replacement**. A pending journal makes an interrupted mixture recoverable rather than treating it as success.
6. Check the applied native UCI readback and the synthetic activation hook. Failed activation/readback immediately attempts restoration. A successful apply stays pending; it never confirms itself.
7. A separate confirmation operation must name the exact transaction, carry explicit operator consent and receive positive, transaction-bound synthetic health/recovery observations from its trusted adapter. It rechecks both active files and the deadline before recording confirmed state.
8. An independent recovery process restores both previous packages unless the transaction was explicitly confirmed. A due-only recovery worker waits until the monotonic deadline, or recovers immediately after a changed boot identity, a backwards monotonic clock, or a previously started rollback.

Neither the activation hook nor the health adapter restarts a service or tests real Internet reachability in these fixtures. Their outcomes are deliberately synthetic and must not be confused with hardware acceptance.

## Independent recovery and crash behavior

The test recovery worker is a separate vendor-MIPS Lua process. It can be started before the caller and continues after the staging/apply caller exits. It polls a bounded number of times, uses the same transaction lock, and invokes the actual native recovery code; it does not need the browser or the original process's memory.

Before restoring anything, recovery validates the journal, both backup hashes, both retained candidate hashes and both current active files. Each active file must match its recorded previous or candidate content. Unknown changes, missing/unsafe files or corrupted backups cause refusal without blind overwriting.

A rollback decision is made durable before restoring the first file. Interruption between restoration steps leaves a rolling-back record that another process can resume. A completed rollback is idempotent. A confirmed transaction is retained, but later changes to its files are reported rather than silently repaired. Previous and candidate files and the journal are retained; the workspace cannot start a second transaction.

Only fixed replacement scratch files may be discarded and recreated after interruption, and only after regular-file, ownership, mode and single-link checks. They are never used as a backup source. Symlinked or otherwise unsafe scratch files are refused and not removed. No recovery operation deletes the stable lock or a retained source backup.

Crashes before a pending journal leave active files unchanged and the partially prepared workspace quarantined. A transaction without an armed recovery journal is not guessed into a recoverable or successful state.

## Native dependencies and privacy

The transaction executes in the extracted vendor Lua 5.1 runtime and uses its nixio filesystem/process-lock functionality. The vendor image lacks the tested optional `nixio.crypto` module, so hashing uses the already present SHA-256 utility. In the test fixture, digest calls are redirected to the actual vendor BusyBox SHA-256 applet under QEMU, not a substitute Python hash in the transaction path. Test orchestration separately verifies bytes using host Python.

The journal is bounded and canonical; duplicate or extra records and unsupported phases fail closed. Its hashes detect accidental corruption but are not a MAC or signature against a privileged attacker. Configuration copies are plaintext, mode 0600, in a trusted mode-0700 fixture and contain synthetic data only. **This is not an encrypted production backup implementation.**

Transaction result receipts omit package values, addresses, package filenames and backup hashes. The private preview revision and on-disk journal are internal synchronization evidence, not public telemetry or support export formats. Raw adapter exception text is not returned.

The lock is advisory. Identity and mode checks assume trusted root-owned fixture directories and cooperating writers. They do not defeat malicious privileged modification or supply modern open-at/no-follow guarantees absent from the existing native filesystem layer.

## Tests

The new suite contains 40 distinct tests against real vendor-MIPS Lua and vendor UCI, covering:

- Complete staged apply, explicit confirmation, byte-identical rollback and repeat recovery.
- A separate timer-driven recovery process after the original caller has exited, expired confirmation, changed boot identity and backwards monotonic time.
- Failed synthetic activation/health checks and probe exceptions, wrong transaction IDs, missing consent, stale preview and unsupported inputs.
- Process exits after backup/candidate creation, pending-journal installation and each active-file replacement; independent recovery restores or safely refuses the appropriate state.
- Interruption during each rollback step and before/after the confirmation marker, including partially written scratch files.
- Native replacement failure during apply or recovery, corrupted backups/candidates/journals, unknown active content, and modified confirmed/restored files.
- Kernel lock contention with independent processes, recursive calls, wrong modes, symlinks/hard links and unsafe replacement scratch files.
- Pending/confirmation-journal sync failures, active-directory sync failures, confirmation-deadline rechecking after a health probe and absence of the second required backup.
- Unchanged retained source files and result receipts that do not disclose configuration contents.

The added sync-failure tests first exposed an incomplete test file-descriptor wrapper: the vendor file helper calls `readall`, which the wrapper did not forward. Adding that passthrough corrected the test injection without changing the transaction implementation. The corrected sync-failure cases then passed.

Failure-injection subcases and contender requests are not counted as extra distinct tests. File replacement and kill tests establish process-crash behavior on the development host, not NAND/UBIFS power-loss guarantees.

```sh
AOTT_VENDOR_ROOTFS=/path/to/private/vendor/rootfs \
  python3 -m unittest discover -s tests -p 'test_c014_apply_recovery.py' -v
```

## Still required for actual use

At the original checkpoint, the recovery loop was a tested fixture worker whose presence was not enforced by apply. The [mandatory recovery-worker admission follow-up](C-014-RECOVERY-WORKER-ADMISSION.md) now requires independent live ownership and an exact transaction acknowledgement before synthetic activation. It remains a development worker, not an installed boot-time/procd recovery service. Actual network/service activation hooks, independent management and forwarding probes, a protected on-device backup store, coordination with other native writers, authentication/session integration and watchdog startup/restart behavior remain open.

Physical persistence, alternate management access, host VLAN behavior, subscriber forwarding and real outage/power-loss recovery need separate hardware qualification. The hidden VLAN control remains disabled. This source does not authorize service reloads, live address changes, firmware staging, reboot or permanent bank commitment.

The existing publication blocker remains separate and unresolved. No alternate source-upload path is used. The native components remain local; only progress and test receipts may be recorded in the existing project discussion.

## Validation checkpoint

The completed affected C-014 suite passed **126 tests, zero skips and zero failures**: the previous 86 C-014 tests and 40 new transaction tests. All new code hashes were recorded before and verified unchanged after the run. The command transport response was interrupted; the matching test process was observed to finish, and its final saved log and source hashes were independently verified rather than assuming completion from the transport error.

Final affected-suite log SHA-256: `6f48a9537b7a3d79d136dc62086301cc0c98e0cc7c5a60524e37b3882ace8512`.

Source disclosure and manifest audits pass across 344 local files. The prior full **942-test** result belongs to locked-staging commit `745d0267bc1eeefd330f2edd5612d6e54037964f`, not this new transaction tree. At this initial affected-suite checkpoint, the new full combined host/vendor/browser run had not started. The subsequent approval-bound result is recorded below. The deployable overlay and manifest remain unchanged at 83 entries.

## Subsequent full-regression result and test correction

The approved full run of `ce99e3e8a2f6281da304fd3b02791edc1c9f4cc1` completed **982 tests with one failure, zero errors and zero skips**, exit code 1, without timeout. The failing deadline test assumed that a one-second lifetime must permit an intermediate pending response. A controlled reproduction showed that expiry during apply correctly restores both prior files before returning.

The [deadline-test contract correction](C-014-DEADLINE-TEST-CONTRACT.md) changes tests and documentation only, leaving this transaction implementation unchanged. The corrected 44-test transaction suite and 18 repeated boundary/worker executions pass. The failed full-run receipt is retained, and a fresh full regression of the corrected revision is still required. This is not a full-suite acceptance or a deployment.

## Verified parent regression and current follow-up

The corrected deadline-contract parent `d3b9e85b8695d16e86425c936a2e8c3797ed09f7` subsequently passed its approved full regression: **986 tests, zero failures, zero errors and zero skips**, exit code 0 and no timeout. The saved log hash is `87f672b398642c7ba3f1ef6dda56609225d50122ea6b8978a74a8ab68ebd4fc8`. The original failed 982-test receipt is preserved separately.

The new mandatory worker-admission integration changes runtime source beyond that parent and therefore needs a new combined regression. Its 70 focused transaction/admission tests pass, but the parent's 986-test success is not claimed for the new tree. No physical configuration or firmware has been installed.
