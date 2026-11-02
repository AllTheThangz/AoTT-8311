# AoTT-8311 delivery backlog, sequencing and acceptance

**Baseline date:** 2026-11-02. **State:** roadmap with real evidence references and explicitly open work. This backlog is not a statement that planned functionality exists.

Status values: DONE_SOURCE, DONE_HARDWARE, IN_PROGRESS, NOT_STARTED, BLOCKED, CONDITIONAL. A task marked DONE_SOURCE remains unqualified on production hardware until DONE_HARDWARE evidence exists.

## Current verified completed milestones

| ID | State | Completion evidence and limits |
| --- | --- | --- |
| CP-001 | DONE_SOURCE | Static registry of 54 environment GUI fields and 13 vendor UCI config domains; exposes known disabled/missing candidates. No per-field hardware qualification |
| CP-002 | DONE_SOURCE | vNext Lua history math handles exact unsigned-64 counter deltas and bounded PON/Ethernet transitions; 53 fixture checks on host and vendor MIPS Lua. Not deployed |
| CP-003 | DONE_SOURCE | vNext 391 regression tests, zero skips, manifest/disclosure checks pass when run against appropriate reference vendor rootfs |
| R8-001 | DONE_HARDWARE | Security-enhanced r8 staged, booted and independently read back on one PRX126 device |
| R8-002 | DONE_HARDWARE | Original r8 in A protected as committed fallback; enhanced r8 trial active in B, both valid at last check |
| R8-003 | IN_PROGRESS | Updated r8/B trial still uncommitted; residential run-time acceptance and optional final commit decision remain open |
| CP-004 | IN_PROGRESS | Durable private project ledger and public-safe continuity documentation in progress in a separate docs branch |

All later tasks are open unless specifically updated with new test artifacts. Each work item should have an assignee before a release work cycle, but no assignee is invented here.

## P0: do not lose the working device or deceive users

| ID | Status | Deliverable | Pass criteria and dependencies |
| --- | --- | --- | --- |
| R8-010 | NOT_STARTED | Current residential trial acceptance | Confirm relevant OLT service, router Internet functionality where testable, operational UI, stable PON/host link and live recovery. No automatic B commit |
| C-010 | DONE_SOURCE | Reproducible source-derived capability registry | All 54 current GUI fields, backend namespace, source/line references, 4 hidden/missing candidates, 2 legacy aliases and 13 offline vendor UCI domains inventoried. 16 targeted tests pass on private r8 and public r7 source. Native runtime-qualified setters/effective states still belong to C-011/C-012. |
| C-011 | IN_PROGRESS | Backend read/effective-value contract | Authenticated source-only readback covers 27 of 54 GUI fields: nine management, eleven device/virtual SFP, four noncredential PON/OMCI and three ISP VLAN controls. The ISP/VLAN readback separates saved overrides, historical native reconciliation and independently unverified live TC rules. Other 27 fields, real service effects and hardware deployment remain unqualified. See [PON](C-011-PON-OMCI-READONLY-READBACK.md), [ISP/VLAN](C-011-ISP-VLAN-READONLY-EVIDENCE.md), [management](C-011-MANAGEMENT-EFFECTIVE-READBACK.md) and [device/SFP](C-011-DEVICE-AND-SFP-SOURCE-READBACK.md). |
| C-012 | NOT_STARTED | Table-driven positive/negative setting tests | Each exposed field validates, previews, writes, durably reads back and actually applies or clearly marks deferred effect |
| C-013 | NOT_STARTED | Persistence and recovery test matrix | Cover service restart, full boot, A/B transition where applicable, power loss/partial write and alternate management recovery |
| C-014 | NOT_STARTED | Repair management VLAN | Trace lct_vlan startup UCI, active bridge/device path, IP routes, UI and revert; finish real test before re-exposing |
| C-015 | NOT_STARTED | Audit missing device_sn and factory_mode | Verify real vendor support and effects, identity sensitivity, safe bounds; expose only after hardware qualification |
| C-016 | NOT_STARTED | Inventory remaining UCI/vendor settings | Classify 13 UCI domains plus runtime/OMCI/optics; provide read-only or unsupported explanation where necessary |
| C-017 | NOT_STARTED | GUI functionality and correctness audit | Every tab, option, chart, button, page, save, readback and error state operates in light/dark/mobile and authenticated paths |
| R-010 | NOT_STARTED | A/B identity and release build labels | All future builds have unique build ID and exact rootfs hash, not only an r8 string. Archive, UI and receipts agree |
| R-011 | CONDITIONAL | Explicit permanent B commit | Only after real acceptance, separate user authorization, fresh exact hashes, native full-bank checks and independent target approval |

