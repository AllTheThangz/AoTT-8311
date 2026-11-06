# AoTT-8311 v2 r9: integrated firmware candidate

**Checkpoint:** November 6, 2026. **Identity:** `AoTT-8311-v2r9`, displayed as `AoTT-8311-v2 r9`.
**State:** integrated offline candidate. No r9 hardware trial or permanent commit is claimed.

## Purpose and shipped source

This revision brings the privately tested security-enhanced r8 runtime and the current configuration readback work into one buildable source tree. It resolves the split between r7-labelled public source and the separately maintained r8 monitoring implementation. The source manifest contains **89 runtime files**.

| Runtime feature | What r9 includes |
| --- | --- |
| Configuration status | Seven manual, administrator-only readback panels covering all 54 existing GUI fields |
| Management | Saved-versus-configured comparisons and independently observable kernel address, route and interface evidence |
| Device, PON and VLAN | Bounded device/SFP, PON/OMCI, advanced host and ISP/VLAN source checks with explicit unavailable or unverified states |
| Sensitive identity | Redacted status for nine identity/credential overrides; no values, hashes, lengths or fingerprints returned |
| Monitoring | Existing r8 optional UDP/TCP syslog controls, test-event feedback and disabled-by-default external metrics |
| Collector access | Existing HTTPS, peer/destination address and header-token checks, durable/live consistency, rotation and revocation |
| Monitoring persistence | Existing mounted-ptconf record and bounded restore through the vendor S11 hook before S12 logging |
| Security visibility | Existing r8 root-only HTTPS-key permission status, without reading or exporting key bytes |
| Release integrity | Unique r9 identity/cache labels, inherited monitoring/boot-link pins and mandatory pins for all 15 new readback files |

A saved value, a matching UCI field, an O5.1 state or a 10 Gbps host link does not prove full setting effectiveness or subscriber Internet service. Each panel preserves the limits reported by its underlying source. VLAN traffic-control evidence is unavailable without its required trusted native reconciliation record; the readback does not create that record or alter rules.

## Integration decisions

The configuration template and current browser JavaScript retain every readback group. The controller combines those routes with the inherited r8 monitoring routes and fail-closed collector handler. The inherited anonymous metrics implementation is not restored. The source also retains the r8 logging, persistence, security-status, native-runtime and browser tests.

The metrics token digest domain remains `AoTT-8311:v2r8:metrics:` intentionally: it is a credential-format compatibility constant, not a release display label. Monitoring storage schema and credential records are unchanged, so changing the displayed firmware revision does not invalidate an existing approved collector token.

Kernel, bootcore, proprietary OMCI/PON libraries, fixed bank geometry and native bank/upgrade code retain their qualified compatibility contract. All hardware compatibility statements remain limited to the existing LL-XS1010 / PRX126 profile; this is not a newly qualified board port.

## Development code outside the firmware

History collection and persistence, certificate generation/import, optional remote firewall, the C-013 recovery journal and C-014 native configuration transaction work remain available under `prototypes/`, `tools/` and `tests/`. They are not installed in the r9 overlay. This release does not advertise a working new VLAN setter, certificate-management GUI, background history service or additional hardware support.

## Offline build and runtime pins

Use the existing private, verified enhanced-r8 base with the reviewed r9 overlay. Keep generated images and vendor components outside this checkout. `tools/refresh_runtime_profile.py` defines `R8_CRITICAL_FILES`, `R8_CRITICAL_LINKS` and `R9_READBACK_CRITICAL_FILES`. The r8 requirements remain enforced after a revision bump. Every readback module and the fixed TC verification helper must have an explicit candidate file record matching the source manifest; missing or downgraded records are rejected.

The build sequence is source validation, overlay staging, independent private rootfs copies, reviewed pin refresh, deterministic 1 MiB-block XZ SquashFS, five-member archive assembly and independent pair qualification. The archive builder checks extracted source bytes/modes, release identity, protected runtime records, fixed kernel/bootcore identities and at least 64 KiB reserve inside the unchanged rootfs volume.

Two independent private firmware builds completed on November 6 with byte-identical SquashFS images and five-member upgrade archives. Each rootfs is **5,734,400 bytes**, leaving **487,424 bytes (476 KiB)** in the fixed 6,221,824-byte bank. All 89 source overlay files matched the independently extracted images; 184 runtime integrity records passed, with no unexpected changes outside the reviewed overlay and integrity profile. Kernel and bootcore hashes retained their qualified values.

Source, native-MIPS and browser regression receipts identify their exact source commit and are tracked with [draft PR #52](https://github.com/AllTheThangz/AoTT-8311/pull/52). Preserved, hash-pinned vendor CSS and pre-monitoring boot/logger fixtures make the source checks independent of optional files omitted from a sanitized test runtime. These fixtures are test inputs and are not installed in firmware. The actual private image/archive receipts remain with the maintainer. Offline build verification does not establish r9 hardware boot or forwarding acceptance.

## Hardware transition

A fresh independent read-only check on November 6 confirmed enhanced r8 active in bank B, original r8 committed in A, no pending activation and a running uncommitted trial. PON association, 10 Gbps host link and recovery credentials matched the private baseline. Exact hashes and receipts remain private. This observation is not r9 trial acceptance.

The latest private operator receipt determines the actual bank state before any later operation. Source integration does not change the ONU, provisioning, boot selection or firmware banks. A subsequent stage/trial uses the exact qualified r9 archive, fresh bank evidence and the existing distinct operational approvals.
