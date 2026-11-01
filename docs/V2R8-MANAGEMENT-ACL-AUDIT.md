# AoTT-8311 v2r8 management access and external monitoring ACL audit

Status: **offline source and extracted-vendor audit only**. This document does
not certify that monitoring is unreachable from untrusted interfaces on a
running ONU. No device firewall or network settings were changed.

## Observed vendor configuration

- The extracted OpenWrt `/etc/config/uhttpd` listens on wildcard IPv4 and
  IPv6 addresses for HTTP and HTTPS. `redirect_https=1` does not by itself
  mean that all routes are inaccessible over plain HTTP.
- The vendor `firewall` configuration has a WAN zone with inbound REJECT,
  but also a general default input ACCEPT. Effective restrictions depend on
  actual interface-to-zone assignments, generated runtime rules, and network
  routing. Static files are not proof of live enforcement.
- The vendor `/etc/init.d/log` exposes TCP and UDP forwarding through
  the existing logread process. A source-mocked procd test validates the
  command line for both transports; it is **not proof of receiver delivery**.
- The v2r7 fallback firmware does not implement r8's token-protected
  collector route. Returning to an old bank can restore its legacy route
  behavior, so network-layer management isolation remains essential.

## Layered protections implemented in the r8 draft

The public collector route is disabled unless configured. It requires
HTTPS at the vendor uhttpd socket, one **exact** configured source IPv4,
the actual local destination matching the configured untagged/tagged
management address, a separate 256-bit collector token sent in the
`X-AoTT-Metrics-Token` header, and matching durable/active token records.
Forwarded-For headers, URL query tokens, remote administrator credentials,
and IPv6 collectors are not accepted for this endpoint.

Administrative save and credential actions require LuCI authentication,
CSRF checking and validated inputs. The HTTP response is no-store and
does not include device provisioning or caller-supplied arbitrary labels.

None of those checks make an all-interface web listener equivalent to a
correct firewall configuration. Do not expand web exposure, introduce
wildcard firewall ACCEPT rules or automatically modify a user's management
network merely to make external scraping work.

## Hardware acceptance matrix

Before r8 can be merged for a supported production image:

1. On a recoverable test ONU with a known management address and working
   WAN/PON baseline, verify the effective iptables/firewall zone assignments
   and listening sockets. Record **redacted** output for local qualification.
2. Authorized collector: HTTPS from its exact configured IPv4 via
   trusted management transport; correct token returns only numeric JSON.
3. Denials: missing/wrong/revoked token, wrong source, wrong destination,
   HTTP, IPv6, replay after rotation, UCI/durable mismatch, and malformed
   request. Observe both API response and firewall reachability.
4. From untrusted/WAN ingress, ensure administrative and monitoring
   ports are blocked by the network firewall, not just HTTP credential
   checks. Test both protocol families and management VLAN variants.
5. Test routing, WAN connectivity, management HTTPS/SSH and the original
   PON state after syslog enable/disable, collector authorization changes,
   reboot, one-shot bank trial and recoverable rollback.
6. Validate that the previous firmware bank may have different web
   authorization behavior, and require management firewall isolation
   before switching banks.

The public project only documents how operators can connect **their own**
syslog server or Prometheus-compatible collector. It must not publish
real monitoring hosts, topology, subscriber identity or network addresses.

See [the monitoring design](MONITORING-AND-TELEMETRY.md),
[r8 implementation status](V2R8-IMPLEMENTATION-STATUS.md),
and the [external Prometheus adapter](../examples/monitoring/README.md).
