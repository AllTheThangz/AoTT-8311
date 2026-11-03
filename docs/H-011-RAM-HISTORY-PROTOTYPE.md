# H-010/H-011: Exact-counter history model and bounded RAM sampler

**State:** offline source prototype, November 2, 2026. **Not deployed.**

## Goal

Provide accurate recent diagnostics for a residential ONU without assuming
a PON O5.1 state proves subscriber Internet service or using flash storage for
high-frequency samples.

The source now includes the vNext pure Lua 5.1 historical counter/event model
and a bounded RAM-only aggregator. These modules have no auto-start entrypoint,
network probe, timer, filesystem write, web route, firmware update or persistent
database. An actual collector integration is still required.

## Implemented and tested

- Exact unsigned 64-bit decimal counter deltas, including values beyond
  JavaScript/Lua floating-point exact integer range. No fabricated wrap.
- Ethernet host-interface RX and TX Mbps rates from valid monotonic intervals,
  separate from provisioned Internet throughput.
- PON registration-state and host-link transitions as sampled observations
  with explicit measurement windows, not invented exact outage timestamps.
- Per-observation boot and interface source identity, with counter baselines
  reset after reboot/source change.
- Gap events for unavailable observations and intervals longer than one hour;
  incomplete probes do not imply a PON disconnect.
- Fixed-capacity RAM rings, O(1) insertion, bounded export size and oldest
  first eviction. Default limits: 120 samples and 128 events; hard caps of
  720 samples and 256 events. Exports cap each read at 100 items.
- Sanitized, whitelisted data records and host-interface name families: no boot ID, subscriber serial, LOID,
  password, raw device output or raw 64-bit counters in export.
- Two pure Lua fixtures: 53 counter/state model checks and 1,073 RAM sampler
  checks, each passing on host Lua 5.1 and the actual offline MIPS vendor Lua
  under QEMU.

## Reproduce without touching a device

Run from repository root:

    lua5.1 tests/history_model_fixture.lua overlay/usr/lib/lua/8311/history_model.lua
    lua5.1 tests/history_sampler_fixture.lua overlay/usr/lib/lua

Run the automated wrapper:

    python3 -m unittest discover -s tests -p 'test_h011_sampler.py' -v

The vendor-MIPS fixture can be enabled by supplying an already extracted
offline AOTT_VENDOR_ROOTFS. The public repository does not bundle vendor
rootfs content.

## Missing before enabling real history collection

1. H-011: select read-only source commands and a single shared collector;
   enforce hard per-probe execution limits, consistent monotonic uptime and
   measured CPU/RAM overhead on the named hardware.
2. H-012/H-013: integrate real PON and Ethernet counter probes, distinguish
   failing sample providers from actual outages, validate RX/TX direction,
   resets, error counters and counter freshness.
3. H-014/H-015: qualify bounded retention, privacy, controlled export and
   power-cut safety. RAM-only history is lost on reboot and cannot supply
   weeks or months of continuity.
4. H-016/H-017: build accessible graphs and honest WAN/router reachability
   integration. No on-device connectivity result can be inferred from O5.1.
5. H-019: test flash wear, ONU temperature, GUI latency, CPU, RAM and PON
   stability under realistic throughput before registering a periodic sampler.

This module does **not** claim any working on-device historical monitoring,
Internet availability check, syslog delivery or production firmware support.
Firmware A/B banks, PON registration, subscriber credentials and live management
remain unchanged.
