# V3 local history runtime qualification

**Status:** source-integrated, opt-in, default disabled, read-only hardware resource evidence collected. Not yet a flashed V3 hardware acceptance.

AoTT-8311 V3r1 now contains an optional local history worker and authenticated History page. The implementation keeps history in RAM, uses the existing read-only PON and host-Ethernet observation paths, and publishes bounded snapshots through two independent kernel locks. It does not enable an anonymous history endpoint, periodic flash-history writes, or remote management.

## Runtime safety model

- The init service reads a dedicated history configuration and does nothing unless local sampling is explicitly enabled.
- The worker runs as a single low-priority foreground process. No procd respawn policy is configured.
- PON and host Ethernet channels have independent sampling intervals.
- Retained samples and events have explicit RAM caps.
- Snapshot files exist only under the fixed root-owned runtime directory and are bounded to 65,536 bytes.
- A collector owner lock proves a worker is alive.
- A separate publication lock is acquired only after the current worker has atomically written and read back its own first snapshot.
- The authenticated reader checks both locks before and after reading. Leftover bytes from a crashed or previous worker therefore cannot be treated as current history.
- Four consecutive complete probe failures revoke publication admission and invalidate the current snapshot.
- PON association and host Ethernet status are never reported as proof of subscriber Internet availability.

## Source and vendor-runtime qualification

The current combined V3 source suite passes 1,202 tests with zero failures or errors. Tests requiring an unavailable browser or optional private runtime are skipped rather than reported as passes.

The V3 history-specific fixture also passes under both host Lua 5.1 and the extracted PRX126 vendor MIPS Lua/nixio runtime. An affected-component vendor-runtime regression passed 157 substantive tests, including H-011 through H-027 history primitives, the H-024 supervisor, cross-process lock/restart cases, and the V3 live-history paths.

A dedicated vendor-MIPS production-path fixture also exercises the exact fixed /run/aott-history directory: it acquires the collector fcntl lock, atomically publishes and reads back a local-runtime snapshot, proves the snapshot is unreadable before publication admission, acquires the independent publication lock, verifies guarded reads, revokes publication, proves stale bytes are denied, invalidates the snapshot, and releases the collector lock. The fixture runs on Hermes only and does not contact or modify the ONU.

## Read-only PRX126 resource reference

A production r9 reference unit was observed without changing files, configuration, services, firmware banks, or boot selectors. The exact native commands used by the planned V3 sampler were invoked five times at an intentionally aggressive two-second cadence, followed by an equal-duration idle baseline.

Observed reference:

| Measurement | Aggressive probe window | Idle reference |
| --- | ---: | ---: |
| Window | about 10.4 s | about 10.0 s |
| Aggregate CPU busy | about 35.6% | about 25.8% |
| Approximate incremental busy fraction | about 9.8 percentage points | n/a |
| Available memory | essentially unchanged | normal small variation |
| Thermal zone | 50.9 C to 50.5 C | 50.7 C to 50.5 C |
| Host Ethernet link | 10,000 Mbps | unchanged |

The stress reference is roughly twenty times more frequent than the intended 30 to 60 second residential cadence. It is evidence that the native reads are lightweight enough to continue qualification, not a throughput or long-duration soak result. A final V3 hardware trial must still measure the actual integrated worker under normal cadence while forwarding traffic.

## Remaining gates

Before local history can be called hardware-qualified:

1. Build the exact integrated V3 source reproducibly and verify bank headroom.
2. Stage only after separate authorization and preserve the committed recovery bank.
3. During a one-shot V3 trial, enable local history deliberately and measure CPU, RAM, thermal behavior, forwarding, PON stability, and management access.
4. Verify worker stop/start, stale-snapshot denial, and configuration persistence across reboot.
5. Confirm the authenticated History page in real Chromium across dark/light and mobile layouts.
6. Keep persistent history disabled until the C-013 durability and wear-limiting path is separately qualified.

No live firmware mutation is authorized by this document.
