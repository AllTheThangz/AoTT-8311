# C-014: Mandatory independent recovery-worker admission

**Checkpoint:** November 4, 2026. **Scope:** native Lua integration on disposable synthetic files. Not deployed to an ONU.

## Closed integration gap

The prior transaction could prepare and activate a candidate without requiring an independent recovery process to be present. Its worker was tested, but worker readiness was not a condition of activation. The new `8311.recovery_admission` module is now called by the existing `vlan_transaction.begin` and `confirm` paths. There is no alternate public begin method that skips admission.

A missing, dead, stopped or unresponsive worker cannot authorize activation. The initial presence check happens before staging or backup copies. After staging, the pending journal is synchronized and the worker must acknowledge that exact transaction before either active fixture package is replaced. A worker-loss check occurs before each replacement and again after applied-readback/health checks. Loss detected while the caller still runs invokes the existing restoration path.

Confirmation needs a fresh acknowledgement even when an earlier acknowledgement authorized apply. A previously issued apply acknowledgement is not reusable as a confirmation response. Recovery itself does not require an available worker: an explicit independent recovery call must remain usable when the worker has failed.

## Independent process and private metadata

A worker owns a stable, root-owned, mode-0600 regular lock file in the existing private mode-0700 transaction workspace. The lock is a real nonblocking kernel fcntl lock. Recursive acquisition and same-process attestation are rejected before opening another descriptor for the owner inode. The lock is never unlinked.

Readiness combines the held kernel lock, a random worker epoch, process ID and leader start-time identity, boot identity, recent monotonic heartbeat and bounded worker lifetime. A probe also verifies the workspace and lock inode. An unlocked file, a leftover readiness record or a live PID by itself is insufficient evidence. Suspended and zombie processes are not accepted.

The process identity check uses `/proc/PID/task/PID/stat`. During extracted-vendor/QEMU testing, the self-stat view occasionally reported a start tick different from the leader viewed by a second process. Using the explicit thread-group leader path made both processes compare the same incarnation. This is an observed emulation constraint, not a claim about a fault on the physical ONU.

Readiness, request and acknowledgement files are bounded, canonical and root-only. They contain no package values, addresses, credentials or backup contents. The application does not accept a caller-provided readiness boolean or caller-supplied worker epoch as proof; proof handles retain their comparison state privately in the module.

## Transaction-specific acknowledgement

The transaction caller sends a fresh random challenge bound to the worker epoch, transaction ID, boot and confirmation deadline. The independent worker reads the existing atomic transaction journal and acknowledges only a matching pending transaction. It also refuses coverage that extends beyond its declared lifetime, including the recovery margin.

The caller checks the acknowledgement, current heartbeat, process identity and kernel ownership again. A replacement worker cannot silently inherit an in-flight apply proof. A replacement may take responsibility for an already-pending transaction only through a new handshake, such as a later confirmation request or ordinary independent recovery.

Atomic metadata replacement can intersect a reader. A small bounded retry handles only an explicitly detected inode replacement; malformed records, unsafe ownership/permissions, missing owners and unrelated errors are not converted into success. Request and acknowledgement checks remain exact.

## Worker lifecycle and recovery integration

The test worker is a separate vendor-MIPS Lua process. Its normal loop refreshes readiness, handles transaction challenges and calls the existing recovery implementation when the journal is due or already rolling back. Terminal journal decisions are observed without taking the transaction lock simply to emit a duplicate success receipt. This avoids unnecessary contention after another caller has already confirmed or restored the files.

The normal transaction fixtures now start this real independent worker before a permitted begin. Tests that deliberately interrupt the explicit manual-recovery caller stop the background worker first; otherwise the worker could legitimately finish recovery before the requested manual fault point. Automatic-worker tests leave the worker running and separately verify that path.

Clock boundary hooks remain confined to the transaction test fixture. They do not fabricate heartbeat freshness or change the admission module's process-liveness clock.

## Failures found during development

The first integration version reused the apply acknowledgement for confirmation. Once confirmation occurred in a later monotonic tick, the old acknowledgement could not satisfy the new freshness requirement. The protocol now uses a fresh challenge for each arm operation and requires its exact response.

