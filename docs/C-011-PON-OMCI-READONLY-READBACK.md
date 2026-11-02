# C-011: Noncredential PON/OMCI readback

**Checkpoint:** 2026-11-02. **Status:** Source-only, not deployed to the ONU.
This is a narrow addition to the previously verified management and
system/virtual-SFP readback modules. No firmware image was built, staged,
trial-booted or committed as part of this change.

## Purpose and scope

Provide read-only evidence for four existing PON/OMCI settings without
returning provider registration identities, credentials or raw PON CLI
output. These controls remain **source-level**, not fully qualified
setters on physical hardware.

| Existing GUI control | Saved source | Vendor configuration read | Independent runtime proof |
| --- | --- | --- | --- |
| `pon_mode` | Named `8311_` environment entry | `gpon.ponip.pon_mode` | Not established from UCI or PON O5.1 |
| `omcc_version` | Named `8311_` environment entry | `omci.default.omcc_version` | Not established from UCI |
| `iop_mask` | Named `8311_` environment entry | `gpon.ponip.iop_mask` | Not established from UCI |
| `mib_file` | Named `8311_` environment entry | `omci.default.mib_file` | A configured path does not prove `omcid` loaded that MIB profile |

Only supported optical modes, valid OMCC range, 0-127 IOP masks and
safely formed MIB paths under `/etc/mibs/` are compared. Malformed,
missing and unrecognized values remain explicitly unavailable.

A **separate** bounded native `pon psg` observation reports the
numeric PON registration state. O5.1 indicates optical association on
that read but **never** certifies each PON/OMCI configuration value,
subscriber throughput, external Internet connectivity or ISP service
provisioning. A CLI failure is unknown, not disconnected.

## Implemented source

- `overlay/usr/lib/lua/8311/effective_pon_state.lua`:
  deterministic Lua 5.1 comparison, range validation and bounded PON
  state parser, with no runtime I/O.
- `overlay/usr/lib/lua/8311/effective_pon_probe.lua`:
  fixed four-key environment/UCI queries and a bounded native PON
  registration query. It returns only validated values and state
  number, never arbitrary raw CLI output.
- An **authenticated-only**, **GET-only** LuCI admin route at
  `/cgi-bin/luci/admin/8311/effective_pon`; no anonymous metrics
  route or editable parameters.
- A manual `Check PON configuration` view on the existing
  Configuration page, with explicit saved-versus-UCI comparison and
  independent registration status. It uses `textContent`, not HTML
  injection, and does not automatically poll.

No PLOAM registration ID, LOID, logical password, PON serial, reported
OLT identity, root credential, full environment dump, device-specific
subscriber provision, private key or unredacted diagnostics is read
by these new components.

## Evidence levels

- **Saved override:** valid, fixed-key environment value.
- **Configured:** independently read native UCI entry.
- **Runtime observed:** only the bounded PON state from `pon psg`;
  this does not establish individual setting effect.
- **Unknown:** a missing or failed native read, invalid format,
  multiple state keys or unsupported value.

All four controls deliberately declare
`runtime_effect_proven=false`,
`persists_across_reboot_proven=false`,
`recovery_proven=false` and
`hardware_qualified=false`, even when saved and UCI match.

## Tests and acceptance

The synthetic portable Lua fixture includes positive and negative
cases for normal values, normalized aliases, saved/UCI drift,
MIB path traversal, invalid OMCC/IOP ranges, missing/ambiguous
PON state and native read errors.

Real Chromium tests cover the shipped UI, manual authenticated
GET-only request, no background poll or external requests, text-only
escaping, distinct O5.1/Internet semantics, server errors,
unavailable state keys omitted by Lua JSON encoding, and incomplete
payload handling.

The source is cross-checked with the fixed vendor configuration paths
and native CLI supported by the reference PRX126 board.
A clean source test is **not** a production deployment or
an independently proven OMCI daemon runtime readback.

## Total C-011 scope and remaining work

This addition initially raised source readback coverage from **20 to 24 of 54** existing GUI fields. A later [ISP/VLAN read-only source extension](C-011-ISP-VLAN-READONLY-EVIDENCE.md) adds three more fields, bringing the current total to **27 of 54**. The other **27** controls still need a truthful
per-setting saved/configured/effective-state contract.

The remaining controls include authentication and reported OLT identity
data. Their secrets must never be exposed by an ordinary status API.
OMCI MIB readback, applied service/VLAN transformations and
credential-sensitive settings require appropriately scoped
read-only/hash/status evidence and separate spare-hardware testing.

Upcoming work:
- C-011: other PON/OMCI and ISP/VLAN diagnostics without credentials.
- C-012: per-setting validation, apply, negative tests, effect,
  reboot/bank persistence and recovery evidence.
- C-014: previously broken management VLAN with alternate recovery.
- H-011: bounded in-memory throughput and PON/Internet-path history.

The current enhanced r8 trial must remain uncommitted in bank B with
original r8 committed in A unless independently authorized.
No source-only milestone grants permission to flash or reboot.
