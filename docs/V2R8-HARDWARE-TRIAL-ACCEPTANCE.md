# AoTT-8311 v2r8 hardware trial acceptance and monitoring baseline

Status: **one-shot hardware trial boot verified; permanent commit NOT performed**.

This report describes a controlled test of a qualified PRX126-SFP-PON
candidate. It deliberately contains no subscriber identity, serial number,
MAC address, public address, hostname, password, token, private backup,
private firmware archive, or management address.

## Recovery and boot result

The operator separately approved an inactive-bank stage and one-shot trial.
The private stage receipt and independent read-only postboot attestation
confirmed:

| Check | Observed result |
| --- | --- |
| Running firmware | AoTT-8311-v2r8 |
| Active bank | A |
| Committed fallback | Bank B, AoTT-8311-v2r7 |
| One-shot boot | Successful; boot identifier changed |
| PON registration | O5.1 |
| Ethernet host link | 10 Gbps |
| Management HTTPS and SSH/root recovery | Available |
| Primary WAN connectivity | Verified against privately pinned baseline |
| Both firmware banks | Complete native readback checks passed |
| Permanent commit | **Not performed** |
| Additional reboot or flash write during verification | None |

Complete off-device A/B bank backups were independently hashed, including
all six raw UBI volumes, before staging. The installed bank-A rootfs image
is **5,701,632 bytes** inside the unchanged **6,221,824-byte** fixed bank,
leaving **520,192 bytes (508 KiB)**.

These observations prove this *particular* staged image booted on the tested
hardware. They do not guarantee support for different vendor boards or
long-term stability.

## Read-only monitoring and telemetry observations

After the first successful r8 boot, the operator ran only read-only
management and diagnostic checks. No monitoring configuration, firewall,
credential, syslog receiver, or firmware bank was modified.

- The monitoring Lua module loaded on the real device.
- The persistent `/ptconf` volume was detected as mounted **UBIFS**.
- The vendor's pre-existing S11 startup link was present; the optional
  bounded monitoring restore hook was present in the installed sysctl script.
- The persistent monitoring directory and its record were both **absent**.
  This is consistent with an unconfigured monitoring feature, not a
  demonstration of restored settings.
- Metrics export and remote syslog forwarding were not configured. No
  collector token or remote log destination was provisioned.
- **Three bounded on-device telemetry samples** each returned all eight
  valid numeric measurements. Every sample reported PON O5.1.
- Optical receive power was approximately **-13.615 dBm**. Transmit
  power ranged from **6.226 to 6.261 dBm**. Optics temperature was
  approximately **40.56 C**. CPU sensor readings ranged from **48.68 to
  50.08 C**.
- An independent read-only SHA-256 comparison of **11 deployed runtime
  files** against the privately qualified r8 filesystem passed. Files
  included the monitoring modules, optional boot restore, LuCI controller,
  JS, vendor bank-control utility and runtime profile.
- Available memory was approximately **386 MiB** in these samples; idle
  load average was near **0.3 to 0.4**. These are observations, not
  concurrent load or throughput benchmarks.

### Bounded live native metric-function load test

A follow-up used four sequential reads and six additional reads with two
simultaneous clients on the actual running uncommitted r8 image. Every read
returned all eight valid numeric metrics and reported PON O5.1. The
median end-to-end read was **1.016 seconds** sequentially and **1.776 seconds**
with two concurrent readers. The slowest observed concurrent read was
**2.657 seconds**.

Available memory remained approximately **386 MiB** before and after.
The one-minute load average increased from **0.29** to **0.69** during the
short test. This is not a controlled CPU percentage measurement and does
not prove long-term stability, throughput, authorized HTTPS scrape
performance or the behavior of many simultaneous clients.

The read-only probes did not change settings, token state or firmware
selection. Avoid aggressive scrape concurrency; the optional off-device
cache and modest collection intervals remain recommended until a real
collector is qualified.

### Collector default-denial test

An external client on the trusted management side made unauthenticated
and intentionally invalid-token GET requests. Results:

| Request | HTTP status |
| --- | --- |
| Public collector route over HTTPS, no token | 403 |
| Same route with invalid token | 403 |
| Admin metrics route over HTTPS, unauthenticated | 403 |
| Public collector route over plain HTTP | 307 redirect |
| Device HTTPS root health check | 200 |

