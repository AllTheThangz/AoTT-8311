# S-012: Local management listener isolation, offline policy evidence

**Checkpoint:** November 3, 2026. **Status:** IN_PROGRESS, source-only
verification. **No direct PRX126 authorization or hardware acceptance.**

## Residential requirement

AoTT-8311 should expose the management GUI only through intended local
management paths unless the user separately enables and qualifies remote
access. It is a residential XGS-PON bridge, not an enterprise firewall.
Management interface restrictions must not interfere with subscriber
forwarding, OMCI, the OLT, or the host-side dataplane.

## Source finding from extracted security-enhanced r8 rootfs

The extracted vendor 'etc/config/uhttpd' defines four wildcard listeners:

- IPv4 HTTP port 80 bound to the unspecified IPv4 address
- IPv6 HTTP port 80 bound to the unspecified IPv6 address
- IPv4 HTTPS port 443 bound to the unspecified IPv4 address
- IPv6 HTTPS port 443 bound to the unspecified IPv6 address

The vendor 'etc/init.d/uhttpd' passes 'listen_http' entries as '-p'
arguments and 'listen_https' entries as '-s' arguments to the uhttpd
process. The UCI 'rfc1918_filter' setting is a DNS-rebinding safeguard,
not a listener-isolation ACL. An HTTPS certificate or login is likewise
not proof that a listener is inaccessible from an unintended interface.

A wildcard bind is an **exposure risk requiring qualification**. It does
not by itself prove the actual GUI is reachable from the customer's
Internet side. The network path, packet filter, runtime process,
kernel socket ownership, physical interfaces and external vantage
points must all be checked separately.

## Implemented offline analysis

Source: 'tools/s012_management_isolation_offline.py'

Tests: 'tests/test_s012_management_isolation_offline.py'

The tool parses bounded UCI listener declarations, including multiple
uhttpd instances, and categorizes numeric IPv4/IPv6 HTTP and HTTPS
endpoints. It rejects malformed, duplicate, wildcard, ambiguous,
unqualified or mismatched addresses and listeners that do not belong
to an independently supplied local management address inventory.

For additional *synthetic* evidence it can compare:

1. Configured UCI listener endpoints
2. Separately supplied '/usr/sbin/uhttpd' process '-p/-s' arguments
3. Linux '/proc/net/tcp' and '/proc/net/tcp6' TCP LISTEN entries
4. Explicit trusted-management connection results for each endpoint
5. Independent negative connection results from the host dataplane
   and upstream WAN vantage points, for both IP families

The independent management IPs cannot be obtained merely by trusting
the same uhttpd UCI configuration under assessment.

The source decision is one of:

- **SOURCE_POLICY_REJECTED:** known unsafe or contradictory settings,
  such as wildcard binds, non-management binds, unexpected listening
  sockets, a reachable untrusted path or lost trusted recovery
- **SOURCE_EVIDENCE_INCOMPLETE:** required runtime, management-address,
  IPv4/IPv6, or trusted/untrusted reachability observations missing
- **SOURCE_ELIGIBLE_NOT_HARDWARE_QUALIFIED:** synthetic scenario satisfies
  the source policy but no live hardware proof is established

No result is named "safe in production" or "hardware qualified."
The report contains only counts and fixed reason codes, not customer
management addresses, observed ports, raw process argv, credentials,
socket details or hostnames.

If there is no IPv6 listener, a separately verified IPv6-disabled
state is required before source eligibility. Missing IPv4 listener
evidence is likewise not accepted as proof of isolation. IPv6 mapped
addresses and link-local listeners without interface scoping are
refused rather than optimistically treated as local-only.

The '/proc/net/tcp*' checks can corroborate socket endpoints, but a
socket snapshot alone does **not** prove which process owns each
socket inode. Process ownership, kernel IPv6-only/v4-mapped semantics,
network-namespace membership, routing and packet filtering remain
independent hardware gates.

## Reproduce the source-only vendor finding

On Hermes against an extracted, offline vendor rootfs:

~~~sh
python3 tools/s012_management_isolation_offline.py \
  --offline-vendor-rootfs /path/to/offline/extracted/rootfs
~~~

The script reads only the fixed 'etc/config/uhttpd' file in an
offline rootfs. It issues **no** SSH, network probe, uci write, firewall
command, uhttpd restart, reboot or firmware operation. A nonzero
status for these vendor defaults is expected, not a deployment failure.

Run source tests:

~~~sh
AOTT_VENDOR_ROOTFS=/path/to/offline/extracted/rootfs \
  python3 -m unittest discover -s tests \
  -p 'test_s012_management_isolation_offline.py' -v
~~~

Synthetic cases cover dual-family management binds, full and missing
evidence, IPv4/IPv6 wildcard binds, multiple uhttpd instances,
unexpected runtime endpoints, extra kernel listeners, malformed
/proc snapshots, unreachable trusted paths, untrusted connections,
ambiguous IPv6 absence, reserved/link-local endpoints, confidential
receipt redaction, and actual extracted vendor UCI syntax.

## Device activation gates

1. Get explicit authorization for an actual recoverable PRX126
   management session; separately verify firmware fingerprints and
   current A/B fallback.
2. Inventory real management addresses, netmask/VLAN/interface bindings,
   IPv4 and IPv6 route and socket ownership, firewall policies and
   alternative local recovery paths without changing anything.
3. Establish a trustworthy management-only binding strategy for uhttpd
   that does not break ONU/OLT/host access. Account for service startup
   ordering and interface-address changes before listener binding.
4. Run verified trusted-LAN and untrusted host/WAN ingress checks
   independently for IPv4 and IPv6. A single negative timeout, missing
   route or blocked path is not proof of universal isolation.
5. Stage any new listener/firewall behavior only after protected
   config backups, a timed rollback and verified alternate management
   access exist; require a separate explicit user authorization.
6. Verify actual uhttpd process, bound socket inodes, HTTPS login,
   redirected HTTP behavior, DNS-rebinding behavior, native CPU/RAM
   costs, reboot durability, firmware fallback and bridge forwarding.
7. Keep optional remote-access firewall controls (S-013) disabled by
   default and separate from the default local-only design.

**Not installed or activated:** No LuCI route, listener change,
uhttpd/service restart, firewall setting, ISP/OLT configuration,
certificate rotation, new firmware overlay file, NAND write,
bank stage, trial boot or permanent commit was performed.
