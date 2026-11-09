# AoTT-8311 delivery backlog, sequencing and acceptance

## Release integration checkpoint, November 7, 2026

| ID | State | Deliverable and evidence |
| --- | --- | --- |
| R9-001 | DONE_SOURCE | Integrated enhanced-r8 runtime and all 54 source readback contracts in an 89-file r9 overlay; [scope and integration decisions](V2R9-INTEGRATED-RELEASE.md) |
| R9-002 | DONE_SOURCE | Exact combined regression passed 1,304/1,304 with zero failures/errors/skips; two independent private builds matched byte-for-byte and final image/runtime qualification passed |
| R9-003 | DONE_HARDWARE | Exact qualified r9 staged into bank A, one-shot trial booted and independently accepted on one PRX126 while enhanced r8 remained committed in B |
| R9-004 | DONE_HARDWARE | Separately authorized guarded permanent commit of running r9 A; final active A / committed A / no pending / not trial, with no reboot or firmware rewrite; [hardware acceptance](V2R9-HARDWARE-ACCEPTANCE.md) |

The r9 release-integration lifecycle is complete for the tested PRX126 device. The repository remains source-only. Build-time `release.json` metadata intentionally retains `offline-candidate`; later hardware qualification is recorded in the acceptance document rather than rewriting historical build evidence.

## V3 completion hardware-trial checkpoint, November 9, 2026

| ID | State | Deliverable and evidence |
| --- | --- | --- |
| V3-HW-001 | DONE_HARDWARE | Exact V3 completion tree `e5ac19d8938ec7cb48a9628f0e4019ae4a6d69b6` staged into B, verified before boot selection, one-shot trial booted, and accepted on the reference PRX126 while r9 remained committed in A |
| V3-HW-002 | DONE_HARDWARE | Postboot acceptance: active B / committed A / running trial; B exact-bank verification, V3 identity, PON O5.1, 10 Gbps host link, `omcid`, SSH, HTTPS, root/root GUI login, first-login advisory and authenticated V3 status all passed |
| V3-HW-003 | IN_PROGRESS | Permanent V3 commit is intentionally not performed; requires separate authorization after remaining desired live qualification |

The first V3 stage attempt failed closed because the live r9 installer used its older candidate runtime pins against the newer V3 rootfs. It left B incomplete and selectors unchanged. The exact V3 release profile was then supplied as volatile trusted qualification policy, read-only rootfs qualification passed, and the corrected stage/trial completed. This is deployment-tooling evidence, not a firmware-content failure.

Further C-012/C-013/C-014 hardware qualification, history/telemetry deployment, certificate/browser runtime acceptance, external remote-firewall packet-path proof, performance measurement and cross-stick support remain roadmap work. C-016 vendor capability discovery and C-017 GUI/backend source qualification are complete.

**Baseline date:** 2026-11-09. **State:** V3 completion image is hardware-trialed pre-commit, with remaining per-feature qualification explicitly open. This backlog is not a statement that planned functionality exists.

Status values: DONE_SOURCE, DONE_HARDWARE, IN_PROGRESS, NOT_STARTED, BLOCKED, CONDITIONAL. A task marked DONE_SOURCE remains unqualified on production hardware until DONE_HARDWARE evidence exists.

## Current verified completed milestones