These responses show default-denial behavior for the tested management
path. They do **not** prove that the listening sockets are unreachable
from untrusted network segments. Authorized collector success has not
been tested.

### Expanded HTTP denial and TLS inspection

A second bounded check from the same trusted management side returned
**403** for an anonymous collector GET, a deliberately invalid collector
token, a spoofed X-Forwarded-For header, a fake bearer credential, and
an unauthenticated administrator metrics GET. HEAD and POST to the
collector route returned **405**. Plain HTTP redirected with **307**,
and the ordinary HTTPS management root returned **200**.

TLS **1.2** and **1.3** both negotiated successfully with the web service.
Those protocol tests deliberately skipped certificate trust verification.
The presented certificate was self-issued and had no Subject Alternative
Name. Default certificate-chain verification **failed** with a self-signed
certificate error. The dates on the certificate were current at the
time of testing; this does not establish trusted server identity.

This is a management certificate trust/identity hardening item. Plan a
properly scoped management certificate and trust distribution separately,
and verify the existing r7 fallback before changing production TLS files.
No certificate or listener settings were changed.

Untrusted or WAN-side reachability has **not** been tested by these
management-side requests.

## Firewall visibility and unresolved exposure

The vendor web service binds wildcard IPv4 interfaces. The local
configuration has default input **ACCEPT** and a WAN zone with input
**REJECT**. A compatible firewall frontend and kernel IPv4 tables were
present. The read-only generated `fw3 print` output included WAN-input,
reject and drop rule references, but this is a proposed rule listing, not
proof of the actual applied kernel rules. A live applied-rule comparison
was not completed. The WAN and IPv6 ingress exposure matrix
remains **unqualified**.

The live kernel socket table listed both **IPv4 and IPv6 wildcard
HTTP/HTTPS listeners**. IPv6 was enabled and forwarding was enabled.
A privacy-safe kernel address-scope count reported **seven link-local
IPv6 addresses**, **zero global IPv6 addresses**, and one loopback/host
address. No IPv6 default route was present. The usual ip6tables inspection
tools were absent and the kernel ip6tables names interface was unavailable,
so an applied IPv6 filtering policy could not be established.

These observations do **not** prove external IPv6 reachability. In
particular, no global address or default route was observed. However,
link-local addresses on multiple interfaces plus wildcard listeners
warrant controlled same-link and isolated-network ingress tests from a
real independent vantage point. Generated fw3 rules are not proof of
kernel-installed rules, and a successful TLS handshake from the trusted
management side is not a WAN firewall test.

No firewall, certificate, listener or network rule was added or removed
during these tests.

## Posttrial source-only UX correction

A source review of the Monitoring page found that a new, untouched r8
installation with no monitoring record displayed the same prominent warning
as a persistent-store integrity mismatch. This is a presentation issue, not
an observed collector authorization failure. The running, trial-booted r8
image still contains that original page.

The draft source now labels the verified-clean state as **Monitoring has not
been configured yet**, with a neutral notice. It only recognizes this state
when ptconf is mounted as the expected UBIFS volume, the private monitoring
directory is genuinely absent, and every active logging/collector option
is absent or at its disabled default. Missing records inside existing
directories, incorrect mounts, symlinks, non-default settings and actual
durable/live mismatches retain an alert and remain denied for metrics access.

Both actual vendor MIPS Lua runtime and synthetic negative tests passed.
**This posttrial source edit is not on the running ONU**, has not been rebuilt
into a qualified firmware image and does not inherit the current trial's
hardware acceptance. It requires its own build and qualification before
any future deployment. No live configuration, bank or reboot was changed.

## Follow-up read-only management-vantage check

After the original hardware trial, five independently addressed hosts on
the established trusted management network each obtained HTTP 200 from
the management HTTPS root, HTTP 403 from the anonymous external metrics
route, and HTTP 307 from the plain HTTP external metrics route. All hosts
reached the same running r8 trial without changing configuration.
This adds application-denial coverage across multiple trusted clients.
It does **not** qualify untrusted VLAN, WAN, IPv6 link-local, or actual
kernel-installed firewall behavior.

## Source-only posttrial image reproducibility