**Order:** C-010 -> C-011 -> C-012 -> C-013. Investigate C-014/C-015 alongside registry work but never make the only production unit the first destructive test. C-017 tracks all UI controls. R8-010 is independent from vNext source work.

## P1: useful on-device historical diagnostics

| ID | Status | Deliverable | Pass criteria and dependencies |
| --- | --- | --- | --- |
| H-010 | DONE_SOURCE | Exact counter delta and state-change math | Portable Lua 5.1/MIPS fixture is already passing, not yet connected to runtime |
| H-011 | NOT_STARTED | Bounded data sampler | Single shared sampler, monotonic clock, sampled source identity, hard timeouts and measured CPU/RAM overhead |
| H-012 | NOT_STARTED | Optical/PON/Ethernet event capture | No O-state or host-link changes silently ignored; sample window and missing data explicitly tracked |
| H-013 | NOT_STARTED | Rate calculator integration | 64-bit correctness, RX/TX direction, counter-reset/reboot behavior and valid Mbps averages/peaks |
| H-014 | NOT_STARTED | RAM history ring and aggregation | Finite capacity, eviction, zero extra always-on heavy service and no secret/identity leakage |
| H-015 | NOT_STARTED | Persistent wear-limited history | Atomic bounded UBIFS summaries/events, power-cut recovery, cap/eviction, tested 7/30/90-day behavior |
| H-016 | NOT_STARTED | Historical GUI and exports | 1-hour/24-hour/7-day/30-day/90-day filters, outage table, throughput/signal charts, JSON/CSV |
| H-017 | NOT_STARTED | Separate WAN/ISP health integration | Optical, host-link and external reachability distinguishable; optional router management-side probe, DNS/HTTP latency and failures |
| H-018 | NOT_STARTED | Configurable history and alert thresholds | Operator-controlled interval, retention, event types, supported safe optical thresholds and disabled-by-default external alerts |
| H-019 | NOT_STARTED | Benchmark monitoring overhead | CPU/RAM, flash write rate, app latency, dropped network packets and PON stability versus baseline |

Dependencies: H-010 -> H-011 -> H-012/H-013 -> H-014 -> H-015/H-016. H-017 requires an actual routable probe or router-side integration and must not assert Internet uptime from PON O5.1.

## P1: certificate management and optional remote access

| ID | Status | Deliverable | Pass criteria and dependencies |
| --- | --- | --- | --- |
| S-010 | NOT_STARTED | Local certificate generator | Correct IP/hostname SAN, validity, key mode, safe old-cert backup and HTTPS reload |
| S-011 | NOT_STARTED | Import operator-owned TLS material | Cert/key/chain match, SAN and expiry validation, secure file handling, reject invalid uploads, restore on failure |
| S-012 | NOT_STARTED | Minimal local management isolation | Actual listener/interface restrictions verified from trusted and untrusted paths, separate IPv4/IPv6 evidence |
| S-013 | NOT_STARTED | Remote GUI opt-in and basic Linux firewall | Disabled by default, explicit enablement, source CIDRs and ports, IPv4/IPv6 as supported, safe cancel/recovery |
| S-014 | NOT_STARTED | TLS/key hardening | Correct read-only warning, private key root-only permissions without breaking web service |
| S-015 | CONDITIONAL | Optional remote syslog and collector acceptance | Only if configured: receiver acknowledgement for TCP where applicable, tested credential handling, correct NAT source restrictions |
| S-016 | NOT_STARTED | Config backup, restore and migration | Secrets masked in exports by default, explicit encrypted private backup for full restores, cross-bank recovery tests |

No enterprise CA or Prometheus infrastructure is required for default residential release. Any claimed Internet-facing remote GUI feature must prove exposure is limited to the configured sources.

## P1: performance and platform compatibility

