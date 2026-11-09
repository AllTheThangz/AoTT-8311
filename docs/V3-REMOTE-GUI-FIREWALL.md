# V3 optional remote HTTPS firewall

## Source status

AoTT-8311 V3 now includes an optional residential remote-HTTPS policy inside
the existing guarded Access & servers transaction.

Remote management remains **disabled by default**. No live packet-filter rule
was installed on the production ONU during this source work.

## Product controls

The Access & servers page adds:

- `remote_gui_enabled`: explicit opt-in toggle, default 0;
- `remote_gui_ipv4_sources`: bounded IPv4 source allowlist.

The source list accepts at most eight non-overlapping explicit CIDRs from /24
through /32. Host bits, duplicates, overlapping networks, loopback,
link-local, multicast, and excessively broad ranges are refused.

An allowlist may be saved while remote access is disabled. Its generated rules
remain disabled until the explicit enable toggle is reviewed and confirmed.

## Fixed firewall scope

V3 only creates deterministic rules named:

`AoTT-Remote-HTTPS-1`, `AoTT-Remote-HTTPS-2`, ...

Each generated rule is constrained to:

- source zone: `wan`;
- protocol: TCP;
- family: IPv4;
- destination: the current ONU management IPv4 address;
- destination port: the current HTTPS port;
- target: ACCEPT.

The feature does not create SSH exposure, forwarding rules, NAT, redirects,
DNAT/SNAT, PON rules, OMCI rules, or arbitrary zone changes.

## Guarded transaction

Remote policy is part of the existing Access transaction:

1. snapshot Dropbear, uhttpd, LuCI and the firewall package;
2. write/read back the reviewed settings;
3. generate only the fixed AoTT remote-HTTPS rules;
4. restart affected access services and firewall;
5. verify the generated UCI policy;
6. require `fw3 -4 print` to render successfully;
7. require authenticated confirmation through the surviving HTTPS path;
8. restore the previous access and firewall configuration on failure/timeout;
9. recover pending state after reboot.

Ordinary access changes that leave the remote policy unchanged do not rewrite
the firewall package.

## Qualification boundary

Source tests prove deterministic policy generation, bounds, UCI readback,
fw3 renderability, recovery binding, and browser submission. They do not prove
the actual kernel packet path, ISP/router forwarding, NAT/firewall behavior
outside the stick, or reachability from a genuine external source.

Those require the later hardware trial and an explicit external probe. IPv6
remote exposure remains unsupported until a qualified management IPv6 target
exists.
