# H-020: One shared collector, source-only integration and admission gates

**Checkpoint:** November 2, 2026. **State:** offline source integration.
**Hardware:** not directly qualified. **Firmware:** unchanged.

## Purpose

The H-011 through H-019 source prototypes contain fixed PON/host
telemetry, exact unsigned-64 counters, guarded RAM rings, windowed
statistics, exports, offline persistence and monitoring preferences.
They previously had no common owner responsible for bounded, serial
native collection. H-020 connects these specific components through
one manual, source-only collector API.

The selected administration gateway currently authorizes Hermes and
five Proxmox hosts, but **does not list the ONU as a permitted target**.
No direct PRX126 readback, traffic or thermal qualification was performed
for this work. The vendor-MIPS Lua checks use an already extracted
**offline** firmware rootfs, not live PON hardware.

## Implementation

Source module:

    prototypes/history/8311/history_collector.lua

API:

    M.new(source_preferences, source_capability, mode)
    M.tick(handle, monotonic_uptime_seconds, readonly_provider)
    M.status(handle)
    M.view(handle, range, limit)
    M.export_json(handle, range, limit)
    M.export_csv(handle, range, limit)
    M.close(handle)

The module calls the already tested fixed H-011 one-shot adapter and
H-012 RAM sampler, then serves the H-016 bounded JSON/CSV projection.
It does not schedule itself or register any web route.

The constructor accepts only a source-only preference state. Sampling
starts disabled, consistent with H-018. The only enabled mode is
the explicit offline_synthetic test mode combined with a synthetic
native-qualified profile. That is **not** real hardware attestation.
There is no runtime code path intended for production activation.

One live collector handle per **Lua process** is permitted at a time.
A private weak-keyed state table holds the actual RAM sampler and native
boot identity, while outward-facing receipts contain only safe status,
counts, unavailable/observed flags and the next due time.

The collector refuses overlapping or reentrant reads and polls only
when explicitly invoked and due. It guarantees that repeated premature
ticks do **not** execute extra native commands. Failed reads back off
for 15, 30, 60, 120 then up to 300 seconds before another explicit
invocation. This is a delay policy, not an operating-system timer.
Reads that span an invalid boot epoch or do not align with their
own monotonic observation window are rejected.

### Legacy shared-mode cadence limitation and H-021 follow-up

A separate [H-021 source-only independent-cadence mode](H-021-INDEPENDENT-PON-HOST-CADENCE.md)
now selectively reads only due native channels, preserves distinct
not_sampled and unavailable states, and calculates exact host throughput
between actual byte-counter observations. The legacy combined mode
below remains intentionally unchanged for backward compatibility.
Neither mode is deployed or authorized on real PRX126 hardware.

The original fixed H-011 adapter polls PON status and host Ethernet
together. H-020 deliberately accepts only **equal** 60-, 120- or
300-second PON/host intervals. The 30-second paired option exceeds
the initial conservative source-level process-wait budget.

H-018 independently exposes distinct PON/host frequencies for future
use, but H-020 explicitly refuses a request for unequal cadences.
It does not silently poll one device more often or less often than
the user requested. Independent per-channel native read scheduling is implemented in
H-021's separate offline synthetic mode, not this legacy combined mode.

Optical polling, heavier diagnostics, flash persistence, actual local
alerts and remote notifications are **not implemented in this
collector**. Requests that rely on those actions are rejected rather
than acknowledged as successful. No actual native processes or
filesystem writes occur in the offline fixture.

### Event noise improvement

The H-012 sampler now records a missing-channel event **once per
continuous failure of the same channel combination**, rather than
emitting the identical event on every scheduled observation.

When a channel becomes observable again, the missing-state baseline
is cleared without inventing a false recovered connection. If the
PON state actually changes later, the real sampled transition is
recorded. A new failure period produces a new unavailable event.
Boot changes, source changes and long gaps still reset the
comparison epoch.

This prevents repeated partial telemetry failures from replacing
meaningful link transitions in a small finite RAM event ring.

## Offline evidence

Run from repository root:

    lua5.1 tests/h020_collector_fixture.lua prototypes/history overlay/usr/lib/lua
    python3 -m unittest discover -s tests -p 'test_h020_collector.py' -v

To repeat the same fixture with the actual extracted vendor MIPS Lua,
supply an offline rootfs through AOTT_VENDOR_ROOTFS. The vendor PON
and Ethernet kernel devices are not attached to QEMU. This is a
source-compatibility test, not a physical hardware observation.

The deterministic fixture exercises 1,181 checks on both runtimes.
It includes:

- Disabled collector: no native provider is needed or invoked.
- Gate refusal: an enabled source profile requires explicit
  offline_synthetic mode; missing qualification is rejected.
- Process-local single-owner, reentrant attempts, safe close and
  invalid handles.
- Initial baselines, consecutive exact-counters and valid Mbps,
  independently unavailable PON status and recovered observations.
- Early ticks, 15/30/60/120/300-second backoff and recovery.
- Monotonic clock regression, malformed boot identity, a fully
  unavailable native report and safe no-data classification.
- JSON/CSV history output with no boot UUID or raw byte counter.
- 100 repeated partial PON reads producing **one** missing-channel
  event, then a real PON change and a separate new failure event.
- Unmatched requested PON/host cadences refused explicitly.

## Production gates

Before this model is installed or enabled in an actual ONU:

1. Add the PRX126 as a directly authorized, recoverable administration
   target. Do not tunnel around administration target boundaries.
2. Perform **read-only** one-shot measurement of actual PON, host
   counters and optic performance. Independently verify real RX/TX
   direction, counter freshness, status semantics, service
   responsiveness and memory/CPU costs at idle and under traffic.
3. Implement a cross-**process** single-owner lock, qualified
   lifecycle/supervisor, missed-tick semantics and safe cancellation.
   The source-only Lua singleton is **not** a process-wide lock.
4. Support independent per-channel polling without false unavailable
   observations or counter interpolation, or explicitly constrain the
   installed settings to the supported shared cadence.
5. Verify that a crashed collector never affects normal PON
   association, Ethernet forwarding or management access.
6. Only after native and resource gates pass, add an authenticated,
   bounded read-only LuCI history API and qualified settings worker.
7. Keep H-015 UBIFS durability and H-017 actual router-side WAN
   reachability separately gated. Neither PON O5.1 nor host Ethernet
   speed establishes customer Internet uptime.

No procd service, cron job, LuCI route, firmware overlay entry,
live hardware command, flash operation, ISP setting or firmware
A/B bank change is included in H-020.