| ID | Status | Deliverable | Pass criteria and dependencies |
| --- | --- | --- | --- |
| P-010 | NOT_STARTED | Repeatable performance baseline | Router-side measured throughput, latency, drops, loss, CPU/RAM/temps, sample intervals, WAN service configuration |
| P-011 | NOT_STARTED | Reduce redundant GUI/native polling | Bounded cache, shared expensive PON/GEM sampling, verified no fresh-data confusion |
| P-012 | NOT_STARTED | Safe host/SerDes and bridging tuning | Per-board supported settings only, throughput/drop improvement and tested recovery |
| P-013 | NOT_STARTED | Startup and failure recovery improvements | PON re-registration after outage, OMCI and management service watchdog behavior, no retry storms |
| P-014 | NOT_STARTED | Thermal and load soak | Sustainable throughput, no overheating/LOS, no PON flaps, no exhaustion of DMA reserves |
| P-015 | CONDITIONAL | Source/firmware size pruning | Static and late-loaded dependency proofs; no removal of PON/crypto/recovery and no unsupported universal build claim |
| X-010 | NOT_STARTED | Board-neutral capability adapter contract | Discovery, getter/setter/effective state, persisted action and recovery interface, feature flags |
| X-011 | NOT_STARTED | Hard-bound PRX126 reference adapter | All 54 UI fields and available UCI/OMCI controls mapped to real qualified hardware capabilities |
| X-012 | NOT_STARTED | Second PRX126 hardware profile | Actual board identity, ABI, optics, UBI geometry, backup/recovery, PON/OLT and tested trial |
| X-013 | NOT_STARTED | Cross-board configuration portability | Export/import only semantically supported fields, report unsupported conversions, never blindly copy secrets |
| X-014 | CONDITIONAL | CIG/Cortina/Realtek management adapters | Read-only where feasible, native firmware port only with separate kernel/bootcore/proprietary dependencies and hardware trial |

No port is called supported merely because its reseller uses XGS-PON, PRX126 or a compatible SFP+ form factor.

## P2: enhancements after the foundation is proven

- On-device anomaly explanations for recurring optical/thermal/link events.
- Multiple standardized external metrics exporters with no built-in customer destination.
- Provider/OLT compatibility profiles supported by independently tested setups, not hardcoded impersonation presets.
- Optional long-term remote history for users who run their own collector.
- Comparative safe tuning profiles with documented baselines and reasons for every enabled setting.
- More hardware families and maintainable board-specific build pipelines.
- Accessible help content hosted in source docs, with concise necessary runtime UI labels only.

## Mandatory verification matrix by work type

| Work type | Minimum source tests | Minimum hardware tests |
| --- | --- | --- |
| UI change | Real Chromium light/dark/mobile, sanitization, auth, invalid inputs, no dead button | Live navigation, save/readback when applicable |
| Configuration backend | Vendor Lua/shell fixture, rejected inputs, partial writes, stale revision, secret masking | Effective behavior, service impact, reboot persistence and restore |
| History sampler | Exact u64, reset/reboot, missing/corrupt samples, retention, clock uncertainty | PON/host transitions, actual storage consumption, thermal/load and power loss |
| Certificate/access | Pair/SAN/expiry/permission negative tests, rollback | Browser trust with intended local name, HTTPS restart, local recovery and optional external firewall probes |
| Performance optimization | Deterministic baseline, reproducible workload, regression profile | Real routed throughput, CPU/RAM, drops, latency, PON stability and thermal soak |
| New hardware profile | Architecture/ABI, partition and image bounds, backup verifier, refusal tests | Distinct target board, genuine OLT, stage/trial/recovery and service acceptance |
| Firmware release | Full regression, source manifest, disclosure scan, reproducible archive and capacity | Complete A/B readback, local network, PON, router WAN as testable, trial and separately authorized commit |

## Resource and scope constraints

Preserve the fixed partition layout, vendor PON microcode/OMCI and native packet forwarding until independently validated changes exist. Monitor CPU/memory and flash writes before adding a sampler. Proposed initial persistent history target is about 512 KiB with oldest-first eviction and infrequent batched writes; this is a hypothesis requiring real NAND wear and crash testing, not a proven limit.

Avoid mandatory external cloud dependencies, enterprise PKI, full databases, router features or "optimization" that simply raises apparent utilization. The provider's OLT controls bandwidth provisioning. The product's goal is better achieved service stability, diagnostics, recovery and interoperability.

## What to do next, without another planning loop

**First actionable source task:** C-010. Generate a canonical capability registry from all 54 GUI environment fields, identify each native consumer, attach backend/effect and risk metadata, and establish source tests that prove the schema and GUI agree. Keep each unqualified field visibly unverified.

**Second:** C-014. Investigate the hidden management VLAN through startup and UCI without modifying production management routes; design a hardware-safe migration/revert test.

**Third:** H-011. Integrate existing exact-rate/event math with a bounded nonpersistent sampler, then add deterministic gaps/reboot tests. No production writes.

**Parallel:** X-010 adapter specification; S-010/S-011 cert source tests; P-010 measurement harness.

**Separate operational decision:** R8-010, followed by R-011 only on separate explicit approval. Do not conflate r8 trial acceptance with vNext source development.

## Completion record for each ID

For each completed item, record: source branch/commit, changed files, unit/browser/vendor-MIPS test counts, hardware target and firmware fingerprint, actual readback/behavior, reboot/flash or no-mutation statement, recovery evidence, failure receipts, remaining limitations and next dependent work ID.

Never advance an item from NOT_STARTED to DONE_HARDWARE based only on an assistant statement or source test.
