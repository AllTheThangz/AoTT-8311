# AoTT-8311 V3r4: Interrupted transaction recovery

Status: **development source only**, not installed or hardware-qualified. The reference PRX126 ONU remains on committed V3r3.

## Boot configuration crash-consistency

Previously, a failed trial-staging write could invoke restoration and then delete the persistent recovery plan **even if restoration was not verified**. A process crash before stage completion could also leave a candidate value in boot environment with the same `prepared` marker used for a legitimately verified trial.

The corrected boot configuration path uses a two-phase persisted plan:

1. `preparing`: backup is durable before any candidate writes. The candidate is not authorized for boot.
2. `prepared`: entered only after **all candidate fields have been read back and verified**. The existing one-boot trial, timed confirmation and rollback behavior remain in effect.

On restart, a `preparing` plan always invokes restoration of prior startup values, including the original boot command. It records the restored state and requires a recovery reboot; it never enters a trial, even if an interrupted write happened to leave all requested candidate bytes in place.

If staging fails, restoration attempts run across the entire prior snapshot. The persistent plan is disarmed **only** after restoration and readback both pass. If restoration or disarm fails, a durable recovery obligation remains visible and a separate failure code is reported. Native environment setter exceptions and unreadable getter results are converted into failure, without disclosing raw exception strings. Status explicitly marks `recovery_required` for incomplete preparation.

## Guarded management transaction

All calls to the management confirmation/verification wait callback are now protected. A callback exception after the recovery marker is armed immediately initiates the normal restore pathway. The rollback receipt is considered verified only if the native restoration adapter supplies `runtime_verified=true`; a successful import/reload alone is not proof of the original running management connectivity.

## Offline fault injection

The new `v3_boot_config_crash_fixture.lua` executes synthetic power-loss conditions, partial writes, post-write setter exceptions, failed restoration, marker cleanup failure and phase-promotion errors with memory-only firmware environment / recovery-store mocks. It explicitly proves that interrupted preparations do not become accepted trials and verifies boot entry restores the old boot variables.

The existing guarded management transaction fixture now injects failures into the wait callback during verification and confirmation, and tests that a missing runtime-restoration proof cannot yield a successful rollback result. Tests run on host Lua 5.1 and vendor MIPS Lua through QEMU. No physical ONU writes occur.

## Qualification

Source tests and byte-reproducible offline builds are prerequisites. Hardware staging, reboots, network interruption/fault injection and verification on a recoverable spare ONU remain separate operations requiring specific authorization. This source change does **not** authorize a live flash or any change to the running V3r3 ONU. The maintainer waived the seven-day soak after the successful 24-hour V3r3 baseline; that waiver does not qualify new V3r4 functionality.
