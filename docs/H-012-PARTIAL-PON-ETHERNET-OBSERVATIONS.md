# H-012: Independent PON and Ethernet state history with partial probes

**State:** offline source qualification, November 2, 2026. **Not deployed.**

## The observed source weakness

The initial RAM sampler tracked a combined valid/invalid status for PON and
Ethernet. If one native reader failed, it intentionally marked the complete
observation unavailable to avoid inventing a link outage, but could also
suppress a genuine status change from the other, working reader. For example,
a PON state transition while the host speed sysfs read was unavailable would
not be recorded as a PON transition.

This update introduces independent, bounded per-channel freshness, while
preserving the existing combined counter-rate safety requirements. It
does not change the underlying firmware or the native PON/ethtool readers.

## Current source behavior

| Scenario | History result |
| --- | --- |
| PON 51 to 60, Ethernet status unavailable | PON transition recorded with a sample-time window; host marked unknown |
| Ethernet 10000 to 0 Mbps, PON status unavailable | Host link transition recorded with a sample-time window; PON marked unknown |
| A missing PON reading followed by PON 51 | New baseline, no invented recovery |
| A missing host reading followed by 10000 Mbps | New baseline, no invented host connection event |
| Both readings unavailable | One unavailable event, no invented PON/host transitions |
| Complete valid observation after partial failure | Restart combined throughput baseline; no cross-gap byte-rate estimate |
| Same boot and interface, valid consecutive samples | Exact existing counter-rate math and individual status transitions |
| Reboot, interface-source change, or over-one-hour gap | Both channel baselines reset; transitions across the boundary are not fabricated |
| Duplicate or reversed monotonic timestamp | Reject the sample without altering retained events |

The [H-020 single-owner source integration](H-020-SINGLE-COLLECTOR-INTEGRATION.md)
now suppresses repeated identical missing-channel events during a
continuous partial read failure while still retaining safe observations.
A genuine subsequent PON/link transition and a new failure period
produce distinct events. This is an offline model behavior, not a live
ONU outage measurement.

Every sample reports separate pon_observation and
host_link_observation labels, each either observed or unavailable.
The existing retention limits, export-size bounds and identity filtering
remain in place. PON status, host-link status, and actual Internet-path
reachability are **three distinct questions**. This code does not assert
subscriber Internet availability.

## Reproduce

From the source checkout with Lua 5.1:

    lua5.1 tests/h012_independent_channels_fixture.lua prototypes/history
    python3 -m unittest discover -s tests -p 'test_h012_independent_channels.py' -v

For vendor-MIPS checks, provide an *offline extracted* AOTT_VENDOR_ROOTFS
and QEMU. The same deterministic 85-check fixture passes in host Lua and
the extracted vendor interpreter. No native PON commands are executed.

## What remains before hardware release

1. Confirm the actual native PON and Ethernet readers return the expected
   state and missing-data patterns on a recoverable PRX126.
2. Verify the separate channel baseline resets during real transient
   timeouts, loss of fiber, Ethernet link changes, module reboot, and
   management-only reachability interruptions.
3. Measure real sampler CPU, memory, probe latency, network drops and
   management responsiveness across representative traffic.
4. Add optical alarms, error/drop counter events and independently verified
   WAN connectivity evidence. Neither O5.1 nor host 10G is WAN uptime.
5. Implement a qualified shared collection loop and storage/export only
   after the read-only reference hardware qualification.

The source module and test fixture remain outside the firmware overlay.
No collector process, HTTP route, periodic timer, flash history or firmware
bank operation is introduced.