| ID | State | Completion evidence and limits |
| --- | --- | --- |
| R9-001 | DONE_SOURCE | 89-file integrated r9 overlay with all 54 stored-source readback contracts |
| R9-002 | DONE_SOURCE | 1,304/1,304 combined regression; reproducible private build pair; final image and runtime-profile audit |
| R9-003 | DONE_HARDWARE | Exact r9 A one-shot trial verified on one PRX126; PON O5.1, 10 Gbps, recovery, both banks and immutable runtime checks passed |
| R9-004 | DONE_HARDWARE | r9 A permanently committed without reboot or firmware rewrite; enhanced r8 remains valid in B |
| CP-001 | DONE_SOURCE | Static registry of 54 environment GUI fields and 13 vendor UCI config domains; exposes known disabled/missing candidates. No per-field hardware qualification |
| CP-002 | DONE_SOURCE | vNext Lua history math handles exact unsigned-64 counter deltas and bounded PON/Ethernet transitions; 53 fixture checks on host and vendor MIPS Lua. Not deployed |
| CP-003 | DONE_SOURCE | Historical vNext regression milestone; superseded for the r9 release by the 1,304-test combined acceptance run |
| R8-001 | DONE_HARDWARE | Security-enhanced r8 staged, booted and independently read back on one PRX126 device |
| R8-002 | DONE_HARDWARE | Enhanced r8 ultimately committed in bank B as the verified recovery image before r9 staging |
| R8-003 | DONE_HARDWARE | Residential r8 runtime accepted sufficiently for recovery use; superseded as active firmware by committed r9 A |
| CP-004 | IN_PROGRESS | Durable private project ledger and public-safe continuity documentation continue as the roadmap evolves |

All later tasks are open unless specifically updated with new test artifacts. Each work item should have an assignee before a release work cycle, but no assignee is invented here.

## P0: do not lose the working device or deceive users

| ID | Status | Deliverable | Pass criteria and dependencies |
| --- | --- | --- | --- |
| R8-010 | DONE_HARDWARE | Historical r8 residential acceptance | PON/host link, Internet path where observed, management and recovery were accepted before enhanced r8 B became the committed recovery image for r9 |
| C-010 | DONE_SOURCE | Reproducible source-derived capability registry | All 54 current GUI fields, backend namespace, source/line references, 4 hidden/missing candidates, 2 legacy aliases and 13 offline vendor UCI domains inventoried. 16 targeted tests pass on private r8 and public r7 source. Native runtime-qualified setters/effective states still belong to C-011/C-012. |
| C-011 | IN_PROGRESS | Backend read/effective-value contract | Current V3 source readback contracts cover **55 of 55 GUI fields** after adding `lct_vlan` to the management group. The original committed-r9 54-field baseline remains historical; a separate value-free C-014 extension records the current untagged management-VLAN observation. Management DNS and VLAN now have independent netifd/kernel observations in source. This still does not make any field fully hardware-qualified. |
| C-012 | IN_PROGRESS | Per-field hardware qualification plan and positive/negative setting tests | The real full-schema contract now exercises **55 fields**. Forty-nine ordinary fields retain the generic transactional save path; the six management tuple fields are validated/previewed there but rejected before write and routed to their guarded transaction. The generated PRX126 matrix covers 55 fields in 4 lower-risk, 26 recovery-required, and 25 spare/test-OLT lanes. The [lower-risk readiness contract](C-012-SAFE-CANDIDATE-CONTRACT.md) now records all four lower-risk controls as source-ready for bounded live qualification with activation, runtime verifiers, and rollback contracts. Hardware qualification remains 0 until separately authorized live apply/effect/restore/reboot evidence exists. |
| C-013 | IN_PROGRESS | Persistence and recovery test matrix | The transaction/recovery fixtures retain their crash-safe journal, retained-file manifest and supervisor coverage. V3 now performs read-only admission of the intended /ptconf UBIFS recovery store and confirms sufficient byte capacity on the reference unit, but the fixed recovery directory is deliberately unprovisioned. Real journal writes, reboot persistence and power-loss qualification remain open. |
| C-014 | IN_PROGRESS | Repair management VLAN and guarded management tuple | V3 source now exposes `lct_vlan` and contains a production-scoped full management transaction for VLAN/address/mask/gateway/DNS/MAC. It creates persistent root-only rollback material before mutation, serializes with firmware/config writers, applies environment + UCI state, reloads network/firewall, verifies exact netifd/kernel address/route/DNS/MAC/VLAN convergence, waits 300 seconds for authenticated confirmation, automatically restores on failure/timeout, and recovers pending state at boot. Real Chromium verifies Configuration-page routing and confirmation UX. The source path is not yet hardware-qualified; no live management mutation was performed during development. |
| C-015 | NOT_STARTED | Audit missing device_sn and factory_mode | Verify real vendor support and effects, identity sensitivity, safe bounds; expose only after hardware qualification |
| C-016 | DONE_SOURCE | Inventory remaining UCI/vendor settings | Source discovery classifies 127 capability records across 13 vendor UCI domains and native Dropbear/uHTTPd consumers with zero unclassified records: 20 product candidates, 6 expert candidates, 13 test-OLT-only candidates, and framework/subsystem/dependency mappings. Promotion to product controls still requires the A-to-Z and hardware gates. See [C-016 vendor capability classification](C-016-VENDOR-CAPABILITY-CLASSIFICATION.md). |
| C-017 | DONE_SOURCE | GUI functionality and correctness audit | Generated C-017 gate covers 14/14 menu pages with real Chromium evidence, 24 POST write handlers and 4 mixed/multipart write handlers with explicit session+CSRF gates. Audit fixes include Support CSRF submission, Live Health copy, and normalized write-action checks. Hardware-specific reachability remains outside C-017. |
| R-010 | NOT_STARTED | A/B identity and release build labels | All future builds have unique build ID and exact rootfs hash, not only an r8 string. Archive, UI and receipts agree |
| R-011 | DONE_HARDWARE | Historical enhanced-r8 B commit | Completed under separate authorization before r9 staging; r8 B remains the intact recovery image after r9 A was later committed |

