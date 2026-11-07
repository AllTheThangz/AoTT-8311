# AoTT-8311: optional external Prometheus JSON adapter

This sample runs on a **user-owned monitoring host**, never on the ONU. The
firmware exposes a read-only JSON endpoint, but does not ship a Prometheus
server, daemon, exporter, dashboards or database.

The adapter uses Python 3's standard library only. It translates the eight
documented optical/PON numeric fields into low-cardinality Prometheus gauges
and caches successful **or failed** ONU queries for a minimum of 15 seconds
(default 60 seconds) to avoid repeatedly invoking the vendor PON status
utility. It does not store a time series or retain stale measurements after a
failed poll.

## Setup

1. In the AoTT-8311 r8 Monitoring & Telemetry page, generate the read-only
   collector token, save the exact IPv4 address of the monitoring host as
   seen by the ONU, and enable the export. The running firmware must be an
   independently qualified r8 build. The public r8 source is a draft.
2. On the **external collector host**, save the one-time 64-character token
   in an owner-only regular file with mode 0600 or 0400. Do not commit it to
   GitHub or expose it in shell command history.
3. Make the ONU's HTTPS certificate trusted by the collector. Use your
   organization's CA bundle or certificate deployment mechanism. There is
   deliberately **no insecure TLS verification switch**.
4. Run the example with a user-controlled endpoint and private token file:

```sh
python3 examples/monitoring/prometheus_json_adapter.py \
  --onu-url https://onu.example.net/cgi-bin/luci/8311/metrics \
  --token-file /path/to/private/collector-token \
  --ca-file /path/to/trusted-ca.pem \
  --port 9109 \
  --minimum-poll 60
```

The `onu.example.net` name is a reserved example, not a built-in destination.
With a public CA you may omit `--ca-file`; certificate verification stays
enabled. No username or administrator password is needed for the collector.

The adapter **always binds to localhost**, not all interfaces. Run Prometheus
in the same network namespace, or use a separately secured reverse
proxy/tunnel. When Prometheus is inside a Docker bridge-networked container,
its `localhost` is **not** the host's loopback address. A hardened adapter
sidecar sharing Prometheus's network namespace can preserve loopback-only
scraping without opening port 9109 on other interfaces. Review the container
runtime, token-file UID/mode, trusted CA mount and network namespace before
deploying; changing the adapter to bind all interfaces is not an acceptable
shortcut.

## Source-IP restrictions when using NAT

An exact permitted collector IP is the source address as seen by the
ONU after routing and NAT. On some networks, distinct client machines
share one apparent public egress IP. This makes an IP allowlist unable
to distinguish those machines even when each has a different private
address. Enforce source-specific filtering at the upstream gateway
before translation, or use a management route that preserves source
identity. Never rely on a common NAT egress address as proof of a
unique client. Keep HTTPS certificate validation and the separate
read-only token enabled.

## Prometheus example

```yaml
scrape_configs:
  - job_name: aott8311
    scrape_interval: 60s
    static_configs:
      - targets: ["localhost:9109"]
```

The adapter's `/metrics` endpoint is independent of the ONU's LuCI endpoint.
Prometheus scrapes the adapter; only the adapter contacts the ONU over HTTPS.

## Interpreting data and failures

- `aott8311_collection_success` is `1` if the last bounded HTTPS JSON
  request succeeded, `0` if the ONU, TLS, authorization or response failed.
  Alert if it remains zero across multiple scrapes.
- Null, missing, boolean, text, NaN or infinite readings are **omitted**, not
  converted to zero or stale values.
- Optical receive and transmit power use dBm, module voltage volts, laser
  bias milliamps, temperatures degrees Celsius.
- The numerical PON registration field is a **state**, not a bandwidth
  measurement. A 10 Gbps host link does not imply provisioned throughput.
- The sample deliberately includes no subscriber identity, serial number,
  MAC address, host topology or arbitrary metric labels.
- HTTP responses are capped at 8 KiB and the ONU HTTPS request at 5 seconds.
  One request at a time and 60-second caching protect the small embedded ONU.
- The output contains only static gauge names and numeric values. Raw errors,
  HTTP headers, bearer tokens and returned private text are never emitted.

This is an optional reference adapter, not a bundled firmware component.
Other users may use their preferred collector or equivalent JSON conversion.
Actual real-device response and firewall behavior remain subject to the r8
hardware acceptance gates.
