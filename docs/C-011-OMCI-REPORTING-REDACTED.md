# C-011: Redacted OMCI reporting and software-image source readback

**Checkpoint:** November 3, 2026. **Scope:** authenticated, manual,
read-only firmware source changes. **Hardware qualification: OPEN.**

## What this adds

Ten additional existing GUI settings now have a bounded boot-environment
presence/format inspector, without showing the underlying strings:

| Field | Source check | Explicit limitation |
| --- | --- | --- |
| equipment_id | Stored OMCI-reported equipment/model text present and within 20 characters | Not proof of what the OLT received |
| hw_ver | Stored hardware-version text present, within 14 characters | Not a physical hardware revision |
| cp_hw_ver_sync | Stored on/off value within supported format | Not proof the Circuit Pack MIB was updated |
| sw_verA | Stored reported image A label, within 14 characters | Not the running firmware bank |
| sw_verB | Stored reported image B label, within 14 characters | Not the running firmware bank |
| fw_match_b64 | Stored input conforms to a bounded Base64 alphabet and padding | Not proof PCRE compiles or matches an OLT update |
| fw_match_num | Stored matching occurrence in 1..99 | Not proof the OLT update uses it |
| override_active | Optional reported active bank override A/B | Does not switch the actual boot bank |
| override_commit | Optional reported committed bank override A/B | Does not commit a firmware bank |
| pon_slot | Stored reported UNI slot in 1..254 | Not proof OMCI or GEM mapping accepts it |

The inspector independently compares the *reported software-version*
environment labels with the separate boot-image version labels
img_versionA and img_versionB, where both are available. It shows only
**labels match / labels differ / unavailable** and never displays either
string. Even a match does not prove which bank is running, that its
rootfs is valid, that the OLT accepted the label, or that a trial bank
is safe to commit.

Raw equipment identifiers, matching expressions, ROM/U-Boot labels,
actual active/committed bank environment selectors, PON serial,
registration ID, LOID/password, IP Host MAC, root credential hash and
the full boot environment are never returned by this inspector.

This raises the source-level C-011 readback count from **35 to 45 of 54**
existing GUI fields. The remaining nine are identity or credential
related: gpon_sn, vendor_id, reg_id_hex, loid, lpwd, iphost_mac,
iphost_hostname, iphost_domain and root_pwhash. They require deliberate
privacy and source-specific effective-value designs, not automatic
exposure of sensitive strings.

**C-011 remains IN_PROGRESS, not hardware-qualified.** C-012 still
requires validating actual setters, persistence, runtime effects and
recovery for every applicable field.

## Architecture

Two new Lua 5.1 modules:

    overlay/usr/lib/lua/8311/effective_reporting_state.lua
    overlay/usr/lib/lua/8311/effective_reporting_probe.lua

The first contains pure, bounded normalization and safe status
projection. The second reads only 10 fixed prefixed environment keys
and two fixed unprefixed boot-image version labels. No request
parameter or saved value can alter these native command arguments.

Each environment lookup uses the fixed read-only fwenv_get executable
under the 3-second timeout wrapper, with capped output size.
A manual complete refresh currently makes at most **12 individual
lookups**. The theoretical serial worst case can approach 36 seconds,
and actual device latency has not been measured. There is no
background polling, command write, OMCI MIB edit, image flashing,
bank change, device restart or WAN verification.

The authenticated LuCI-only endpoint is:

    GET /cgi-bin/luci/admin/8311/effective_reporting

It inherits the existing admin/8311 authentication tree, accepts GET
only, uses private no-store and nosniff headers, and returns a generic
503 on invalid source evidence. It never returns a raw saved value.

The configuration page contains a new, manual **Check reported-field
status** panel. Its DOM construction uses textContent and fixed labels.
It renders present/valid/invalid/unavailable source states, the
redacted image-label comparisons and an explicit unverified effect
message. It never prints raw identity strings, byte counters or
firmware labels, and it does not send a save request.

Two additional files are explicitly listed in the 81-entry source
overlay manifest. This is a source checkout update, not an
installation, compiled image, or live ONU change.

## Independent tests

From the repository root:

    lua5.1 tests/effective_reporting_fixture.lua overlay/usr/lib/lua
    python3 -m unittest discover -s tests -p 'test_effective_reporting.py' -v
    python3 -m unittest discover -s tests -p 'test_browser_effective_reporting.py' -v

The deterministic Lua fixture contains **1,269 assertions** on both
host Lua 5.1 and extracted vendor MIPS Lua under QEMU. It verifies
fixed-key access, 10 field boundaries, unavailable/malformed text,
valid Base64 padding, reported-vs-image-label comparison, and strict
non-disclosure of saved contents. It also executes the live adapter
with a synthetic intercepted native command provider.

The real Chromium suite validates the actual LuCI template section
and shipped 8311.js with a synthetic intercepted HTTP response.
It checks GET-only/manual behavior, 10 fixed status rows, no XSS or
raw-value display, unsupported claims rejected, source error handling
and refusal of external URL replacement.

The existing C-011, C-012, firmware-source and disclosure tests must
continue passing in the release CI workflow.

## Unresolved production work

1. Qualify the actual PRX126 as a directly authorized, recoverable
   administration target. Never route around the target allowlist.
2. Verify each boot environment getter, exact version-label source,
   parser and resource/time cost with real read-only hardware data.
3. Verify each OMCI reporting field independently against actual
   firmware-side MIB/OMCI behavior and where possible OLT responses.
4. Treat OMCI bank reporting separately from real firmware
   boot/commit state. A reported label is not proof of a valid bank.
5. Add safe, privacy-preserving evidence for the other nine GUI
   controls without returning registration or login secrets.
6. Complete setter, reboot persistence and alternate recovery tests
   before claiming end-to-end functionality or expanding to other
   XGS-PON sticks.

No active r8 trial bank, committed fallback bank, ISP registration,
PON identity or firmware image was changed by this work.
