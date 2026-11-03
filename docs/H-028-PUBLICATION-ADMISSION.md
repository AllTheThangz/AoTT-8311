# H-028: Prevent stale history during collector-lock handoff

**Checkpoint:** November 3, 2026. **Status:** source-only, vendor-MIPS
offline tested; PRX126 runtime NOT qualified. No firmware overlay change.

## The H-027 race this closes

H-027 accepted a bounded cached JSON history file when a collector held
`collector.lock` before and after an independent reader's load. However,
a dead writer can leave valid JSON on disk. If a *new* process obtains
`collector.lock` but has not invalidated that old cache yet, a reader
could wrongly return HTTP 200. A live main lock does not identify which
writer last published the cache.

H-028 introduces a **second, independent POSIX fcntl lock**, exclusively
at the fixed filename `publication.lock` inside the same root-owned 0700
source test lock directory.

- A publisher takes the main H-022 lock before start, but is not allowed
  to admit history readers merely because that lock is held.
- The publication lock is acquired **only after** a new canonical H-026
  snapshot has been published, atomically replaced and independently
  read back. A process restarting after a crash cannot inherit the old
  owner's kernel lock; Linux releases the prior advisory locks on exit.
- A history request must observe **both** the main collector lock and
  the publication lock before reading, then verify both again afterward.
  The cached snapshot must also pass the existing strict inode,
  ownership, size, structure and canonical JSON validation.
- On normal stop, shutdown, failure cooldown or circuit breaker,
  publication admission is revoked before the cache is invalidated and
  the collector lock is released. A verified reboot boundary revokes
  reader admission before the next boot-epoch snapshot is published.
- If the second lock cannot be obtained due to another holder, wrong
  inode, symlink or ambiguous permissions, the collector enters its
  existing bounded cooldown, revokes the snapshot and cannot serve it.
  An unverified gate revocation freezes the session as unsafe.
- The publication lock file, like the main lock file, is **never
  unlinked**; it is not proof of an active process unless the kernel
  reports current lock contention. Readers never create it.

This is **not** a cryptographic publisher identity, proof of a sampled
observation's currentness, accurate Internet uptime, complete WAN
diagnostics, or an administrator-session verification. Root-level
attackers, a frozen but lock-owning producer, real transport and storage
behavior, and live LuCI session expiry are not qualified by this
source-only model.

## Verified source behavior

`prototypes/history/8311/history_publication_gate.lua` contains the
separate guarded publication lock. H-023's existing lifecycle module
opens it only after successful H-026 publication and releases it on
all controlled exit paths. H-026's `read_guarded` now checks both locks
on both sides of the data read, still returning fixed, redacted
errors through H-027's uninstalled LuCI route candidate.

Offline regression includes a direct reproduction of the prior race:
an old writer leaves a valid snapshot, then another real MIPS process
holds only `collector.lock` while the old file remains untouched.
H-028 refuses both the standalone read and the authenticated-source
HTTP response. H-027's old one-lock check would have admitted this
file. Other cases cover active readers, 60-second publishing bounds,
SIGKILL, competing lock holder, symlink refusal, normal and unsafe
stops, staged-file recovery, reboot and no unexpected native commands.

Run:

```sh
AOTT_VENDOR_ROOTFS=/path/to/extracted/vendor/rootfs \
  python3 -m unittest discover -s tests \
  -p 'test_h027_lifecycle_snapshot.py' -v
```

The extracted vendor's MIPS Lua/nixio/jsonc runs under QEMU on Hermes,
with root-owned disposable offline fixture directories and synthetic
PON/Ethernet responses. No physical ONU or router is contacted.

## Production hold

All features remain **IN_PROGRESS**, not shipped. Neither lock, the
collector, the history endpoint nor any route is listed in the
deployable overlay or release manifest.

Before activation on the residential PRX126, separately qualify a
true RAM-backed lock/snapshot directory, actual kernel and vendor
fcntl semantics on the stick, file/CPU/RAM costs and no forwarding
regression, procd crash/boot ordering, real root-admin LuCI session
behavior and safe rollback. H-015 flash history and H-017 separate
router/WAN proof are not enabled by this work.

**Source changes do not stage, flash, boot or commit either firmware
bank and do not alter ISP registration or network service.**
