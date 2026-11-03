# H-013/H-014: Bounded RAM throughput windows and honest coverage

**State:** offline source prototype, November 2, 2026. **Not deployed.**

## Delivered

A read-only, dependency-free Lua 5.1 aggregation module at
prototypes/history/8311/history_aggregate.lua consumes the existing
H-011/H-012 bounded RAM sampler. The sampler now offers two explicit
query APIs:

    sampler.summary(state, requested_window_seconds)
    sampler.history_windows(state)

The five predefined windows are 1 hour, 24 hours, 7 days, 30 days and
90 days. They are **query lengths**, not a promise that the ONU has
stored that much history. The default source ring holds 120 samples,
and at most 720; a module that has not been installed or running cannot
provide any live history.

To avoid rescanning five windows on every GUI refresh, the predefined
window query uses a weak-keyed, RAM-only cache keyed to the sampler's
accepted-observation revision and ring position. A new accepted sample
invalidates the cache. Returned windows are defensive copies, so a GUI
caller cannot mutate the cached results. The cache stores no subscriber
identity, raw counters or target configuration and never writes to flash.

For each window, the module returns independently calculated RX and TX
host-Ethernet byte-counter rates: a duration-weighted average in Mbps,
peak observed interval Mbps, count of valid rate intervals, and seconds
actually covered by those intervals. Coverage fractions use the whole
requested duration as denominator, never an invented complete time series.
No samples or valid intervals yield a null average/peak, not a false zero.

## Data integrity rules

- Rate source must be the existing exact unsigned-64 Ethernet counter
  model, with validated host RX/TX direction and a positive interval
  at most one hour.
- Intervals that begin *before* the requested time window are entirely
  excluded. Traffic within the unobserved portion is not extrapolated.
- RX and TX measurements have separate weighting and denominators.
  One direction can remain valid when the other's counter is absent.
- Invalid/missing probes, counter resets, excluded boundary intervals
  and empty history never contribute synthetic throughput.
- Reboot, interface change and sampling gaps break the aggregation
  window. The model will not blend old boot epochs or interfaces.
- A 90-day request with minutes of RAM samples reports the minutes
  measured and explicitly states that the requested window is not
  complete.
- The aggregate reads the bounded ring of up to 720 samples directly.
  It does not lift the existing 100-item raw-export cap.
- Source interface identifiers and status codes are validated against
  an allowlist. Boot IDs, registration tokens, raw counters, device logs,
  MACs, external targets and credentials are never exported.
- WAN speed, full Internet reachability, reliable calendar time,
  hardware qualification and cross-reboot continuity are all
  explicitly **not proven** by these results.

The output includes the latest observed PON and host-link readings,
with independent availability labels. This is context, not evidence of
Internet connectivity or the subscriber's provisioned rate.

## Reproducible offline qualification

From the repository root on a host with Lua 5.1:

    lua5.1 tests/h013_h014_rate_aggregate_fixture.lua prototypes/history
    lua5.1 tests/h014_five_window_cache_benchmark.lua prototypes/history
    python3 -m unittest discover -s tests -p 'test_h013_h014_rate_aggregate.py' -v

The deterministic 681-assertion fixture also passes under an already
extracted vendor MIPS Lua interpreter executed in QEMU. It exercises
duration weighting, missing TX, PON unavailability, cross-window
exclusion, long gaps, reboots, interface changes, 350 source
observations with oldest-first eviction, all five presets, invalid
input and corrupted-ring rejection, plus cache isolation and automatic
invalidation after the next accepted measurement.

A repeatable synthetic benchmark uses **720 retained samples and 200
five-window queries**. In one Hermes offline test session, host Lua CPU
time decreased from 2.535 seconds to about 0.028 seconds after adding
the cache; vendor MIPS Lua running under QEMU decreased from 35.666 to
about 0.369 seconds. These are **offline repeated-query measurements**,
not actual PRX126 timings or a prediction of hardware CPU utilization.
The cache adds a small bounded amount of RAM, with no flash traffic.

## Boundaries and remaining release gates

1. H-013: qualify actual vendor Ethernet RX/TX counter direction,
   counter resets, driver refresh cadence, byte accounting and native
   source correctness on recoverable PRX126 hardware.
2. H-014: benchmark aggregate runtime and retained RAM on the real
   board while the GUI and forwarding path are active. Test missing
   data and power events under representative throughput.
3. H-016: implement history panels and bounded JSON/CSV exports only
   after the underlying on-device sampler is qualified, without
   giving 90-day UI controls a false retention guarantee.
4. H-015: wear-aware persistent summaries are a separate project.
   This source module makes no writes and provides no history after
   a restart of the memory-owning collector.
5. H-017: independent router-side WAN reachability must be verified
   separately; PON association and host Ethernet throughput cannot
   stand in for subscriber WAN uptime or speed.

This work adds **no** rootfs overlay entries, scheduled service, network
probe, flash writes, native processes, firmware bank operations, or
live ONU access. It is a source-only building block.
