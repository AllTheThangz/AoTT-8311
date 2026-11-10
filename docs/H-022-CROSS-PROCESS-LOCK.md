# H-022: Kernel-level cross-process history collector lock

**State:** tested against extracted vendor MIPS Lua/nixio under QEMU, November
3, 2026. **Not installed on PRX126.**

## Why this is necessary

H-020/H-021 enforce one in-process collector, but a crash, LuCI restart, or
two independent processes could still create competing native PON/ethtool
pollers. On a residential bridge, redundant monitoring should not
consume resources or disturb subscriber forwarding.

H-022 adds a genuine **Linux advisory fcntl try-lock** in an extracted
vendor MIPS Lua runtime, and requires it before opening an H-021 collector
through the guarded source-only entrypoint. This is stronger than a
synthetic mock or a process-local boolean. It is still not tested on the
live PRX126 kernel.

Source modules:

    prototypes/history/8311/history_process_lock.lua
    prototypes/history/8311/history_guarded_collector.lua

The first module uses the real vendor nixio and nixio.fs libraries. The
second uses the kernel lock to guard H-021's exact-counter, selective
read-only collector. Both are outside the deployable firmware overlay.

## Lock contract

The source allows only a trusted production directory
/var/run/aott-history, or strictly named private /var/tmp directories
reserved for the offline test harness.

A future operator-approved installation must independently provision
the production directory as **root:root, mode 0700**, on the intended
volatile filesystem. The library never creates this directory.

The lock file is named collector.lock, must be root:root, mode 0600,
regular and single-linked. Before opening, the code verifies the parent
and existing file. After opening it checks the fd and visible pathname
refer to the same device and inode. After acquiring fcntl tlock it
checks the file and parent identities again. Symlinks, hard-linked
lock files, wrong ownership or permissions, unsafe directories and
arbitrary path input are refused.

**Important ABI limitation:** the extracted vendor nixio open_flags API
does **not** expose O_NOFOLLOW. The safety of the open check therefore
depends on the already-provisioned root-owned private 0700 directory,
strong pathname restrictions, and repeated lstat/fstat identity checks.
Never place a production lock directly under a world-writable directory.
A privileged actor who can modify the private directory remains within
the system trust boundary.

The lock is nonblocking: contention fails immediately, before a
second sampler starts. The file descriptor remains open for the
entire collector lifetime. Releasing it, exiting normally, or an
unexpected process death releases the kernel lock.

**Never unlink the lock file during release.** A process that removes
the pathname while another holds the old inode can accidentally permit
two exclusive locks on different inodes.

POSIX advisory locks only coordinate **cooperating processes using the
same inode**. An unrelated process intentionally bypassing this
contract is not prevented from running other commands.

## Guarded offline collector API

    guarded.new(directory, preferences, profile, "offline_synthetic")
    guarded.tick(handle, uptime, injected_readonly_provider)
    guarded.status(handle)
    guarded.view(handle, range, limit)
    guarded.export_json(handle, range, limit)
    guarded.export_csv(handle, range, limit)
    guarded.close(handle)

The guarded constructor obtains the kernel lock first and only then
creates the H-021 in-memory collector. Failure to admit the collector
releases the newly acquired lock before returning an error.

The guarded wrapper retains the private lock token until the
collector closes. It never exports file descriptors, local boot
identifiers, raw counters, or subscriber credentials.

The entrypoint explicitly **rejects any mode other than
offline_synthetic**. A synthetic board-qualified flag is not hardware
attestation. The wrapper has no procd registration, cron timer,
LuCI route, PON-side shell execution, firmware image install, or
persistent history writes.

## Actual cross-process offline tests

Tests use temporary root-owned 0700 directories under /var/tmp
on Hermes, with independently executed extracted vendor MIPS Lua under
QEMU and the real vendor nixio.so library. The test harness
starts multiple real operating-system processes.

Run:

    AOTT_VENDOR_ROOTFS=/path/to/offline/rootfs python3 -m unittest discover -s tests -p 'test_h022_process_lock.py' -v

Verified cases:

- A process owns the lock; 12 concurrent external contenders all fail
  nonblocking acquisition.
- The same Lua process cannot create a second collector lock.
- An independent guarded H-021 collector cannot start while another
  guarded collector or direct lock owner holds the same lock file.
- Normal close, clean process exit and forced SIGKILL release the
  kernel lock; a subsequent process obtains ownership.
- The lock file inode remains stable across releases and acquisitions.
- Wrong parent permissions, a symlink lock, a hard-linked lock file,
  a non-0600 file and out-of-scope paths fail closed.
- The guarded source collector runs fixed synthetic PON/Ethernet probes,
  computes validated rates, and exposes bounded sanitized history.
  No real ONU command is invoked.

The public GitHub runner does not have the private extracted vendor
rootfs. Its source/syntax gates still run; vendor-MIPS ownership tests
are explicitly skipped there unless a qualified offline rootfs is
provided. They were executed successfully on the Hermes offline host.

## Remaining production blockers

1. Confirm the actual vendor kernel's locking behavior, tmpfs layout,
   user identity, permissions, and process lifecycle on a directly
   authorized, recoverable PRX126 target.
2. Provision the private root-owned runtime directory only during a
   separately reviewed firmware deployment, not in this PR.
3. The [H-023 offline lifecycle model](H-023-COLLECTOR-LIFECYCLE.md)
   now exercises bounded start/retry/stop and process-death release
   against this guarded collector. The [H-024 source-only foreground process test](H-024-SUPERVISOR-OFFLINE-PROCESS.md)
   now verifies TERM and parent/child crash handling with the same
   kernel lock. A real **single procd-managed process**, its on-board
   exit handling and restart acceptance still need PRX126 qualification.
4. Confirm the real PON/ethtool read costs, CPU/RAM and thermal load,
   forwarding stability, and management responsiveness during traffic.
5. Add authenticated LuCI history access and real setting readback only
   after source and hardware acceptance. H-015 UBIFS persistence and
   H-017 actual router WAN reachability remain separate.
6. Verify physical service and A/B recovery on the board before enabling
   automatic startup. This lock does not by itself qualify a firmware
   release.

The [H-027 source-only reader gate](H-027-GUARDED-LIFECYCLE-SNAPSHOT.md)
now uses a passive fcntl lock-contention check to refuse old cached
history if no collector process owns this lock. Source tests verify
SIGKILL and restarted-producer behavior; on-device acceptance remains
open.

No live stick, ISP provisioning, boot bank or hardware lock directory
was touched by H-022.