A subsequent draft-only source correction strengthens clean-install
classification and the normal-save/rotation consistency gate. Two
independent unflashable offline SquashFS builds from the saved r8
filesystem, with the revised source and a stricter embedded integrity
profile, matched byte-for-byte at 5,705,728 bytes. Both leave
516,096 bytes of fixed-bank capacity, and critical member readbacks
matched their source inputs. The reproducibility retry used normalized
source directory timestamps; the earlier mismatched pair was rejected.

The draft source passed 369 tests without skips, including 54 real
Chromium/Playwright browser tests and private vendor runtime fixtures.
This only proves offline source and image properties. The deployed
hardware trial remains unchanged, no complete flashable upgrade tar was
created and no permanent commit occurred.

## Later security and monitoring qualification

A sanitized read-only live UCI/fw3 inspection found an unattached WAN
firewall zone: the configured `wan` and `wan6` network references were
not defined as UCI interfaces in the inspected running configuration.
The default input policy was ACCEPT, and the generated IPv4 fw3 plan
contained no WAN input jump. One management IPv4 interface was active.
This is **not** an actual kernel rule dump, untrusted ingress test or
proof of Internet reachability. The firmware and firewall were untouched.

The external Prometheus JSON adapter passed three additional isolated
live-socket HTTPS tests on the off-device build host. A short-lived
local test CA established TLS trust; valid credentials returned numeric
Prometheus metrics, revoked credentials failed without stale data and
an untrusted certificate prevented requests. No live device token was
generated or used.

The draft Monitoring page also gained an explicit, authenticated
revoke/reset action for an invalid writable persistent monitoring
record when there is no active token. This remains a source-only
correction. The now-expanded suite passed 379 tests with no skips,
including 55 real Chromium/Playwright cases.

The corrected posttrial private SquashFS image pair was reproducible,
with each image 5,705,728 bytes and 516,096 bytes of bank headroom.
The images are offline-only and cannot be installed from these
qualification results. No trial firmware was changed.

## Later TLS-key and source-NAT observations

Additional read-only posttrial checks observed a root-owned HTTPS
private key with mode 0644 on the persistent UBIFS volume. The
current uhttpd service ran as root; restricting private key access
should be qualified and operator-approved with recovery available.
No key contents were copied, no permissions were changed, and the
certificate was not replaced.

The current self-issued management certificate has no SAN and fails
both default validation and validation after explicitly trusting
the certificate because its management identity does not match.
A qualified replacement needs a matching SAN and trusted issuer or
anchor without disabling verification.

Two simultaneous trusted management hosts appeared at the ONU under
the same public source IPv4 due to translation. Source-IP allowlisting
alone cannot distinguish these hosts; the independent collector token
remains necessary. Qualify gateway filtering before address
translation or a management path preserving source addresses.

The new key-permission and NAT-warning UI is draft source only, and
not in either the original r8 hardware trial or the earlier frozen
posttrial image. This does not establish external or WAN-side exposure.

## Tests that remain necessary before release signoff

1. Explicitly authorized configuration of a real syslog receiver, followed
   by positive UDP/TCP receipt tests, negative receiver tests, and a safe
   restoration to the desired configuration.
2. An authorized exact-IP HTTPS collector, correct-token numeric JSON,
   wrong/revoked-token denial, wrong-source and wrong-destination denial,
   and concurrent scrape latency/resource measurements.
3. Actual durable-record write/readback, S11 restoration after a controlled
   restart, mismatched UCI/UBIFS denial, and interruption/low-space
   behavior. The current absence of a persistent record is not a failure.
4. Independent effective runtime firewall and network-segment exposure
   checks for both IPv4 and IPv6, including link-local access and legacy
   fallback behavior. Inspect actual kernel-installed rules, not only the
   generated fw3 plan. Establish management-certificate identity/trust.
5. Extended PON/WAN stability observation, load/thermal behavior, real
   browser monitoring UI checks, and an independently approved eventual
   permanent commit if the operator chooses one.

No further reboot and no permanent commit are authorized by this
document. A subsequent reset of an uncommitted one-shot trial normally
returns to the saved bank B.

See [the monitoring design](MONITORING-AND-TELEMETRY.md),
[the management ACL audit](V2R8-MANAGEMENT-ACL-AUDIT.md), and
[implementation status](V2R8-IMPLEMENTATION-STATUS.md).
