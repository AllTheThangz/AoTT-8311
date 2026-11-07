# C-014: Single-owner, single-use native staging workspace

**Checkpoint:** November 4, 2026. **State:** local source candidate. No live configuration, firmware overlay or production startup changes.

## What this adds

The Lua transition core can now be executed through `prototypes/configuration/8311/vlan_stage_guard.lua`. The guard holds one real nonblocking kernel fcntl lock across the candidate's initial state check, UCI mutations, package commits and persisted-file verification. Competing cooperating processes using the same workspace are refused before they call the native adapter.

The only accepted paths are root-owned private synthetic test workspaces with a fixed prefix and 16 hexadecimal characters under `/var/tmp`. Production paths and modes are refused. This is an executable native staging prototype, not a newly installed daemon, LuCI route, network reload or firmware operation.

## Ownership and operation boundaries

The lock file is an empty root-owned, single-link regular file with mode 0600 in a root-owned mode-0700 workspace. It is held by a private file descriptor and is never unlinked by the guard. Recursive acquisition is rejected before opening a second descriptor, avoiding accidental loss of a POSIX process lock when another descriptor is closed. The originating process identity, directory inode, lock inode, ownership and modes are checked during the guarded operation.

The adapter must be explicitly disposable and bound to the same workspace. Nested staging or an attempt to release the owner from inside an active callback is refused. Every callback has a before/after guard check. A failed core call is also rechecked, so an adapter exception does not mask a lost directory or lock identity. Unexpected adapter errors are not echoed.

The extracted nixio interface does not supply the same open-at/no-follow facilities as a new hardened filesystem service. The implementation relies on a separately provisioned, trusted root-owned workspace and checks identities around access. It does not claim to defeat a malicious privileged process, a rogue adapter, or an unrelated UCI writer that ignores this advisory lock. A production adapter and writer-coordination policy remain necessary.

## Single-use state markers

Before any candidate operation, the guard creates, synchronizes, atomically installs and reads back a fixed **pending** marker. The marker contains only a format label and state, never configuration values, identifiers, password material or a copy of the plan.

Only after the transition core has independently verified the persisted candidate does the guard install a **validated** marker, with a file sync, rename, directory sync and exact readback. If the initial marker write fails, no candidate mutations begin. If completion-marker writing fails, the candidate is not reported as successfully validated.

Any existing final or partial marker causes a later acquisition to refuse the workspace. This applies to pending, malformed and validated markers and to symlinked marker paths. Markers are not trusted to authorize a restart, and neither they nor the stable lock file are automatically deleted. Kernel lock release after a crash therefore does not silently allow a partially changed candidate to resume.

A successful candidate is also single-use. A fresh staging attempt requires a separately created workspace. Even a no-op transition consumes the guard's workspace and writes its state markers, although the Lua core issues zero UCI mutations or commits for that no-op. The marker is not a signed integrity receipt or evidence that an old candidate remains unchanged after validation; no API promotes or trusts it for live activation.

## Actual native integration and failure tests

`tests/c014_locked_staging_fixture.lua` composes the guard with the preceding Lua planner and execution core. It uses the extracted vendor MIPS Lua runtime and actual vendor UCI executable, limited to unpredictably named synthetic packages. Retained source configuration files are checked byte-for-byte after each test. The test adapter still validates its private candidate files and performs independent no-delta persisted-file reads.

`tests/test_c014_locked_staging.py` adds 31 tests covering actual kernel-lock contention, recursive ownership, native UCI execution, and deterministic interruption at explicit process barriers. Twelve contender requests, scheduled across up to six concurrent workers, are refused before native UCI access while another process owns the workspace.

Crash tests terminate the owner before staging, after the pending marker, after the first mutation, after persisted readback and after the completion marker. A pre-staging crash releases the unused workspace; every started or completed workspace remains blocked. Native mutation and package-commit failures, stale plans and incorrect persisted readback also leave an untrusted pending candidate rather than a success marker.

Further tests change lock or directory identities and permissions, alter the marker during execution, inject marker sync/rename failures, supply incorrect ownership, hard links, symlinks or a FIFO, and attempt a mismatched adapter or nested close. These cases must stop without further candidate mutations and without exposing private error text. Refusal is tested alongside successful staging so that an implementation rejecting every operation cannot pass.

The initial tamper tests exposed an error-reporting gap: the adapter refused the operation but its exception could mask the exact ownership-loss cause. The guard now performs the ownership/marker check after a failed core call as well. All original refusal protections remain in place.

## Integrated apply/recovery follow-up

The [native apply, confirm and recovery workflow](C-014-APPLY-CONFIRM-RECOVERY.md) now composes this guard with the same Lua planner and actual UCI candidate. It retains verified previous/candidate files, journals before synthetic activation, and exercises independent confirmation and deadline-driven recovery. This is not an installed network-reload or production recovery service.

## Limits and next gate

These tests exercise real Linux processes and vendor-MIPS code on Hermes, not the physical ONU. File sync and process-kill tests do not prove NAND/UBIFS power-loss behavior. A failed candidate may be partially modified and must be discarded; this is not rollback of a live network, a two-package atomic promotion transaction, an encrypted recovery archive or an independent watchdog.

Next work remains a protected native staging adapter and separately qualified activation/recovery protocol, followed by physical persistence, alternate-management and subscriber-forwarding acceptance. The management-VLAN control remains hidden. No live ONU, ISP provisioning, credential, HTTPS service, management route, firmware bank or boot selector is accessed by this change.

## Validation checkpoint

The complete affected C-014 suite passed **86 tests, zero skips and zero failures**, comprising the previous 55 C-014 tests and 31 new staging-guard tests. Failure-injection subcases and competing requests are included in those tests, not added to the distinct test count. All new code hashes were recorded before the run and verified unchanged afterward.

Affected-suite log SHA-256: `bb7164f652716b67ad6de57bab1bd520e60869a13b492e9ebb5d55e16ef92e47`.

The subsequently approved full combined run of locked-staging commit `745d0267bc1eeefd330f2edd5612d6e54037964f` passed **942 tests, zero skips and zero failures**, with exit code 0 and no timeout. Its log SHA-256 is `1af51abc4af98fd2f500aa5f94379c5ed9fafc66e394c184fb58f2cb5c0d9acf`. That result belongs to this locked-staging checkpoint, not the later apply/confirm/recovery integration. The deployable firmware overlay and manifest remain unchanged at 83 entries.

Source publication remains pending from the preceding checkpoint; no alternate upload route is used. The guard and its parent Lua core remain local until publication can proceed normally. The deployable firmware overlay and manifest stay unchanged at 83 entries.
