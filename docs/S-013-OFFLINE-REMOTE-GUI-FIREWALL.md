# S-013: Optional residential remote management with bounded firewall preview

**Checkpoint:** November 3, 2026. **Status:** IN_PROGRESS / offline source-validated only.
No live PRX126 configuration, network access, firewall execution or A/B bank action.

## Residential purpose

AoTT-8311 is an XGS-PON bridge. Remote access to its management GUI is
an optional convenience, not a universal enterprise security requirement.
Its default remains **local-only management** with remote GUI access
**disabled**. A router-hosted VPN is normally preferable to directly
exposing the ONU's web server. Users may still configure narrowly scoped
remote access if they explicitly choose it and the actual hardware is
qualified for that use.

This is a basic Linux firewall policy for the management GUI only.
It is **not** a router firewall redesign, subscriber traffic filter,
OLT provisioning feature, cloud management dependency, SSH-access
shortcut or an Internet-availability monitor.

## Vendor source evidence

The extracted security-enhanced AoTT r8 vendor rootfs contains a
working ELF program at /sbin/fw3 and a regular /etc/config/firewall file.
The extracted firewall config declares the named wan zone with
default input REJECT and leaves LAN input ACCEPT. The vendor's existing
uhttpd configuration still contains dual-stack wildcard listeners
as documented in S-012.

These source facts do not prove actual runtime firewall rules,
interface-to-zone mapping, support for all iptables/ip6tables paths,
management traffic routing, upstream Internet reachability or
packet-filter application to the XGS-PON forwarding dataplane.

The offline source probe reads only the fixed extracted firewall config
and checks for an installed fw3 binary. It neither invokes fw3 on a
live host nor reads or changes an actual subscriber firewall.

## Implemented source-only candidate

Source: tools/s013_remote_gui_policy_offline.py

Tests: tests/test_s013_remote_gui_policy_offline.py

The model's default policy has remote GUI disabled and no rules enabled.
A simulated operator request must explicitly confirm enabling remote
management and contain a strict set of fields:

- Numeric HTTPS listener port, default 443, with optional qualified
  high-numbered custom TCP port. SSH and plain HTTP ports are excluded.
- Fixed, known ingress firewall zone, never an arbitrary shell string
  or the local trusted LAN zone.
- One or more exact IPv4/IPv6 source CIDRs, at most eight in total.
  IPv4 /24 or more specific and IPv6 /64 or more specific
  are permitted. Internet-wide CIDRs, overlapping ranges, unintended
  IP families, invalid/ambiguous sources and unqualified link-local
  sources are refused. This is a conservative starter scope, not a
  blanket claim that any accepted source address is routable.
- An explicit independently verified local management target IP for
  each enabled family. Wildcard, loopback and link-local destinations
  are excluded.
- A 60- to 300-second rollback deadline, 120 seconds by default.

The generated fw3 UCI rule candidates each contain:
config rule, a fixed generated name, enabled=0, src=<ingress zone>,
src_ip=<operator CIDR>, dest_ip=<management IP>, dest_port=<HTTPS port>,
proto=tcp, family=ipv4 or ipv6, target=ACCEPT.

The candidate does not include forwarding, NAT/DNAT, OLT, OMCI, PON,
VLAN, LAN zone, bridged service, shell commands or autoactivation.
Every generated rule is disabled. The default CLI source probe emits
redacted counts and fixed status codes, not source addresses or
management identities.

**Important:** A returned UCI candidate is a SOURCE-ONLY preview.
Neither a runtime UCI setter nor a real installed on-stick GUI/action
is provided. The model is incapable of activating rules itself.

## Offline admission and rollback model

An offline synthetic scenario can only become
SOURCE_TRIAL_PLAN_READY_NOT_DEPLOYED after separately confirmed facts
indicate that the actual device would have:

1. A working, authenticated HTTPS listener on intended management paths.
2. Trusted local management recovery and an independent alternative
   recovery route.
3. An actual fw3 backend and correctly mapped ingress zone.
4. A default-deny input policy, no other broad allow rules, and
   noninterference with bridged XGS-PON forwarding.
5. A verified firewall/config backup, independent restoration method,
   and watchdog that can roll back if the administrator's session drops.
6. Independent remote test vantage points to verify both allowed and
   denied connections, including the configured IPv4/IPv6 families.
7. A verified negative remote policy for any IP family that is not
   explicitly enabled.

An injected synthetic trial must observe all of:
trusted local management connectivity, allowed remote connectivity,
denial of an unlisted source, and *subsequent* operator confirmation,
within the bounded rollback interval. Missing, contradictory, late,
duplicate or unsafe observations return SOURCE_TRIAL_ROLLBACK_MODEL.
This is a **simulation** of the required state machine, not a running
timer, background watchdog, or verified real-world firewall change.

A source trial result cannot authorize firmware stage, service reload,
firewall activation, or final commit. It is explicitly tagged
SOURCE_TRIAL_VERIFIED_SYNTHETIC_ONLY when all synthetic checks pass.

## Source validation and limitations

The focused offline suite covers opt-in refusal, default-off state,
source CIDR parsing/overlap/family/width, explicit WAN/ingress scope,
wildcard rejection, HTTPS-only port rules, disabled fw3 UCI text,
no forwarding/NAT writes, full/missing IPv4 and IPv6 evidence,
absent local recovery, denied source reachability, pending/expired
trial, premature/missing confirmation, and vendor fw3 source presence.

Actual remote reachability is unknown. In particular, the upstream
router, provider firewall, NAT, IPv6 exposure, host Ethernet bridging,
the stick's management routing and OpenWrt zone semantics could prevent
or unintentionally broaden access. Only direct on-device configuration
and genuine trusted/untrusted packet-level tests could resolve that.

## Production acceptance before ANY real enablement

1. Establish a directly authorized, recoverable PRX126 management
   target, read exact active bank/rootfs fingerprint and preserve the
   known committed fallback.
2. Read live listener addresses, socket owners, kernel/firewall state,
   network-to-zone mapping, IPv4/IPv6 ingress interfaces, HTTPS and
   SSH service health and router topology without writes.
3. Confirm there is no conflicting catch-all input allow rule and that
   the requested fw3 rules act solely on management INPUT, not
   FORWARD/bridge/OLT/control traffic.
4. Independently verify that locally reachable management remains
   available on an alternate path when the rule is staged, including
   after session loss and service restart.
5. Implement a separate guarded operator action with exact revision,
   root-only backups, a true watchdog independent of LuCI, bounded
   timeout, automatic restore, and clear cancellation behavior.
6. After explicit separate authorization, test an approved source and
   an unlisted source from genuinely independent remote vantage points
   for IPv4 and IPv6, then require final confirmation before the timer.
7. Test denied-by-default reboot behavior, S-012 local-only state,
   loopback/recovery access and no ISP/OLT/host bridge regression.

No optional remote metrics exporter, SSH exposure or syslog destination
is enabled by S-013. S-014 TLS key hardening and S-016 backup/restore
remain independent prerequisites for any live certificate/access change.

**No production device was accessed, flashed, rebooted, modified,
reconfigured, or connected through this source development.**
