# AoTT-8311 v2r8 implementation plan

Implementation status: **first offline monitoring candidate under review**, not yet qualified or merged (2026-11-01). See [candidate implementation status](V2R8-IMPLEMENTATION-STATUS.md).
The draft implementation adds a separately rotatable read-only HTTPS collector token, exact peer IP restriction and management-destination check. This design still requires target HTTP integration and firewall qualification. The stock boot path may discard rootfs_data. See [persistence design](V2R8-PERSISTENCE-DESIGN.md) for the required durable store and dual-record fail-closed authorization. This has not been wired into the firmware.
Baseline: privately committed v2r7 source and its independently verified A/B recovery contract on one qualified LL-XS1010 / PRX126-SFP-PON device. Public GitHub remains source-only.

## Release objective

Make AoTT-8311 observability and device management easier to integrate and configure **without** introducing heavyweight background services, flash-write amplification, private deployment assumptions or PON regressions.

**Release theme:** Observability, performance, security and usability.

### Scope and priorities

| Priority | Workstream | Deliverable |
| --- | --- | --- |
| P0, release-blocking | Optional external monitoring | GUI-managed remote syslog and an access-controlled metrics endpoint backed by existing lightweight Lua/runtime functionality |
| P0, release-blocking | Metrics security and privacy | Audit the inherited unauthenticated metrics route; restrict to trusted management access, protect sensitive data and validate all configuration writes |
| P0, release-blocking | Recovery and reproducibility | Preserve v2r7 bank guards, fixed vendor ABI, A/B rollback and independently reproducible private firmware qualification |
| P1, targeted | Diagnostics and workload | Bounded optical/PON/Ethernet/GEM metrics, explicit units, missing-data handling, low-overhead collection and measurable flash/RAM/CPU impact |
| P1, targeted | GUI consistency | Consolidate Live Health and monitoring configuration, validate light/dark charts, mobile UI, labels, and honest connectivity indicators |
| P1, targeted | Operator guidance | Generic, copyable collector examples and troubleshooting that live in GitHub rather than the firmware image |
| P2, conditional | Native Prometheus text exposition | Consider a small Lua exposition route **only** if external JSON translation is inadequate and security/flash/resource tests pass |

No P1/P2 feature may displace a P0 security or recovery gate. A feature not qualified in time moves to a later revision rather than weakening the release standard.

## Architecture

- Existing LuCI/uhttpd and Lua form the management UI and read-only telemetry surface. No new always-on metrics agent is bundled.
- Use the vendor/OpenWrt logging service when its exact version supports remote forwarding. Do not claim TCP support until verified on the targeted image; UDP is the baseline transport if supported.
- The stick **does not** store historical metrics, run Prometheus/Loki/Grafana, maintain long-term persistent logs or include collector-specific client binaries.
- Users bring their own monitoring system and configure the destination; a collector may translate the existing JSON into Prometheus exposition.
- Default: remote forwarding and optional export disabled until a trusted management path and receiver are configured. Existing local Live Health remains available to authenticated admins.
- No shipped address, hostname, network topology, deployment label or special-case logic for a developer's own infrastructure.
- Detailed protocol, example configuration, safety and naming contracts: [MONITORING-AND-TELEMETRY.md](MONITORING-AND-TELEMETRY.md).

## Workstream A: Monitoring & Telemetry GUI (P0)

Proposed page: **Monitoring & Telemetry**, integrated with existing Live Health and system logging pages without duplicate menu entries.

**Remote syslog controls:** enable/disable, destination hostname/IP, port, explicitly supported transport, severity level, current effective configuration, Save/Apply, failed-save feedback and a non-sensitive test event.

**Metrics controls:** enable/disable read-only collection, show endpoint information, access-control status and supported metric groups. Display a suggested external scrape interval as **guidance**, never falsely claim to configure the user's Prometheus collector from the ONU.

**Status:** distinguish `configured`, `local service active`, `test event attempted`, and `receiver confirmed`. UDP send success or a populated destination is not proof of remote receipt. Receiver confirmation requires actual collector-side evidence.

Do not invent a GUI control for a protocol, persistence mechanism or source unavailable on the qualified rootfs.

## Workstream B: Security and configuration safety (P0)

- Audit the current `/cgi-bin/luci/8311/metrics` route, which is registered outside the authenticated admin route tree. Decide and test an explicit access policy that preserves safe migration for existing legitimate integrations.
- Restrict access to permitted management interfaces and authenticated or appropriately ACL-restricted clients. Never expose telemetry or administrative operations to an untrusted WAN interface.
- Ensure JSON/text responses exclude credentials, registration identifiers, passwords, secret hashes, MACs and subscriber-specific information. Avoid high-cardinality arbitrary labels.
- Validate hostnames/IPs, ports, severity values, transport modes and form tokens server-side; never compose shell commands from unchecked user input.
- Apply/revert configuration safely and read back effective state. Changes must survive reboot and legitimate A/B switching without erasing unrelated UCI or management settings.
- No automatic addition of a management route, static WAN address, default credentials or broad firewall allowance.
- Retain verified TLS/SSH/OMCI cryptographic dependencies; investigate vendor web advisories without unqualified library removal.
- Review inherited password/bootstrap and admin access warnings; implement only independently verified, recovery-safe fixes.

