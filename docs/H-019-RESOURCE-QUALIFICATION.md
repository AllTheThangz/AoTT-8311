# H-019: Source-level history resource budget and hardware acceptance

**Checkpoint:** November 2, 2026. **State:** IN_PROGRESS, offline model only.
**Production H-019 acceptance:** NOT DONE. **Live ONU:** not queried.

## Why this measurement exists

AoTT-8311 is a small residential ONU bridge, not a monitoring appliance.
Optional history must not trade away stable PON registration, Internet
forwarding, management access, or flash lifetime. A synthetic benchmark can
find unbounded memory growth and costly parser paths before any hardware
trial. It cannot establish real board CPU, DMA, optics or ISP throughput cost.

The benchmark uses the **existing** one-shot reader and 120-sample/128-event
RAM ring with a deterministic fake provider. It never invokes actual
`pon`, `ethtool`, SSH, routers, UCI, flash, firmware tooling or network
operations. It lives outside the deployable firmware overlay, does not add a
resident service, and provides no claim of on-device history availability.

## Reproduce the offline test

From the repository root with Lua 5.1 installed:

```sh
python3 tools/bench_h019_offline.py --iterations 2500 --repeats 2
```

For an independently extracted, local reference vendor rootfs with MIPS Lua
and QEMU available, append `--vendor-rootfs /path/to/offline-rootfs`.
The path must refer to an **offline extracted directory**, not a device,
network URL or mounted customer filesystem.

The runner limits each run to 100 to 20,000 mock cycles, 1 to 5 repeats,
uses no shell invocation, and emits sanitized JSON. A failed cycle, missing
fixed dependency or malformed result aborts the experiment.

## Offline result, one Hermes benchmark session

Two independent runs of 2,500 synthetic cycles were completed for each
runtime. The following are illustrative measurements from this session,
not fixed performance specifications or predictions for an ONU:

| Item | Host Lua 5.1 | Vendor MIPS Lua via host QEMU |
| --- | ---: | ---: |
| Median Lua CPU time per **mock** observation | 0.1037 ms | 1.5840 ms |
| Highest retained Lua heap delta after GC | 132.62 KiB | 100.35 KiB |
| Observed transient Lua heap high point | about 562 KiB | about 438 KiB |
| Highest **host-process** peak RSS | 3,584 KiB | 9,844 KiB |
| Samples / events retained | 120 / 98 | 120 / 98 |

Each 2,500-cycle run exercised 12,500 **mock** kernel reads and 5,000
**mock** subprocess responses. No real PON or Ethernet process was run.
The QEMU RSS includes the host emulator. Both CPU figures exclude the
actual native process latency, driver overhead, hardware interruption
effects, and any real service contention. They cannot be used as an ONU
resource budget or a claimed throughput improvement.

The benchmark confirms the synthetic RAM ring remains bounded and tests
consistent loop behavior; it does **not** prove that hardware resource
requirements fit the firmware's CPU/RAM constraints.

## Read-only PRX126 hardware qualification gates

The following must be executed only from a directly authorized ONU
management target, without routing ONU commands through an unrelated administration target.
The current project administration gateway does not identify the ONU as
an available target.

1. **Source identity:** independently confirm board and vendor ABI. Check
   that the running kernel exposes a parseable boot UUID and monotonic
   uptime; make no boot or configuration changes.
2. **Native probe semantics:** verify bounded `pon psg` output and actual
   `ethtool -S eth0_0` counter names with read-only, time-limited
   requests. Confirm that RX/TX byte counters are exact, monotonic within a
   boot, and reset correctly after a legitimate reboot. Never export
   serial numbers, LOIDs, MACs or credentials.
3. **Baseline without sampler:** record independently observed idle/normal
   traffic CPU, RSS/available RAM, temperatures, driver drops, PON and host
   link status, firmware UI responsiveness and pre-existing errors. Do not
   generate new speed-test traffic without authorization.
4. **One-shot acquisition:** measure actual command latency and memory
   impact while leaving native routing, VLANs and registration untouched.
   Confirm the 12-second acquisition gate, command timeouts and absence
   of false rate/Internet availability claims.
5. **Load comparison:** repeat under approved representative natural or
   controlled traffic, with matched baseline windows and documented
   variability. Confirm no new registration flaps, management instability,
   unbounded allocations or material forwarded-traffic regression.
6. **Single collector design:** only after the one-shot work qualifies,
   specify one shared process/interval, compute worst-case probe duty
   cycle and RAM bounds, and test cancellation and missed periods.
7. **WAN semantics:** Internet availability must be supplied by an
   independently validated router/WAN probe. Optical O5.1 and host 10G
   association alone do not prove subscriber Internet service.

Before any production feature is enabled, the board-specific CPU/RAM,
temperature, PON, host-link, drop-rate and wall-time acceptance thresholds
must be set against the recorded baseline. Do not call H-019 DONE_HARDWARE
from this offline benchmark.

## Privacy, flash and deployment boundaries

No flash writes, retention database, automatic service or firmware bank
operation is added. The bench and its fixtures belong under `tools/` and
`tests/` and are not shipped in the ONU rootfs image. The previous
source-only RAM prototype stays under `prototypes/history/`. This is
a qualification aid, not a performance-tuning preset or release authorization.
