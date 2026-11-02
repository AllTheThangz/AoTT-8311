# C-011 extension: device and virtual SFP effective-state comparison

**Status:** Source-only implementation, November 2, 2026. Not deployed to a
production XGS-PON stick, and not proof of full functionality.

## Purpose

Extend C-011 beyond the nine management settings to the four ordinary
device identity/time settings and seven host-visible virtual SFP EEPROM
settings found in the existing 54-field LuCI form.

Two small Lua 5.1 modules are added:

- `overlay/usr/lib/lua/8311/effective_device_state.lua`, a pure read-only
  interpreter that separates saved override, UCI configuration and
  independently observed runtime information.
- `overlay/usr/lib/lua/8311/effective_device_probe.lua`, a fixed-key
  adapter to existing environment/UCI readers and the running Linux
  hostname at `/proc/sys/kernel/hostname`.

The LuCI admin route `admin/8311/effective_device` is authenticated,
accepts GET only, does not cache responses and cannot write settings.
An optional, manually triggered panel on the existing Configuration
page shows the readback with safe text-only rendering.

## Coverage and evidence

| Existing GUI field | Configured source | Actual running evidence |
| --- | --- | --- |
| hostname | UCI system hostname | Independently observed kernel hostname from procfs |
| lang | UCI LuCI language | Not verified as active for this session |
| timezone | UCI system time-zone description | Not independently verified as the active local-time implementation |
| ntp_servers | UCI NTP server list | Not proof of synchronization, time quality, reachability or service state |
| sfp_vendor | UCI virtual SFP vendor_name | Does not prove actual router-visible EEPROM |
| sfp_oui | UCI virtual SFP vendor_oui | Does not prove actual router-visible EEPROM |
| sfp_partno | UCI virtual SFP vendor_partno | Does not prove actual router-visible EEPROM |
| sfp_rev | UCI virtual SFP vendor_rev | Does not prove actual router-visible EEPROM |
| sfp_serial | UCI virtual SFP serial_no | Does not prove actual router-visible EEPROM |
| sfp_date | UCI virtual SFP datecode | Does not prove actual router-visible EEPROM |
| sfp_vendordata | UCI virtual SFP vendor_data | Does not prove actual router-visible EEPROM |

This adds 11 source-level readbacks for **20 of the current 54 GUI
environment controls**, together with the nine original management
readbacks. It does not qualify the remaining 34 controls, and no
individual setting can be called hardware-verified solely from these
source tests.

For each setting, the API labels: saved value, UCI-configured value,
observed running value if separately available, comparison states,
evidence sources, a privacy classification and explicit false
qualification, persistence and recovery flags.

## Discoveries requiring further engineering

- The vendor startup program copies saved SFP fields into UCI
  `sfp_eeprom.default`, but matching UCI does not establish that the
  host router was presented those bytes, or that its EEPROM cache
  refreshed. A separate safe host-side readback is required.
- The board applies the hostname through a kernel hostname setter,
  making a read-only procfs check a meaningful independent observation.
- The time-zone field is written into UCI `system` configuration,
  but merely observing that string cannot prove time zone behavior.
- The saved NTP server list is copied to UCI at startup. A matching
  list does not prove time synchronization or accurate historical
  timestamps. A separately bounded synchronization-state probe is
  necessary before declaring NTP functional.
- The upstream-documented `device_sn` option is **not a functional
  setter in the current vendor backend**. The private source
  `_set_8311_device_sn` body is explicitly a no-op. The user
  interface must not present it as working without a separately
  qualified hardware implementation.
- `tx_en_mode` and `lct_vlan` remain high-risk advanced candidates,
  not ordinary working toggles. Do not enable them on the working
  production stick without independent physical recovery.

## Safety model

- No PON registration credentials, LOID, registration ID, root
  password hash, hardware calibration or full boot environment is
  read by the new probe.
- Only eleven named environment fields are queried. All UCI package,
  section and option choices are fixed in source. Nothing from
  the browser supplies a shell command or filesystem path.
- The kernel read is limited to the hostname. No SFP EEPROM hardware
  bytes are read, exported or guessed.
- Values from the authenticated API are never inserted into HTML.
  The browser uses textContent, rendering an embedded HTML string
  literally without executing it.
- No automatic background polling or active speed tests are added.
- Probe failure, malformed input, absent UCI value and multiple
  upstream NTP servers do not silently become a success.
- This change performs no setting write, service restart, firmware
  stage, reboot, A/B selection, permanent commit or rollback.
- Per-setting hardware confirmation, reboot persistence and
  recovery remain unqualified.

## Test contract

The synthetic portable Lua fixture exercises 168 checks on both host
Lua 5.1 and the vendor MIPS Lua runtime: exact source labels,
configured-versus-kernel hostname drift, saved/configuration
differences, NTP server order, malformed NTP lists, SFP virtual
identity changes, read failures, oversized values and misleading
UCI-only success.

Source-level Python tests verify no mutating backends or credential
readers, authenticated-only GET routes, complete 11-field mapping,
no auto-polling and source provenance. Real Chromium tests exercise
the shipped manual UI, request interception, clear distinction
between configured and observed, untrusted HTML escaping,
incomplete responses, server errors and external URL refusal.

These tests validate the source implementation, not its live
hardware deployment.

## Later source-only PON/OMCI extension

A separate authenticated, noncredential readback now compares four additional PON/OMCI saved and UCI settings while recording independent PON association without falsely asserting individual setting effects or ISP Internet health. Total C-011 source coverage is now 24 of 54. See [the PON/OMCI source readback](C-011-PON-OMCI-READONLY-READBACK.md).

## Resume

Continue C-011 with PON/OMCI and platform/system readbacks, then
C-012 positive/negative writes, persistence and recovery per field.
Any live deployment, boot, stage or commit must be separately
authorized, with the original r8 committed fallback preserved.
