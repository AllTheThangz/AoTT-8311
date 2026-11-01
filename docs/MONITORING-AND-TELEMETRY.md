# Vendor-neutral monitoring and logging integration

This document defines the planned AoTT-8311 v2r8 monitoring interface. It is a **design and integration guide**, not a claim that its proposed GUI controls are implemented in v2r7.

## Design principles

- Any compatible user-owned syslog receiver and Prometheus-compatible collector may be used. AoTT-8311 does not ship or assume a particular monitoring host, network, database, Grafana instance, or service provider.
- The ONU's job is exposing bounded device health data and forwarding selected log events. Collection, historical storage, analytics, dashboards and alert delivery belong on the external collector.
- Reuse LuCI/uhttpd/Lua telemetry and the existing lightweight system logger. Avoid a new background agent, Python, containers, databases and persistent flash log storage.
- Telemetry must not expose subscriber credentials, provisioning, device serials, MACs, personally identifiable data, or private network configuration.
- Restrict collection to trusted management interfaces; do not expose a scrape endpoint to the untrusted WAN.

## What exists in the current source

The inherited JSON `/cgi-bin/luci/8311/metrics` route exposes a compact collection of optical power, optic and CPU temperature, voltage, laser bias and PLOAM status. **Its route is not currently nested under the authenticated LuCI admin path**, so v2r8 must audit and harden its access boundary before any expanded exposure.

The authenticated Live Health endpoint uses `8311.health.performance()` to present selected Ethernet MAC counters, GEM/XGEM counters, uptime, optical readings and host link speed. Some source commands execute external utilities and require bounded, lower-frequency sampling.

Both APIs are read-only. Do not mistake a browser's live-refresh selector for a server-side Prometheus scraping configuration.

## Planned syslog settings in v2r8

| User-facing option | Behavior |
| --- | --- |
| Enable remote syslog | Disabled until enabled by an administrator |
| Destination | User-provided hostname or IP, validated before saving |
| Port | Configurable valid destination port |
| Transport | Only protocols shown to be supported by the installed logger; UDP is baseline when available |
| Severity | Validated logging threshold mapped onto actual vendor logger behavior |
| Test event | Locally generated, bounded, unprivileged-content message |
| Apply/revert | Save and read back effective configuration with recovery-safe failure behavior |
| Status | Distinguish local configuration, sender attempt and confirmed collector-side receipt |

An example receiver hostname is `collector.example.net`. This is a reserved documentation domain, **not** a built-in destination. Actual UI settings must be empty or safely disabled until supplied by the operator.

For OpenWrt-derived images, verify `/etc/config/system` remote logging options and the shipped `logd` implementation before designing the GUI backend. Different vendor builds may support different transports. Do not silently alter routing or firewall policy to make a collector reachable.

## Planned metrics integration

- **Basic optical/PON group:** optical RX/TX power in dBm, laser bias in mA, module voltage in volts, optic/CPU temperatures in degrees Celsius, PON registration state, uptime.
- **Ethernet group:** link negotiation, monotonic RX/TX bytes/packets, FCS/error and drop counters.
- **GEM group:** bounded number of GEM ports/counters with documented semantics; no provisioning secrets.
- Missing data is unavailable rather than zero. Rates require two samples and reboot/reset awareness. A 10 Gbps host link does not establish provisioned subscriber speed.
- Keep labels low-cardinality and free of subscriber/device identity.
- Prefer an external JSON exporter for Prometheus. Optional native OpenMetrics/Prometheus text output requires a separate size, security and CPU justification.

### Generic external collector flow

```text
Compatible ONU (trusted management network)
  |-- HTTPS read-only health/metrics -> user's exporter -> Prometheus-compatible collector
  |-- remote syslog events ----------> user's syslog receiver -> optional log store
```

The receiver and exporter are software **chosen by the user**, not embedded in AoTT-8311. Scrape timing, credentials and log retention are external deployment settings; the GUI must clearly distinguish these from locally applied ONU settings.

## Security and troubleshooting contracts

1. Require authenticated administration to change settings. Verify route-level access/management firewall rules before allowing metric reads.
2. Validate all form inputs; never compose arbitrary shell commands from values submitted in the GUI.
3. Use `no-store` and sensible response size/time limits for read-only endpoints.
4. No sender credential or registration value appears in logs or the metrics response. Test messages contain only a generic marker, not device IDs.
5. UDP transmission cannot confirm delivery. If the user's collector is unreachable, present the local send result without inventing remote receipt.
6. When DNS, gateway, receiver, clock, or logging daemon is unavailable, show the actual failure without disturbing PON, WAN or management routing.
7. Verify preservation across reboot and A/B bank transitions using the qualified firmware process; avoid frequent persistent flash writes.

See [the v2r8 plan](V2R8-PLAN.md) for implementation order, test gates and exclusion criteria.
