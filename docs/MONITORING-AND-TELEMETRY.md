# Vendor-neutral monitoring and logging integration

**r9 integration:** This guide describes the r8 monitoring implementation retained in [the r9 firmware candidate](V2R9-INTEGRATED-RELEASE.md). The token digest domain and persistence schema are deliberately unchanged. References to r8 implementation milestones below record their original development and qualification context.

This document defines the planned AoTT-8311 v2r8 monitoring interface. It is a **design and integration guide**, not a claim that its proposed GUI controls are implemented in v2r7.

## Design principles

- Any compatible user-owned syslog receiver and Prometheus-compatible collector may be used. AoTT-8311 does not ship or assume a particular monitoring host, network, database, Grafana instance, or service provider.
- The ONU's job is exposing bounded device health data and forwarding selected log events. Collection, historical storage, analytics, dashboards and alert delivery belong on the external collector.
- Reuse LuCI/uhttpd/Lua telemetry and the existing lightweight system logger. Avoid a new background agent, Python, containers, databases and persistent flash log storage.
- Telemetry must not expose subscriber credentials, provisioning, device serials, MACs, personally identifiable data, or private network configuration.
- Restrict collection to trusted management interfaces; do not expose a scrape endpoint to the untrusted WAN.

## What exists in the current source

The committed v2r7 source inherits an anonymous JSON metrics route. The unmerged v2r8 candidate replaces it with a token-protected collector endpoint and a separate administrator-authenticated view. Neither approach is a completed hardware security qualification.

The authenticated Live Health endpoint uses `8311.health.performance()` to present selected Ethernet MAC counters, GEM/XGEM counters, uptime, optical readings and host link speed. Some source commands execute external utilities and require bounded, lower-frequency sampling.

Both APIs are read-only. Do not mistake a browser's live-refresh selector for a server-side Prometheus scraping configuration.

## Planned syslog settings in v2r8

| User-facing option | Behavior |
| --- | --- |
| Enable remote syslog | Disabled until enabled by an administrator |
| Destination | User-provided hostname or IP, validated before saving |
| Port | Configurable valid destination port |
| Transport | The audited v2r7 OpenWrt logger supports UDP and TCP; the v2r8 candidate presents both |
| Severity | The vendor forwarding service has no verified remote severity selector, so v2r8 does not present a nonfunctional one. Filter on the collector |
| Test event | Locally generated, bounded, unprivileged-content message |
| Apply/revert | Save and read back effective configuration with recovery-safe failure behavior |
| Status | Distinguish local configuration, sender attempt and confirmed collector-side receipt |

An example receiver hostname is `collector.example.net`. This is a reserved documentation domain, **not** a built-in destination. Actual UI settings must be empty or safely disabled until supplied by the operator.

The audited vendor `/etc/init.d/log` supports `log_remote`, `log_ip`, `log_port` and `log_proto`. Device-side settings do not change routes or firewall access to external collectors.

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

An optional [standard-library-only external Prometheus JSON adapter](../examples/monitoring/README.md) demonstrates how operators can use their own monitoring hosts. It is not installed on the ONU. Its loopback-only listener, TLS validation, bounded response parsing and cached polling are part of the example, not device-side settings.

The receiver and exporter are software **chosen by the user**, not embedded in AoTT-8311. Scrape timing, credentials and log retention are external deployment settings; the GUI must clearly distinguish these from locally applied ONU settings.

## Dedicated read-only collector authentication (v2r8 candidate)

The optional external JSON endpoint is `/cgi-bin/luci/8311/metrics`. This is **not a public anonymous route** in the r8 candidate. An administrator configures its separate read-only credential and an exact allowed IPv4 client in the Monitoring & Telemetry page.

- Generate the 256-bit token from the authenticated HTTPS GUI. It is displayed **once**; only a domain-separated SHA-256 digest is persisted in the device's UCI system configuration. Keep the token in a user-controlled secure secret store, not in source code, logs, URLs, query parameters or public dashboards.
- Select the single source IP as seen by the ONU, including any NAT. No wildcard or CIDR client ranges, proxy-trusted source headers or IPv6 client access are implemented in this candidate.
- The collector sends an HTTPS GET to the trusted management address with an `X-AOTT-Metrics-Token` request header. The source address, local destination and HTTPS state are checked from the socket environment supplied by uhttpd, not from user-controlled forwarded headers.
- A token alone is not a substitute for a trusted management firewall. Reject untrusted interfaces and certificate errors. The collector should validate the ONU certificate, using an appropriately trusted CA or pinned certificate as supported by its software.
- Rotate the token using the same authenticated GUI when necessary. Rotation invalidates the previous token immediately. Revocation deletes the hash and disables external metrics. Old tokens cannot be retrieved.
- The admin metrics view remains under `/cgi-bin/luci/admin/8311/metrics` and inherits LuCI session authentication. External collectors do **not** need administrator credentials.

Generic external configuration:

```text
URL: https://onu.example.net/cgi-bin/luci/8311/metrics
Method: GET
Header name: X-AOTT-Metrics-Token
Header value: <one-time token copied from the device GUI>
Scrape interval: about 60 seconds to start
TLS: validate the ONU's certificate using trusted CA/pinning
```

This is a JSON response, not native Prometheus exposition. Run a compatible JSON-to-Prometheus conversion externally. Store the header value through the collector's secret mechanism. No monitoring service, data retention or collector configuration is bundled into the firmware.

**Qualification limit:** the code and its isolated tests exist in draft source, but actual UCI persistence, HTTP header/TLS behavior, management ACLs, and A/B survivability have not yet been independently hardware-qualified.

See the [management ACL audit](V2R8-MANAGEMENT-ACL-AUDIT.md) before treating a listener bound on all device interfaces as safely restricted. The stock vendor web listener uses wildcard addresses, so hardware ingress and fallback-bank checks remain mandatory.

### Source-IP authentication caveat on NAT routes

The exact allowed IPv4 is interpreted as the remote socket address
observed by uhttpd, not the original private address claimed by a
client. A router performing address translation can cause distinct
authorized and unauthorized clients to appear under one source IP.
A live posttrial two-client check confirmed this condition on the
tested routed management path.

Consequently, configuring the shared public egress IP as the one
collector allowlist does not independently identify the collecting
machine. Enforce a per-client access restriction upstream of NAT or
use a management route that preserves the original source IP before
enabling the endpoint. The separate randomly generated token remains
mandatory but does not replace network isolation. No proxy-forwarded
identity headers are trusted by the ONU.

The current management HTTPS certificate additionally lacks a SAN and
is not verified by default TLS clients. A private-key permission issue
was also detected. Do not disable TLS verification to work around
certificate deployment; qualify a trusted identity and key storage
permissions before collecting production metrics.

## Security and troubleshooting contracts

1. Require authenticated administration to change settings. Verify route-level access/management firewall rules before allowing metric reads.
2. Validate all form inputs; never compose arbitrary shell commands from values submitted in the GUI.
3. Use `no-store` and sensible response size/time limits for read-only endpoints.
4. No sender credential or registration value appears in logs or the metrics response. Test messages contain only a generic marker, not device IDs.
5. UDP transmission cannot confirm delivery. If the user's collector is unreachable, present the local send result without inventing remote receipt.
6. When DNS, gateway, receiver, clock, or logging daemon is unavailable, show the actual failure without disturbing PON, WAN or management routing.
7. Verify preservation across reboot and A/B bank transitions using the qualified firmware process; avoid frequent persistent flash writes.

See [the v2r8 plan](V2R8-PLAN.md) for implementation order, test gates and exclusion criteria.
