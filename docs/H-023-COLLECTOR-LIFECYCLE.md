# H-023: Controlled collector lifecycle and restart circuit breaker

**State:** offline source-only lifecycle qualification, November 3, 2026.
**No automatic startup, live PRX126 reads, deployed procd service, or
firmware-bank operations.**

## Purpose

H-021 samples PON and host Ethernet on independently selected intervals.
H-022 holds a genuine vendor-MIPS nixio/fcntl lock for a guarded collector
across cooperating OS processes. H-023 adds controlled lifecycle rules
for an eventual residential history service, so transient failures cannot
spawn overlapping collectors or consume unlimited CPU in restart loops.

The primary new module is:

    prototypes/history/8311/history_lifecycle.lua

It composes the existing H-022 guarded collector without changing the
rootfs overlay or running any native command by itself. The model has
**no timer, sleep, daemon, procd registration, LuCI endpoint, flash
writer, external alert transport or network client**. All transitions
are explicitly driven by a caller with monotonic observation time.

## Source-only API

    lifecycle.new(directory, preferences, capabilities, "offline_synthetic")
    lifecycle.start(handle, uptime)
    lifecycle.step(handle, uptime, read_only_provider)
    lifecycle.status(handle)
    lifecycle.history(handle, window, count)
    lifecycle.export_json(handle, window, count)
    lifecycle.stop(handle)
    lifecycle.shutdown(handle)

Creation never opens a lock, starts collection or schedules work.
Only a subsequent explicit start can acquire H-022's real kernel lock.
Only the literal offline_synthetic mode is admitted, and only with a
source-only, synthetic-qualified native profile and an explicitly
enabled source preference. This is **not a hardware qualification
token or production activation path**.

The lifecycle snapshots all scalar preference values on creation so
later mutation of the caller's settings table cannot change an
already-reviewed collector configuration.

### State transitions

| State | Meaning | Follow-up |
| --- | --- | --- |
| stopped | No owner, no automatic work | Manual start required |
| running | H-022 kernel owner retained | Manually tick H-021, or stop |
| cooldown | Guarded reader closed and lock released | A separate manual start after the prescribed interval |
| circuit_open | Restart budget exhausted | No further start in this session, including after stop |
| unsafe | A critical ownership/close/admission error | Fail closed, do not retry or claim the lock is safe |
| closed | Explicit shutdown | Create a new, separately reviewed session to operate again |

**No state transition creates an OS timer.** The return value only
reports the next permissible monotonic action time.

On native read failure, the underlying H-021 collector already backs off
15/30/60/120/300 seconds. H-023 tolerates three such failures. After
the **fourth consecutive failed observation**, it closes the guarded
collector and releases its kernel lock. An explicit start may resume after
a cooling interval of **60, 120 or 300 seconds** in that session.

After **four controlled restart cycles** the circuit breaker opens and
no further start is permitted. An ordinary stop operation does not reset
that breaker. Only a fresh, explicitly created session can begin a new
policy evaluation.

Contention with another kernel lock owner is treated separately from
a read failure. It does not start a native probe, it records a busy
admission and delays the next manual attempt. Repeated contention also
opens the circuit after a bounded number of denied starts.

Unsafe directory permissions or a failed release are terminal for the
current session. Do not automatically retry them, skip the kernel
lock, or claim that ownership succeeded.

### Stop, restart, and verified reboot

A normal stop closes the guarded collector before releasing the H-022
lock and clears future scheduling. A subsequent manual step while
stopped performs no native read.

A controlled restart starts with a new, bounded **volatile RAM history
ring**. This source module does not claim durable continuity across
collector restarts. H-015's independently qualified UBIFS checkpoint
adapter must be completed before persistence can be enabled.

During an actively running session, a decreasing ONU monotonic uptime
is accepted only when the existing H-021 reader independently verifies
a changed kernel boot identity. It resets both channel schedules and
counter baselines, and records a reboot observation. A lower uptime
with the same boot identity is rejected.

If the controller is in cooldown and the monotonic clock moves
backwards without independent evidence, it remains fail-closed.
An installed procd supervisor will require separately qualified
new-process/boot admission semantics. The present module does not
treat a caller-provided time reset as proof of reboot.

## Actual offline testing, not simulated lock ownership

Tests execute extracted vendor MIPS Lua with the actual vendor
nixio.so library under QEMU. They create root-owned 0700 private
test directories only and invoke a **fully synthetic read-only
provider**, not live PON, ethtool or filesystem reads from the ONU.

    AOTT_VENDOR_ROOTFS=/path/to/offline/rootfs \
      python3 -m unittest discover -s tests -p 'test_h023_lifecycle.py' -v

Source fixtures:

    tests/h023_lifecycle_fixture.lua
    tests/h023_process_fixture.lua

They cover:

- Source-only admission, disabled-by-default behavior, immutable
  preference snapshots and manually controlled startup.
- Due/early ticks with independently scheduled PON/host native calls
  supplied by an injected fake provider.
- Four consecutive reader failures, built-in backoff, guarded close,
  kernel lock release, explicit restart and fresh measured rates.
- Contention with an already-owned kernel lock, including 10 concurrent
  external processes, followed by reacquisition after owner shutdown.
- Clean exit without explicit close and **SIGKILL** of a holding process,
  followed by successful new ownership with the original lock inode.
- A monotonic time rewind refused without a changed boot identity;
  verified reboot creates a new epoch without combining counters.
- Circuit breaker after four restart cycles, no hidden timer,
  no automatic collector recreation after operator stop.
- Strictly no live shell probes, user identities, registered services,
  flash writes or network/notification delivery.

Public GitHub CI may not have the private extracted vendor rootfs. Its
source and Lua syntax tests still run; MIPS process tests must be
explicitly skipped there unless the offline rootfs is supplied.
The complete process/lock matrix is executed on the Hermes offline host
before publication.

## Deployment gates still unresolved

1. Authorize the PRX126 as a **direct** recoverable management target.
   Do not use Hermes as a covert path around the target allowlist.
2. Measure actual PON/ethtool timing, CPU/RAM, thermals, packet drops
   and management responsiveness under load.
3. The [H-024 offline wrapper and inert procd candidate](H-024-SUPERVISOR-OFFLINE-PROCESS.md)
   now test foreground process exit and graceful TERM/HUP/INT shutdown
   against the guarded source lifecycle. A **new, qualified production
   procd service**, actual PRX126 process/RAM limits and recovery
   behavior remain necessary before installation.
4. Verify supervisor exits release file locks and do not disturb
   subscriber forwarding after fiber loss or module reboot.
5. Add authenticated LuCI history/settings readback and independently
   verified H-015 flash durability only when relevant hardware gates
   pass. H-017 router-side Internet reachability remains separate.
6. Verify actual firmware A/B recovery before permitting automatic
   collection from the shipping firmware.

H-023 is an offline source and vendor ABI qualification, not a
production monitoring daemon. It makes **no** change to the active ONU,
ISP provisioning, firmware bank selector or released image.