**Order:** C-010 -> C-011 -> C-012 -> C-013. Investigate C-014/C-015 alongside registry work but never make the only production unit the first destructive test. C-017 tracks all UI controls. R8-010 is independent from vNext source work.

## P1: useful on-device historical diagnostics

| ID | Status | Deliverable | Pass criteria and dependencies |
| --- | --- | --- | --- |
| H-010 | DONE_SOURCE | Exact counter delta and state-change math | Portable Lua 5.1/MIPS fixture is already passing, not yet connected to runtime |
| H-011 | IN_PROGRESS | Bounded data sampler | The [RAM history core](H-011-RAM-HISTORY-PROTOTYPE.md) passes 1,076 synthetic assertions. A [one-shot native PRX126 reader](H-011-ONE-SHOT-NATIVE-READBACK.md) uses fixed time-bounded PON and Ethernet commands with exact counters and validated boot/uptime windows, tested with mocked host and vendor-MIPS providers. No installed collector, live hardware acceptance, scheduled sampling, flash storage or measured load exists yet. |
| H-012 | IN_PROGRESS | Optical/PON/Ethernet event capture | [Offline partial-observation model](H-012-PARTIAL-PON-ETHERNET-OBSERVATIONS.md) independently tracks PON and host-link state through a failed opposite-channel probe, preserving observed transitions without false recoveries. Validated by 85 host and MIPS/QEMU scenario assertions. Actual native events, optical alarms, power-loss/reboot recovery and sustained hardware qualification remain open. |
| H-013 | IN_PROGRESS | Rate calculator integration | [Offline rate aggregation](H-013-H-014-RAM-RATE-AGGREGATION.md) computes duration-weighted host Ethernet RX/TX averages and sampled peaks from exact-64 source intervals, independently tracking missing directions and refusing cross-window, reboot or interface-spanning calculations. Real driver source/direction and hardware validation remain open. |
| H-014 | IN_PROGRESS | RAM history ring and aggregation | [Offline bounded RAM summaries](H-013-H-014-RAM-RATE-AGGREGATION.md) calculate retained coverage for 1-hour/24-hour/7-day/30-day/90-day queries directly across at most 720 samples, retaining 100-item raw export cap and privacy redaction. The summaries do not imply full requested retention or production collection; actual runtime memory/CPU and user-interface qualification remain open. |
| H-015 | IN_PROGRESS | Persistent wear-limited history | [Offline two-slot journal](H-015-OFFLINE-DUAL-SLOT-JOURNAL.md) defines <=160 KiB checksummed generations in A/B slots, a 15-minute routine-write guard, 2,160 hourly/256 event source caps, simulated tear/corruption fallback and synthetic 7/30/90-day clock-aware counts. No actual durable UBIFS adapter, NAND wear measurement, real power-cut recovery or runtime deployment is qualified. |
| H-016 | IN_PROGRESS | Historical GUI and exports | [Source-only history GUI and JSON/CSV exporter](H-016-HISTORY-UI-EXPORT.md) provide five selectable windows, observed host throughput, state-change/gap tables, dark/light contrast, bounded and privacy-filtered 100-item latest-epoch exports. No optical power chart, verified ISP outage duration, persistent records, installed LuCI route, running collector, or hardware qualification is claimed. |
| H-017 | IN_PROGRESS | Separate WAN/ISP health integration | [Offline router/WAN evidence model](H-017-INDEPENDENT-WAN-EVIDENCE.md) separates PON/host status from declared router test outcomes, bounded latency and history, without inventing ISP fault, full Internet health or cross-device timestamps. A real authenticated router-side probe adapter, reachability measurements, GUI and hardware acceptance remain open. |
| H-018 | IN_PROGRESS | Configurable history and alert thresholds | [Source-only 17-field residential preferences model](H-018-RESIDENTIAL-HISTORY-CONTROLS.md) provides disabled-by-default collectors/alerts/storage, validated intervals and RAM limits, revision-aware previews, synthetic board-gated optical thresholds, strict 15-minute minimum flash cadence and an accessible preview UI. Real saved settings, qualified collectors, optical alarm delivery, external notifications and on-device effect readback remain unavailable. |
| H-028 | IN_PROGRESS | Source-only publication-admission lock closes stale-cache collector-handoff race | [Offline H-028 independently locked reader admission](H-028-PUBLICATION-ADMISSION.md) requires a separate real fcntl publication lock *only after* validated first snapshot, checking both publisher and collector locks before and after reading. Real MIPS processes reproduce the old-JSON/new-owner race, competing holder and symlink refusal. No live runtime file, route, firmware change or verified PON/ISP health. |
| H-027 | IN_PROGRESS | Guarded lifecycle snapshot publishing and LuCI admin gate | [Offline H-027 lifecycle-to-IPC integration](H-027-GUARDED-LIFECYCLE-SNAPSHOT.md) publishes canonical bounded history only from the guarded collector, rate-limits refresh, invalidates cached data on controlled stop/start and denies stale data after crash through real fcntl lock checks. A source-only root-admin LuCI session gate rechecks local ubus facts. No real procd publisher, LuCI route, hardware qualification or live management change exists. |
| H-026 | IN_PROGRESS | Authenticated local history snapshot handoff | [Offline H-026 bounded history IPC and administrator read-only contract](H-026-LOCAL-HISTORY-READONLY-API.md) validate a root-owned guarded collector publishing at most 65,536 bytes via an atomic source-only file handoff to independent MIPS readers, strict nested schema, administrator-session GET gate and explicit same-origin browser loader. No on-device volatile tmpfs, installed LuCI route, live PON data, hardware authorization or runtime GUI activation is claimed. |
| H-025 | IN_PROGRESS | Read-only resource evidence and direct hardware admission | [H-025 source-only resource preflight and fail-closed evidence screen](H-025-HARDWARE-ADMISSION.md) verify extracted vendor MIPS32 ABI and bounded injected PON/host/CPU/memory/thermal parsing, reject unknown evidence and block production activation even with hypothetically in-range observations. Actual authorized PRX126 measurements, soak/traffic comparisons, qualified native runtime and deployment remain unavailable. |
| H-024 | IN_PROGRESS | Minimal supervised worker and termination safety | [Offline process wrapper and inert procd candidate](H-024-SUPERVISOR-OFFLINE-PROCESS.md) exercise real vendor-MIPS QEMU process shutdown, parent/worker crash, kernel-lock release, low priority, fd/core limits and bounded manual run. No real procd deployment, qualified on-stick RAM/CPU limit, PON-side native worker, or authenticated activation exists. |
| H-023 | IN_PROGRESS | Bounded collector lifecycle and restarts | [H-023 offline lifecycle model](H-023-COLLECTOR-LIFECYCLE.md) composes the actual vendor-nixio-guarded H-021 source collector with manual start/stop, 4-read failure threshold, finite 60/120/300-second restart cooldown, circuit breaker, verified boot handling and real competing MIPS/QEMU OS-process tests. A procd service, actual PRX126 kernel, traffic-load proof and authenticated runtime activation remain open. |
| H-022 | IN_PROGRESS | True cross-process collector ownership | [Extracted vendor-MIPS nixio/fcntl lock tests](H-022-CROSS-PROCESS-LOCK.md) verify a guarded H-021 collector, competing OS processes, stable inode, crash release and fail-closed root-owned file/dir checks. No real PRX126 kernel, procd lifecycle, runtime lock provisioning, native load or service-impact qualification is complete. |
| H-021 | IN_PROGRESS | Independent channel cadence | [Offline H-021 independent selective sampling](H-021-INDEPENDENT-PON-HOST-CADENCE.md) separately schedules due PON and Ethernet native read-only probes with not_sampled vs unavailable semantics, exact counter-to-counter elapsed rates, reboot identity verification and no false WAN outage inference. A physical PRX126 target, real performance proof, H-022 lock installation, supervisor and authenticated runtime deployment remain open. |
| H-020 | IN_PROGRESS | Shared bounded collector integration | [Offline single-owner collector](H-020-SINGLE-COLLECTOR-INTEGRATION.md) connects H-011 native one-shot, H-012 RAM state, H-014 rates and H-016 sanitized exports through one manually ticked Lua owner with backoff, retry and event-noise guards. Native PRX126 readback, H-021 independent cadence deployment, H-022 lock installation, a qualified supervisor and authenticated LuCI runtime remain unimplemented. |
| H-019 | IN_PROGRESS | Benchmark monitoring overhead | [Offline resource benchmark](H-019-RESOURCE-QUALIFICATION.md) runs 2,500 mocked H-011 reader cycles under host Lua and vendor-MIPS QEMU with finite ring retention, repeatable CPU/heap and host RSS measurements. Actual PON/ethtool cost, hardware CPU/RAM, flash wear, thermals, forwarding, latency and no-regression acceptance remain unqualified. |

