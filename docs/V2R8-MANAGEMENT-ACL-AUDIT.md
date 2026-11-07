# AoTT-8311 v2r8 management access and external monitoring ACL audit

Status: **source audit plus partial read-only hardware checks**. On the
running r8 trial, the public HTTPS collector route denied anonymous and
invalid-token requests with HTTP 403. Plain HTTP redirected and the
management HTTPS root remained accessible. The vendor web listener binds
wildcard IPv4; the WAN firewall zone is configured REJECT while the global
default input is ACCEPT. Effective untrusted interface filtering and IPv6
exposure are **not certified**. No firewall or network settings were changed.
See [hardware trial acceptance](V2R8-HARDWARE-TRIAL-ACCEPTANCE.md).

## Additional live socket, IPv6 and TLS evidence

Read-only kernel socket inspection confirmed wildcard listeners for
HTTP and HTTPS on **both IPv4 and IPv6**. The kernel recorded seven
link-local IPv6 addresses, no global IPv6 addresses and no IPv6 default
route. IPv6 was enabled. No applied IPv6 firewall ruleset could be
inspected with the available tools. Local link reachability and
WAN/untrusted ingress remain **unverified**, not demonstrated exposures.

The live application returned 403 for anonymous, invalid-token,
forged X-Forwarded-For and fake bearer metrics requests, 405 for
disallowed HEAD/POST methods, and redirected plain HTTP with 307.
These are management-side application results, not independent
network isolation tests.

TLS 1.2 and TLS 1.3 were both negotiable. The current management
certificate is self-issued, has no Subject Alternative Name, and
fails default certificate-chain verification. Certificate-chain trust
and management-hostname validation remain open hardening tasks.
Do not replace a production TLS identity without a verified recovery
path and separate operator authorization.

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

## Expanded trusted-management checks

From five independent hosts on the currently trusted management network,
the r8 management HTTPS root responded HTTP 200, anonymous external
metrics responded HTTP 403, and the same metrics route on plain HTTP
redirected with HTTP 307. These are consistent application responses
from multiple management-side clients, not proof that untrusted WAN,
another VLAN, or IPv6 link-local peers are unable to reach the listener.
No firewall, certificate, ONU configuration or bank selector was changed.

## Unattached WAN-zone mapping found in a later read-only audit

The current vendor-style OpenWrt firewall configuration defines a WAN zone
with inbound REJECT, but the zone refers to UCI networks named `wan` and
`wan6`. Neither network is defined as an interface in the inspected live
network configuration. The global input default is ACCEPT. A generated IPv4
fw3 print plan had no WAN-zone input jump from the INPUT chain. Its LAN
management mapping was present.

A new source-only audit checks the declared UCI interface names, the
WAN-zone input policy and optional generated firewall plan. On a sanitized
private live snapshot it returned CONFIGURATION_REVIEW_REQUIRED, with two
unresolved WAN-zone references and no generated WAN input hook.

This does not demonstrate Internet exposure. The device had only a
private-addressed management IPv4 interface in the inspected snapshot.
Other WAN-side pathways, bridge paths and IPv6 link-local ingress must be
assessed independently. Generated fw3 output is not a kernel ruleset
readback. Do not switch default input to REJECT or modify production
interface mappings without a recovery-verified change plan, since
management and PON services depend on inherited vendor routing behavior.

## Posttrial TLS private-key and source-NAT findings

A read-only live certificate audit found a self-issued ECDSA P-384 HTTPS
certificate with no Subject Alternative Name. Its validity dates were
current, but ordinary certificate trust failed. Even when the presented
certificate was explicitly trusted as an anchor during a temporary
in-memory verification, validation against the ONU management IP still
failed for an identity mismatch. A SAN-correct certificate and a
properly trusted issuer or anchor are both necessary.

The certificate and its private key live in persistent UBIFS. The key
was a root-owned regular file with mode 0644, making it readable beyond
root. The active web service ran with root UID. The draft read-only
Security & Access page now classifies key permissions, ownership and
symlinks without reading or returning key bytes or paths. It cannot
repair the live device. Any permission change or certificate replacement
requires independent rollback-verified operator approval.

Two simultaneous TLS connections from different trusted administration
hosts were observed on the ONU with distinct TCP source ports but the
same public source IPv4. This is source-address translation on the
tested management route. The exact-source-IP metrics allowlist cannot
distinguish those clients along that route; the independent 256-bit
bearer token remains mandatory. Before enabling external collection,
restrict the permitted collector at the upstream gateway before NAT or
establish a management path preserving individual client addresses.
Do not assume a shared NAT egress address uniquely identifies a
collector.

These read-only checks do not prove Internet reachability or an
authentication bypass. No TLS key content, network settings, UCI
configuration or firmware bank was changed.

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
   checks. Test IPv4, IPv6 link-local on the actual interfaces, and
   management VLAN variants. Confirm applied rules, not only fw3 output.
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