Initial broad tests also exposed the process-incarnation discrepancy described above and contention caused by a recovery worker unnecessarily revalidating already-terminal state. These were investigated from the returned errors, not hidden by accepting arbitrary refusals. The corrected focused suites retain success-path expectations and explicit failure checks.

## Test coverage

The new admission suite has **26 distinct tests**. It covers absent/dead/stopped workers, nonresponsive workers, missing deadline coverage, stale/future/wrong-boot heartbeat data, changed process incarnation, unsafe metadata and links, replaced lock inodes, same-process and duplicate ownership refusal, a tampered acknowledgement, and old-acknowledgement replay.

Integration tests also terminate the worker before activation, between the two package replacements, after both replacements, and before confirmation. They verify restoration of the original pair. Separate tests cover rejection of an in-flight proof after worker replacement, a fresh confirmation handshake with a replacement worker, and recovery by a separately restarted worker after both the original caller and worker were killed.

The existing **44 transaction tests** continue to pass with mandatory admission enabled. Together these are **70 distinct focused tests**, not a complete project-wide regression. The earlier tests were rerun in bounded groups; repeated development executions are not added to this distinct-test count.

```sh
AOTT_VENDOR_ROOTFS=/path/to/private/vendor/rootfs \
  python3 -m unittest discover -s tests -p 'test_c014_recovery_admission.py' -v
AOTT_VENDOR_ROOTFS=/path/to/private/vendor/rootfs \
  python3 -m unittest discover -s tests -p 'test_c014_apply_recovery.py' -v
```

## Native supervision follow-up

The [native recovery-supervision integration](C-014-RECOVERY-SUPERVISION.md) now forks and monitors this worker, restarts failed or unhealthy children within a retained finite launch budget, and exercises recovery after parent loss. The supervisor verifies that an admission proof belongs to its own child. This replaces manual worker replacement in the new supervision tests, but it is not an installed boot/procd service.

## Limits that remain

Readiness is a checked condition at admission and operation boundaries, not a promise that a process can never fail immediately afterward. If both caller and worker die, a separately restarted worker or operator recovery is still needed. The restart test supplies that replacement explicitly; it does not prove an installed supervisor will do so.

The lock protocol assumes cooperating trusted code and private root-owned directories. A malicious privileged writer or an arbitrary replacement implementation can subvert those assumptions. The protocol is not remote attestation or authentication against a root attacker.

The worker loop and activation/health hooks remain development fixtures, not installed boot/procd services. Native supervision/restart, resource/load qualification, protected production backups, authenticated GUI integration, real service activation and independent physical management/forwarding/power-loss testing remain open. A bounded worker must not be advertised as an always-running production watchdog.

No live ONU, ISP provisioning, credentials, management interface, HTTPS service, firmware bank or boot selector was accessed or changed. The deployable overlay and manifest remain unchanged at 83 entries. Source publication is still pending from the earlier checkpoint.

## Validation checkpoint

Focused pass evidence identifies all **70 distinct test IDs** across the two affected modules, with no missing or duplicate cases. Saved log hashes and the final code hashes were verified independently. The combined focused-receipt SHA-256 is `6a0a82e5a568ccde2a228c2379680cff848244bb25f04e4d4ad6200a3ccf25be`. The logs are retained privately; they are not source files or firmware contents. The parent 986-test full run applies only to commit `d3b9e85b8695d16e86425c936a2e8c3797ed09f7`, not this new admission implementation. A new source-pinned combined host/vendor/browser run has not yet been performed and requires its own target-issued approval.

## Subsequently completed admission regression

The admission parent `9770eeaa47807a72b15e1edeeacb40f53e1366f6` completed its approved combined host/vendor-MIPS/Chromium regression: **1,012 tests passed, zero failures, errors or skips**, exit code 0, without timeout. Its saved log SHA-256 is `9d724f18bc6395722d2c51eb1845f4700d3ef1490573ec3e360ab2089583d814`. The result and tracked-file hashes were independently checked after completion.

That full result does not cover the later supervisor changes. The new supervision/admission focused suite passes 56 distinct tests, while a fresh combined regression for its source revision is still pending. Both versions remain local source, not installed firmware.