Dependencies: H-010 -> H-011 -> H-012/H-013 -> H-014 -> H-015/H-016. H-017 requires an actual routable probe or router-side integration and must not assert Internet uptime from PON O5.1.

## P1: certificate management and optional remote access

| ID | Status | Deliverable | Pass criteria and dependencies |
| --- | --- | --- | --- |
| S-010 | DONE_SOURCE | Local HTTPS certificate generator | Authenticated HTTPS-only px5g candidate generation and guarded activation are integrated with persistent backup, 180-second browser confirmation, automatic rollback and boot recovery. EC P-256/RSA-2048 generation supports bounded DNS/IPv4 SANs. Hardware/browser trust acceptance remains open. |
| S-011 | DONE_SOURCE | Import operator-owned TLS material | Production V3 now accepts bounded PEM/DER leaf/key plus optional issuer chain through a root/HTTPS/CSRF-gated multipart route. It validates SANs, validity, RSA/EC/signature policy, CA structure/order/path limits, proves the exact cert/key pair with vendor uhttpd on loopback, then feeds the existing guarded candidate activation/rollback transaction. Browser trust/revocation remain runtime acceptance items. See [V3 TLS import qualification](V3-TLS-IMPORT-QUALIFICATION.md). |
| S-012 | IN_PROGRESS | Minimal local management isolation | [Offline S-012 local listener policy](S-012-OFFLINE-MANAGEMENT-ISOLATION.md) confirms source r8 uhttpd wildcard IPv4/IPv6 HTTP/HTTPS binds and models fail-closed source checks for UCI/procd/kernel socket differences, independently verified management IP bindings and separate trusted/host-data/upstream reachability. No on-device listener change, verified socket process ownership, real trusted/untrusted path proof, alternate access or hardware isolation acceptance exists. |
| S-013 | DONE_SOURCE | Remote GUI opt-in and basic Linux firewall | Access & servers now provides default-off remote HTTPS plus an IPv4 /24-/32 allowlist. V3 creates only fixed WAN INPUT rules targeting the management IPv4/HTTPS port, snapshots firewall with access configuration, verifies UCI + fw3 rendering, and rolls back on failure/timeout. SSH, forwarding/NAT, PON and OMCI are not exposed by this feature. Live external packet-path proof remains hardware acceptance. See [V3 remote GUI firewall](V3-REMOTE-GUI-FIREWALL.md). |
| S-014 | IN_PROGRESS | TLS/key hardening | V3 retains the [S-014 offline root-only key/certificate health](S-014-OFFLINE-TLS-KEY-HARDENING.md) checks and now adds a one-shot fixed-path hardener after uhttpd startup. Read-only r9 evidence found the persistent HTTPS key root-owned but mode 0644; the V3 hardener accepts only the qualified regular single-link inode and changes that legacy mode to 0600 with inode/readback verification, without reading key bytes or changing UCI/certificate contents. Hardware V3 boot verification, browser trust, protected rotation and rollback remain open. |
| S-015 | CONDITIONAL | Optional remote syslog and collector acceptance | Only if configured: receiver acknowledgement for TCP where applicable, tested credential handling, correct NAT source restrictions |
| S-016 | IN_PROGRESS | Config backup, restore and migration | [Offline S-016 source-only encrypted backup/restore model](S-016-OFFLINE-CONFIG-BACKUP-RESTORE.md) redacts sensitive config fields by default, separately encrypts a bounded synthetic private bundle with scrypt/AES-GCM, rejects wrong keys/tampering/schema/board conflicts, requires explicit recovery and cross-bank approval, and simulates rollback after injected partial failures. Schema covers only an allowlisted prototype subset. No live export/import, complete vendor setting coverage, native crypto, on-device journal, encrypted backup download, power-loss restore, or hardware validation exists. |

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

