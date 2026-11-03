# H-024: Source-only foreground supervisor and safe process termination

**Date:** 2026-11-03. **State:** Offline process and vendor-MIPS ABI
qualification only. Not installed, activated, or hardware qualified.

## Goal

H-021 supplies independent-cadence observations, H-022 supplies actual
vendor-nixio kernel locking, and H-023 supplies bounded failure recovery.
H-024 verifies the foreground process boundary needed before these could
become a lightweight residential service: avoid duplicate workers,
handle termination gracefully, protect resources and never leave an
orphaned collector polling native interfaces.

The firmware already includes OpenWrt procd. Some existing firmware
services use a respawn retry count of zero, which OpenWrt defines as
unlimited. Do not adopt that for new monitoring. The H-024 candidate
defines no procd respawn and relies on the H-023 finite circuit breaker
in a future qualified runtime.

## Source-only components

- prototypes/supervisor/h024_wrapper.sh: offline shell parent which
  validates source paths, lowers the worker's scheduling priority,
  applies process limits and manages signal shutdown.
- prototypes/supervisor/h024_worker.lua: extracted vendor MIPS Lua
  foreground process which uses the actual H-023, H-022 and H-021
  source modules with a fixed synthetic PON/Ethernet test provider.
- prototypes/supervisor/8311-history.init-candidate: deliberately inert
  procd configuration. Even if evaluated, start_service only registers
  an error and never starts an instance or sets respawn.
- tests/test_h024_offline_supervisor.py: real OS-process and SIGTERM,
  SIGHUP, SIGINT and SIGKILL tests with actual vendor nixio under QEMU.

No file is in the deployable rootfs overlay, no procd service is enabled,
and the native PON commands in the source fixtures are *never executed*.

## Shutdown and crash semantics

The parent launches one foreground child which must acquire the stable
H-022 lock and start the H-023 lifecycle. A signal to the wrapper
creates a private per-parent stop request in its root-owned 0700
runtime directory. The child detects this promptly, calls the
lifecycle shutdown and releases the kernel lock. The wrapper waits up
to five seconds for cooperative exit, then escalates to TERM and KILL
if necessary and cleans up its stop request.

If the parent is killed, the child detects that its parent PID changed
and closes its H-023 lifecycle independently. A killed child does not
cause the wrapper to start another. The stable collector.lock inode
is never deleted. Another wrapper cannot launch a competing collector
while the first holds its kernel lock.

The actual PRX126 process supervisor, kernel and signal behavior have
not yet been verified. A real procd service must not be derived from
this source without separate qualification.

## Resource controls and limitations

The offline parent applies nice +10, a 32-file-descriptor limit and
a core-dump limit of zero. Tests inspect the actual QEMU child process
priority and Linux process limits.

The offline wrapper uses a 4 GiB virtual-address limit **only because
QEMU reserves a large guest mapping**. This is not a meaningful or safe
PRX126 memory budget. Hardware CPU, RAM, thermal and forwarding tests
are required to establish an actual on-device limit.

The synthetic worker runs at most 300 bounded steps with a deliberately
accelerated fake source clock. These timings prove process behavior,
not actual hardware sampling, subscriber Internet uptime or performance.

## How to verify

With AOTT_VENDOR_ROOTFS pointing to an already extracted offline vendor
rootfs, run:

    python3 -m unittest discover -s tests -p 'test_h024_offline_supervisor.py' -v

Tests cover inert procd admission, vendor BusyBox/host shell syntax,
normal SIGTERM/HUP/INT shutdown, forced parent/worker death, lock
reacquisition, competing process denial, low scheduling priority,
file-descriptor and virtual-memory test limits, and zero service
registration or firmware flash changes.

GitHub CI does not include the private vendor rootfs. Source checks
run there, while vendor ABI/process tests require the Hermes offline
environment and must be explicitly reported as offline qualification.

## Production gates

1. Authorize a recoverable PRX126 direct management target. The
   [H-025 source-only resource preflight](H-025-HARDWARE-ADMISSION.md)
   validates an extracted vendor ABI and sanitized synthetic input, but
   cannot substitute for that direct target or enable this service.
2. Qualify actual PON/optical/Ethernet counter semantics, process costs,
   CPU, RAM, thermals, packet drops and residential forwarding impact.
3. Implement a distinct non-synthetic, bounded native input provider.
4. Qualify the private root-owned runtime lock directory and actual
   procd lifecycle under the vendor board kernel.
5. Design a production procd unit with verified resource limits,
   explicit operator opt-in and no unlimited respawn.
6. Connect authenticated H-016 history and H-018 saved setting
   readback only after actual runtime effect validation.
7. Keep H-015 UBIFS and H-017 external WAN reachability separately
   gated until independent qualification.

H-024 remains **IN_PROGRESS**. The live trial bank, committed recovery
bank and ISP provisioned settings have not been touched.
