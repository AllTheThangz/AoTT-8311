# C-011: Authenticated management effective-state readback

**Checkpoint:** November 2, 2026.
**State:** source-only implementation and read-only hardware observations. No
new firmware has been installed or committed because of this work.

## Purpose and design

The previous GUI can validate and durably save a firmware-environment
value without proving the *running* Linux network interface, route or
service actually changed. C-011 makes those evidence levels distinct.

Two new Lua modules are added:

- `overlay/usr/lib/lua/8311/effective_state.lua`: dependency-free,
  pure Lua 5.1 interpretation of saved, UCI-configured and independently
  probed kernel/runtime state.
- `overlay/usr/lib/lua/8311/effective_probe.lua`: read-only board-bound
  native probes using bounded `fwenv_get`, UCI read, `ip` and sysfs.
  Only known management keys and two fixed interfaces are accessed.

An authenticated, GET-only LuCI route at
`/cgi-bin/luci/admin/8311/effective_management` serves the result.
It is **not** added under an anonymous collector path, accepts no
configuration data, never writes settings and returns no full boot
environment. The configuration page offers a manual, nonpolling
"Check running values" comparison. It renders all returned values
through plain text rather than untrusted HTML.

## Currently covered settings

| Field | Saved value source | UCI configuration | Running effect and limit |
| --- | --- | --- | --- |
| ipaddr | 8311 environment | network.lct or network.mgmt | Independently observed kernel IPv4 address, only if an unambiguous interface is present |
| netmask | 8311 environment | active management section | Kernel CIDR prefix compared with configured netmask when readable |
| gateway | 8311 environment | active management section | Kernel management default next hop, or explicitly absent route; on-link/ambiguous cases remain unknown |
| dns_server | 8311 environment | active management section | UCI-configured only; resolver use and reachability not inferred |
| pingd | 8311 environment | not a proof of service traffic | Configuration visible; daemon existence does not prove ping delivery |
| ping_ip | 8311 environment | boot helper target | Runtime cached target may be observed, not proof of ping traffic |
| lct_mac | 8311 environment | active management section | Kernel sysfs MAC comparison, only when unambiguous |
| reverse_arp | 8311 environment | daemon config loop | Configuration visible, not proof of packets/neighbor updates |
| https_redirect | 8311 environment | uhttpd.main.redirect_https | UCI configured only until an independent HTTP response proves the redirect |

The interface selection distinguishes direct `lct` from the optional
VLAN-based `mgmt`. If both report IPv4 simultaneously or the actual
kernel state cannot be parsed safely, the response says "unverified"
rather than inventing a preferred effective interface.

## Each returned field

The read-only data schema distinguishes:
- Saved environment override, configured value and observed value.
- Evidence/source of configuration and kernel observation.
- Whether saved and configured values match.
- Whether configured and observed values match.
- Whether saved and observed values match.
- Whether a running effect has independent observation.
- Whether restart persistence, recovery and full hardware support
  have been proven (all remain **false** in this source milestone).

The UI explicitly says that source, UCI and cached-target observations
do not automatically mean a service is working. No field is marked
fully hardware-qualified by this feature.

## Security and privacy boundary

- The API inherits authenticated LuCI admin routing, uses GET only,
  `Cache-Control: no-store` and is not a public metrics endpoint.
- No user-provided shell command, interface or UCI key can reach the
  native probe. Only fixed known management names are used.
- The nine known management environment keys are read individually,
  never a complete boot-environment dump or a PON registration secret.
- All native reads are bounded; failures yield unavailable state.
- Returned local management addresses and interface MACs are intended
  only for the authenticated administrator. They are never embedded
  in public source snapshots or logs.
- No service restart, file write, reboot, routing change, bank action
  or automatic background sampler is performed.
- The readback button is manual to avoid expensive polling on the
  constrained ONU management CPU.

## Independent verification

The pure Lua fixture exercises saved/kernel mismatches, UCI-only
values, link ambiguity, VLAN mode selection, route absence, malformed
output, simulated read errors and source-only semantics.

At the November 2 checkpoint:
- **97 fixture checks passed** under both host Lua 5.1 and the actual
  vendor MIPS Lua runtime.
- **8 static/backend tests** passed, including auth route, no mutation
  and source read restrictions.
- **6 real Chromium tests** passed, including manual-only GET,
  no outside requests, script-injection escaping, incomplete response
  handling and no false effective claims.
- The complete private vNext source suite passed **421 tests** with
  zero skips and the source manifest/disclosure checks passed.
- A separate **read-only live PRX126 probe** found the configured
  management IPv4 and MAC consistent with the running kernel. This
  confirms those native read techniques on the tested device, **not**
  that the new vNext Lua UI/API has been installed or hardware-qualified.

## Source-only device and SFP extension

An additional authenticated, read-only panel has been implemented for 11 system and virtual SFP fields, bringing C-011 source-level readback coverage to 20 of the current 54 GUI fields. It distinguishes the independently observed kernel hostname from configured-only LuCI language, time zone, NTP server list and seven host-visible virtual SFP UCI entries. Neither NTP synchronization nor host-side EEPROM presentation is inferred. See [the C-011 device/SFP extension](C-011-DEVICE-AND-SFP-SOURCE-READBACK.md). No new firmware image has been installed by this source work.

## Known limitations and next work

- This source change is not installed on the live r8 trial. A real
  production API/GUI hardware acceptance and independent postboot
  readback are still needed before calling C-011 fully hardware-done.
- C-011 currently covers the nine management settings, not all 54.
  Expand the same schema/backend/effective-evidence contract to every
  supported PON, OMCI, VLAN, SFP and system control.
- `lct_vlan` remains deliberately hidden and unqualified. Read-only
  recognition of a management VLAN does not constitute a safe
  setter or migration/revert procedure. Investigate under C-014.
- `device_sn`, `tx_en_mode` and `factory_mode` remain unverified
  missing/advanced candidates.
- Service proof for DNS, ping, reverse ARP and HTTPS redirect requires
  independent bounded probes, without assuming daemon existence or
  a UCI match is enough.
- C-012 owns full per-setting write, persistence, failure and recovery
  tests, and cannot be satisfied by this read-only milestone.
- The future board-adapter layer should replace hardcoded management
  interface names after separate board-level qualification.

## Resume instructions

Continue with source validation for the remaining effective consumers
under C-011 and a comprehensive per-setting C-012 test matrix.
Do not change the live ONU or commit its r8 trial without a separate
specific authorization and fresh native readback. The original r8
in bank A must remain the committed fallback until deliberately
replaced by an independently qualified commit.
