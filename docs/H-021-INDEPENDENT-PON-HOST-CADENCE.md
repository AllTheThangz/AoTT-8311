# H-021: Independent PON and Ethernet cadence, source-only qualification

**State:** offline source integration. **No live ONU target, firmware install,
background sampler, WAN-speed test, or service activation.**

## Why this matters

H-018 allows different sampling frequencies for PON registration and host
Ethernet counters. The previous H-020 collector could only call both native
probes together, so it correctly rejected unequal frequencies instead of
silently ignoring a setting. H-021 supplies an explicit second collector
mode with **independent per-channel due times**, while retaining H-020's
original combined-mode contract and existing regression tests.

This solves an important source-integrity problem: **not scheduled** is
not the same as **scheduled but unavailable**. Neither status may be
interpreted as optical loss, an Ethernet disconnection, zero traffic,
or a failed customer Internet connection.

## Implementation

The existing, fixed native read-only adapter now exposes:

    history_native_probe.read_selected(provider, {pon=true, host=false})
    history_native_probe.read_selected(provider, {pon=false, host=true})
    history_native_probe.read_selected(provider, {pon=true, host=true})

It continues to read and verify kernel boot ID and monotonic uptime both
before and after native work, enforcing its 12-second maximum observation
window. It executes only fixed read-only argv for channels actually due.
A selection with no channels, nonboolean flags, or unknown keys fails
before any kernel or native command is requested.

H-011's original read_once remains a compatibility wrapper that samples
both channels. It has not been replaced by automatic background work.

The H-012 RAM sampler now provides a separate ingest_selected path.
It records explicit attempted-channel flags. A skipped PON or host
reading is exposed as **not_sampled**, not unavailable. A genuine
read failure is **unavailable**. Neither one is silently filled with
previous measurement values.

Host RX/TX Mbps deltas use two *actual Ethernet counter measurements*,
even when PON-only samples occurred in between. If the byte counters
did not change, that may legitimately produce zero measured throughput
over a real interval; a skipped poll alone never fabricates zero. The
existing exact-unsigned-64 delta model and reset guards remain in use.

A failed scheduled PON read still breaks a potentially misleading rate
baseline, and a true host measurement failure also resets its baseline.
Reboot, source-interface changes and long collection gaps reset all
epoch-sensitive comparison values. A PON-only state transition is
recorded with the elapsed window between genuine PON observations.

New sample status labels are partial_interval and not_sampled. H-014
rate aggregation, H-016 sanitized JSON/CSV and the history-view JavaScript
accept the new labels. The GUI shows **Not sampled this interval**,
rather than claiming the link was disconnected or the ISP was down.
Only truly unavailable attempts count as missing probe samples in the
coverage summaries.

## Collector schedule

The additional API is:

    history_collector.new_independent(source_prefs, source_profile, "offline_synthetic")
    history_collector.tick(handle, monotonic_uptime, provider)
    history_collector.status(handle)
    history_collector.view(handle, range, limit)
    history_collector.export_json(handle, range, limit)
    history_collector.close(handle)

It reuses H-020's one-owner-per-Lua-process guard and private history ring.
No procd/cron timer is created. A caller explicitly requests every tick.
The next due time is the smaller of the PON and host due times. A tick
calls exactly the probes scheduled at that moment, including only one
PON or one Ethernet command when the other is not due.

Permitted source choices are 30/60/120/300 seconds for each channel,
subject to the conservative H-018 combined worst-case command waiting
budget of 720 seconds per hour. Both channels at 30 seconds are rejected.
Examples validated offline include 30/60, 60/30, 60/120, 120/300
and 300/120 seconds. Delayed ticks do not start catch-up bursts.

Only a **source-only synthetic-qualified profile** can activate the
model, and only with the explicit offline_synthetic mode. Even that
mode performs no actual hardware access unless a test injector is
supplied. The qualified-board flag is not a board attestation.

H-020's original combined constructor remains deliberately limited to
equal 60/120/300-second cadences for backwards compatibility.

### True reboot verification

If the supplied monotonic time decreases, H-021 requests a bounded
native observation and accepts the reset **only** when its boot ID
differs from the last independently observed kernel boot ID.
Identical IDs or invalid readings cannot rewrite the collector's
tick clock, counter baseline or history epoch. After a verified boot
change, the two schedules restart from the new monotonic uptime,
and H-012 records a reboot marker rather than inventing an outage.

### Known unsupported controls

Optical measurement cadence is not wired to an optical sensor reader,
so an optical interval differing from the prototype's default is
explicitly rejected. Heavy diagnostics, UBIFS persistence, local
alert delivery, outbound notifications and customer-router WAN probing
remain unimplemented. No live control is saved or acknowledged as
applied.

This still needs the per-board CPU/thermal and service no-regression
checks. The PON O5.1 state is not proof of customer Internet service.

## Reproduce

    lua5.1 tests/h021_independent_cadence_fixture.lua prototypes/history overlay/usr/lib/lua
    python3 -m unittest discover -s tests -p 'test_h021_independent_cadences.py' -v
    python3 -m unittest discover -s tests -p 'test_browser_h021_independent.py' -v

The fixture performs **324 synthetic assertions** on host Lua 5.1
and vendor MIPS Lua under QEMU, using an extracted offline rootfs.
It covers fixed command selectivity, actual counter interval length,
correct sampled PON events, skipped vs failed classifications, 30/60,
60/30 and 120/300 schedules, bounded retry handling, true boot
validation and bad-clock refusal.

The Chromium browser fixture uses the actual H-021 Lua-generated JSON
through H-016's static history UI. It verifies that a host-only
observation shows **Not sampled this interval** for PON, retains
measured-rate points, and cannot claim an Internet outage. Unexpected
external requests are rejected. Real Chromium is required by CI,
even if unavailable on Hermes.

## Still blocked before a usable residential release

1. Directly authorize a recoverable PRX126 administration target; do
   not route commands through unrelated hosts to bypass target policy.
2. Measure genuine optical registration, native host counters and
   process/RAM/thermal overhead under actual residential traffic.
3. Qualify a cross-process exclusive collector, procd life cycle,
   reboot/recovery safeguards, interval and cache coalescing, and
   low-priority resource behavior so PON forwarding cannot be affected.
4. Qualify an authenticated LuCI endpoint and configuration worker
   with real save, readback, runtime effects and source identity.
5. Build actual optical diagnostics, real H-015 UBIFS durability, and
   independent H-017 router WAN health with honest uncertainty.

**The source-only collector is not yet a running firmware feature.**
No live stick, ISP provisioning, firmware bank selector, rootfs overlay,
or persistent flash history was changed in this milestone.
