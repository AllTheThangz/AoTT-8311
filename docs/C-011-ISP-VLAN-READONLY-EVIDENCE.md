# C-011: Residential ISP/VLAN configuration readback

**Checkpoint:** November 2, 2026.
**Status:** Source-only and independently tested on host/vendor-MIPS/Chromium.
No new image was installed on the running ONU. This is not a working
VLAN repair, router diagnostics agent or service speed test.

## Scope and purpose

Extend the source-derived configuration readback from 24 to **27 of
54 existing GUI fields** by adding the three ISP VLAN settings:

| GUI field | Authoritative stored source | Additional evidence | Not proven |
| --- | --- | --- | --- |
| `fix_vlans` | Fixed `8311_` boot environment key, valid 0/1/2 | Read-only daemon presence, if available | That the daemon is translating traffic, that a hook ran or that current TC rules are correct |
| `internet_vlan` | Fixed boot environment key, valid 0-4095 | Optional value in the last native built-in reconciliation receipt | The actual current data-plane VLAN, traffic throughput or ISP connectivity |
| `services_vlan` | Fixed boot environment key, valid 1-4095 or unset | Optional value in the last native built-in reconciliation receipt | The OLT's service mapping or current multicast/IPTV traffic |

The code knows that absent `fix_vlans` defaults to built-in mode 1
and absent `internet_vlan` uses source default 0 (untagged). An
absent services VLAN depends on provider detection, so its effective
value must **never** be invented from a generic default.

The three modes are disabled (0), built-in mapping (1), and custom
hook only (2). Neither an active process nor the existence of a
historical reconciliation receipt guarantees traffic rules are
currently installed or even that a router has Internet access.

## Native reconciliation evidence

The existing upstream-derived built-in fixer publishes
`/tmp/8311-config.sh` after it finishes its own traffic-control
readbacks. The new read-only code does **not** execute or source this
file. It may inspect only the two fixed VLAN assignments plus the
topology state hash, and only when the file has all required security
properties:

- Regular file, not a symlink.
- Root-owned and mode 0600.
- Bounded to 4096 bytes.
- Unique required keys with strictly validated decimal ranges and
  a 64-character lowercase hexadecimal state hash.
- No executable source or arbitrary parameters accepted.

When a valid receipt is present, the source can perform a separately
bounded, read-only `8311-detect-config.sh -H` to compare network
topology to the hash recorded after the last reconciliation.

**The hash comparison does not prove live TC rules still match.**
It only indicates whether the topology signature changed since the
last recorded native reconciliation. Unrelated TC changes, an old
receipt, missing hook operations, a failed daemon or other traffic
problems can still exist. The API deliberately marks all individual
runtime effects, restart persistence and recovery as unverified.

On the tested PRX126, the `8311-vlansd.sh` process was observed,
but `/tmp/8311-config.sh` was absent. Therefore there was no
validated last-reconciliation record to compare. No actual VLAN
settings, PON identity or provisioning were exported in the test.

## Implementation

- `overlay/usr/lib/lua/8311/effective_vlan_state.lua`: pure Lua 5.1
  normalization, fixed-name receipt parser and evidence-labeled
  comparison. No device access or side effects.
- `overlay/usr/lib/lua/8311/effective_vlan_probe.lua`: fixed-key,
  bounded read-only boot-environment reads, root-owned receipt
  metadata gate, daemon-presence probe and optional read-only
  topology hash.
- Admin-only, GET-only `/cgi-bin/luci/admin/8311/effective_vlan`
  route with private no-store HTTP headers. No anonymous collector
  endpoint or write-capable handler.
- Manual **Check VLAN service state** view in the configuration page.
  Device-provided data are rendered via `textContent` and never
  interpreted as HTML. No periodic background probe.

This work leaves the existing `8311-fix-vlans.sh`, kernel traffic
control, provider OMCI provisioning, native hook script and current
network routes untouched.

## Validation requirements and failures checked

The deterministic host and vendor-MIPS Lua fixture verifies saved
mode 0/1/2 handling, unset defaults, malformed/oversized VLAN IDs,
reserved service VLAN zero, source drift, changes in the recorded
topology, missing receipt, stale daemon, invalid source metadata,
duplicate receipt keys, injection-like text and untrusted runtime
failures. All false-positive running/effective claims are forbidden.

Headless Chromium tests check manually triggered authenticated GET,
no background mutations, absent receipt and unknown daemon,
saved-versus-historical drift, unavailable or incomplete responses,
external URL refusal and safe rendering of adversarial text.

A complete source regression suite, native MIPS fixture, browser
fixture, source manifest and disclosure scan must pass on both the
private vNext source and an independently checked-out public r7
source branch before any public merge.

## Known limitations and next work

- **Not an independently verified traffic rule reader yet.** For
  actual A-to-Z VLAN functionality, add safe fixed-selector
  `tc filter get` readbacks and compare full installed rule
  content, without changing any unrelated traffic-classification
  rule or assuming a target VLAN from the OLT.
- No Internet routing test is performed by a bridging ONU. Real
  subscriber availability requires a separately configured
  routable probe or router-side integration.
- An unset saved override is not necessarily equivalent to an
  observed value, even when an upstream default exists.
- C-012 still owns positive/negative applies, rule readback,
  reboot persistence, provider service impact and recovery tests.
- The unrelated management VLAN `lct_vlan` remains hidden as
  broken and must not be silently exposed via this source code.
- Other **27** GUI fields still need independent readback and
  setting-specific test evidence.
- PON credentials, ISP identifiers and private full-bank backups
  remain excluded from public source and status APIs.

As with all previous C-011 milestones, this document does not
authorize firmware flash, reboot, selector changes or a permanent
commit. The enhanced r8 trial remains separate from public
r7-source development and its original-r8 committed fallback must
be preserved.