**Next firmware task:** complete R9-002 against the integrated candidate, preserving the latest native-transaction tests as development source. **Further configuration development:** continue the guarded write/restore adapter with explicit refusal of unsupported present-empty restoration and qualified cache handling. The read-only device baseline is complete; do not ask the operator to repeat it. C-010 discovery, C-012 schema tests and C-011 stored-source readback coverage now account for all 54 existing fields, but native effective behavior and persistence remain unqualified. Continue C-013 backend integration without treating a source-only journal as an on-device watchdog.

**Hardware prerequisite:** use the verified existing SSH profile for appropriately scoped read-only checks. Native writing, reboot/bank operations and disruptive tests remain separate approval-bound actions.

**History follow-through:** qualify the existing H-011 through H-028 source collector and its authenticated UI against measured PRX126 resources before runtime installation. Source integration is not an installed sampler or proof of subscriber Internet availability.

**Parallel:** X-010 adapter specification; S-010/S-011 cert source tests; P-010 measurement harness.

**Separate operational decision:** R8-010, followed by R-011 only on separate explicit approval. Do not conflate r8 trial acceptance with vNext source development.

## Completion record for each ID

For each completed item, record: source branch/commit, changed files, unit/browser/vendor-MIPS test counts, hardware target and firmware fingerprint, actual readback/behavior, reboot/flash or no-mutation statement, recovery evidence, failure receipts, remaining limitations and next dependent work ID.

Never advance an item from NOT_STARTED to DONE_HARDWARE based only on an assistant statement or source test.