## Workstream C: Bounded telemetry and capacity (P1)

- Reuse `8311.tools.metrics()` for basic optical values. Extend from the existing authenticated `8311.health.performance()` for uptime, Ethernet/GEM counters and link details only when safe.
- Keep inexpensive optical status polls separate from costly `pontop` and `ethtool` subprocess calls. Bound process timeouts, output bytes, response sizes and concurrent work.
- Suggested external scrape guidance: around 60 seconds for basic optics/PON, around 300 seconds for heavy diagnostic counters; measure before choosing firm defaults.
- Use explicit status for unavailable counters, resets, reboot boundaries and omitted samples. Do not invent zeros or derive data rates from a single sample.
- Prefer metric names with units and Prometheus `_total` suffixes for monotonic counters if text exposition is implemented.
- Profile load on the actual PRX126 single online Linux CPU. Require quantified comparison against the v2r7 baseline, including memory, responsiveness and number of subprocesses per scrape.
- Keep flash persistent-write rate effectively unchanged, and do not change UBI geometry. The fixed rootfs bank is **6,221,824 bytes**; measure the final compressed, aligned image and preserve at least the project's previously established 64 KiB minimum reserve. Aim to stay close to the v2r7 520 KiB reserve when practical.

## Workstream D: Usability and firmware lifecycle (P1)

- Audit all remaining v2r7 GUI pages for dark/light contrast, graph text, navigation placement, mobile accessibility and consistent wording.
- Show clear warnings on monitoring configuration failures rather than silently saving unusable settings.
- Preserve authenticated bank-action validation, the short-lived boot-state fingerprint, backend locking, full-bank verification and the distinction between staging, one-shot trial and permanent commit.
- Correct only verified bugs in firmware-management jobs and error reporting. Any write-path change must receive isolated/native testing before being allowed onto hardware.
- Keep release identity, cached UI asset versions and historical candidate-versus-commit status clearly separated.

## Work sequence and dependencies

1. **Inventory and design freeze.** On an offline extracted v2r7 rootfs, verify `logd`, `logread`, supported UCI options, logging protocols, management ACL behavior and actual telemetry route authentication. Record before/after capacity baselines.
2. **Management access and API hardening.** Define read-only metric route policy, input validators, persistent configuration schema and rollback behavior. Write isolated negative tests before enabling endpoints.
3. **Syslog backend and GUI.** Reuse existing logging service, implement validated settings, readback and bounded test-event actions. Test reboot and bank-preservation behavior.
4. **Metrics mapping and external recipes.** Make data sources explicit, implement access controls, publish vendor-neutral Prometheus/syslog examples and optional off-device JSON translation. No private collectors in examples.
5. **UI and performance pass.** Consolidate navigation, improve charts, benchmark both light/heavy polls and verify bounded service impact. Defer native text exposition if it costs too much.
6. **Qualification and release.** Run privacy/manifest/provenance checks, Lua 5.1, shell, JavaScript, isolated native MIPS, browser, regression, independent offline image/archive rebuilds and a hardware-recoverable staged trial. A distinct authorized permanent commit comes only after acceptance.

## Acceptance matrix

| Gate | Required pass condition |
| --- | --- |
| Public neutrality | No production credentials, private hostnames/IPs, capture files, personal domains, hardcoded collectors, or subscriber identity in public Git tree, issue descriptions, examples or CI logs |
| GUI | Every visible setting has a working backend, validation, effective readback and clear failure messages; automated light/dark and narrow-screen tests pass |
| Syslog | Configurable remote receiver, correct severity mapping, compatible transport only, safe test log emission; unreachable receivers do not block the PON or cause uncontrolled retries |
| Metrics | Access-controlled read-only API, documented schema/units, bounded JSON output and subprocess time, no sensitive fields, no single-sample rate invention |
| Security | Auth/ACL negative tests, no WAN management exposure, no new blank/shared credentials, deterministic safe apply/revert and no shell injection |
| Resources | Final aligned SquashFS fits the unchanged bank with >=64 KiB reserve; idle/load RAM/CPU and process overhead measured and reviewed; no new persistent logs or always-on monitoring agent |
| Firmware continuity | Both banks, active/committed/pending state, recovery credentials, optics, GEM/VLAN, management and WAN pass independent checks; verified rollback plan exists |
| Reproducibility | Source manifest, source disclosure gate, no proprietary binaries, independent rootfs/archive matching, pin/ABI checks and complete native/browser regression suites pass |
| Hardware acceptance | Separate approvals for backup verification, inactive-bank stage, one-shot boot and permanent commit; no release claims before actual trial evidence |

## Explicitly deferred

Kernel SMP/VPE activation; NAND or UBI resizing; replacing PON/OMCI firmware; changing ISP provisioning; speculative throughput tuning; supporting untested ONUs; SNMP and other resident collectors; long-term log storage on flash; container runtimes; automated irreversible upgrades; bypassing proven A/B safety checks; introducing new dependencies without measured benefits.

## Release disposition

Planning this version authorizes **no modification to the production stick**. The public repo contains only auditable source and operational guidance. Separate offline implementation, source review, reproducible builds, private hardware backups, stage approval, trial approval and commit approval remain mandatory. Issues track actual completion and acceptance evidence; no task is marked complete merely because it is written here.
