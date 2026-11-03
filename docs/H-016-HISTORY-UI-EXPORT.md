# H-016: Bounded history preview and JSON/CSV export

**State:** offline source prototype, November 2, 2026. **Not deployed.**

## Goal and scope

A residential XGS-PON bridge should provide useful history without becoming a
large always-on monitoring appliance. This milestone adds a portable source
projector and an accessible, static history preview that consumes existing
H-011/H-014 RAM observations. It does **not** register a live LuCI route,
background collector, timer, router probe, persistent store, or actual data
feed to a running ONU.

## Source contract

The source-only Lua module is:

    prototypes/history/8311/history_export.lua

Its methods are:

    M.project(state, range, limit)
    M.export_json(state, range, limit)
    M.export_csv(state, range, limit)

The ranges are **hour, day, week, month, ninety_days**. All five summaries
come from the existing exact-counter, duration-weighted H-013/H-014
aggregation. Every summary explicitly reports measured seconds, coverage
fraction, and missing intervals, rather than pretending a full time range
was observed.

The projection carries at most **100 latest-epoch samples** and **100
latest-epoch events**. Its raw tail is independent of the initial view,
so changing from an hour to a day can reveal older retained observations
without a new fetch. Range-specific CSV exports apply the selected time
cutoff. Rates from an interval crossing that cutoff are omitted, never
extrapolated. An arbitrary 90-day selection does not produce 90 days of
records from a small RAM ring.

The output limits are **64 KiB JSON** and **64 KiB CSV**. A failed validation
or exceeded cap returns an explicit error rather than silently truncating.

The sampler now assigns a monotonically increasing *private-in-process
epoch sequence* when it observes a reboot, interface change, or long
observation gap. No subscriber identity or boot UUID is exported. The
projector filters history to the current epoch, preventing old boot-relative
uptimes from being mistaken for current readings after a reboot.

Raw Ethernet byte counters, registration credentials, LOIDs, serials,
MAC addresses, destination hostnames/IPs, arbitrary device output, and
extra unrecognized properties are not included. CSV uses a fixed 12-column
schema with formula-like text neutralization. No CSV download executes
code in the ONU.

## Static browser preview

Files:

    prototypes/history/ui/history.html
    prototypes/history/ui/history.css
    prototypes/history/ui/history.js

Features: accessible control labels, responsive layout, readable dark/light
colors, separate PON/host/Internet/optics provenance, host Ethernet RX/TX
average and peak cards, accessible SVG throughput graphs, observed state
changes and missing-data tables, five selectable ranges, and bounded
JSON/CSV export controls.

Graphs leave unobserved and cross-window intervals blank. The UI never
turns missing data into zero traffic, presents state-change windows as
exact outage times, or interprets optical O5.1 as functioning Internet.

**This page has no automatic request path and receives no production data.**
Its rendering API requires a sanitized source projection injected explicitly
by the test harness. The Lua exporter and browser both drop unknown fields.
An actual installed view will require an authenticated, read-only LuCI
endpoint and a qualified collector before any claim of working device
history is appropriate.

**Not available yet:** optical power history, on-device event collection,
WAN/router reachability, cross-reboot calendar-time continuity, persistent
flash summaries, or observed customer ISP outage totals. The preview
labels each of these limitations explicitly.

## Reproduce offline

Run from the repository root:

    lua5.1 tests/h016_history_export_fixture.lua prototypes/history
    python3 -m unittest discover -s tests -p 'test_h016_history_export.py' -v

With an extracted local vendor MIPS rootfs and QEMU available, the Lua
fixture runs unchanged in the vendor MIPS interpreter.

The real Chromium UI regression suite:

    python3 -m unittest discover -s tests -p 'test_browser_history_ui.py' -v

As with the existing source-validation workflow, real browser testing is
mandatory in GitHub CI. Those tests use only synthetic JSON emitted by the
actual Lua projector. They intercept requests and prohibit unexpected
network access. They exercise range selection, darkness/lightness and
contrast, the distinction between PON/host/WAN states, browser download
controls, invalid payload rejection, and rendered missing-data gaps.

## Remaining qualification gates

1. **Real telemetry:** independently qualify the read-only PON and
   ethtool measurements on a recoverable PRX126; measure resource and
   network overhead. Never enable a new collector solely from this PR.
2. **Runtime integration:** design a single shared, permission-checked
   history producer, with bounded memory, explicit collection interval,
   backoff, and authenticated read-only route. No anonymous endpoint.
3. **Visual validation:** verify actual running LuCI dark/light themes,
   responsive mobile layout, keyboard navigation, screen reader labels
   and diagnostic readability against real output.
4. **Persistence:** power-fail-safe and wear-limited event summaries
   remain H-015, distinct from this volatile source preview.
5. **WAN:** a trustworthy, explicitly authorized router-side probe adapter
   must independently establish customer Internet availability (H-017).
   A failed destination does not automatically prove an ISP fault.
6. **Optics:** sample actual RX/TX power, error/drop counters and
   alarms before any optical trend graph can be enabled.

This work does not change the rootfs source manifest, firmware banks,
subscriber configuration or live ISP service. H-016 remains IN_PROGRESS.
