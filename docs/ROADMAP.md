# AoTT-8311 development roadmap after committed v2r7

The v2r7 source corresponds to firmware privately hardware-tested and committed on one qualified LL-XS1010 / PRX126-SFP-PON device. v2r6 remains the verified on-device fallback. The public repository distributes sanitized source only, not ready-to-flash firmware or deployment-specific configuration.

## Completed historical milestones

- **v2r4:** LuCI and PON Managed Entity Explorer improvements, dark-mode and diagnostics fixes, recovery refinement.
- **v2r5:** Vendor web request-validation hardening, size/security audits, private hardware trial and commit.
- **v2r6:** Reboot consequence previews, stale-state handling, native guarded firmware actions, reproducible-build provenance checks and separate hardware trial/commit.
- **v2r7: Post-commit stability and graph contrast:** Readable inherited realtime Overview graphs in light/dark modes, tests for equivalent chart styles, independently built matching images, 300 source tests including 46 real Chromium scenarios, and independently verified permanent commit. See [v2r7 hardware acceptance](V2R7-HARDWARE-ACCEPTANCE.md).

The original offline candidate records are preserved as historical build-time evidence. Later hardware acceptance is recorded separately.

## v2r8: Observability, performance, security and usability

**Release-blocking:**

1. GUI-controlled optional remote syslog and secure integration with user-owned Prometheus-compatible or other monitoring collectors.
2. Access control, privacy filtering, server-side validation and persistence for new metrics/logging controls.
3. Preserve the proven A/B recovery lifecycle, fixed firmware bank geometry, SSH/HTTPS management and vendor PON/OMCI ABI.
4. Pass source-only scans, native MIPS checks, isolated browser suites, reproducible private image qualification and separately authorized hardware gates.

**Targeted enhancements:**

5. Bounded optical/PON/Ethernet/GEM sampling, explicit counter semantics and measurable CPU/RAM/flash overhead.
6. Consolidate Live Health and Monitoring pages; fix remaining contrast, mobile, navigation and error-reporting defects.
7. Keep generic collector examples and troubleshooting in GitHub, not the deployed firmware.

**Conditional:** a native Prometheus text endpoint only if external JSON translation is insufficient and the size, security and workload budgets remain satisfied.

Full details: [v2r8 implementation plan](V2R8-PLAN.md) and [monitoring integration design](MONITORING-AND-TELEMETRY.md). These documents are plans, not claims of implemented features.

## v3: Isolated hardware and kernel research

- Investigate offline secondary VPE startup and vendor kernel/bootcore behavior only on independent recoverable test devices.
- Treat PON pin/clock, NAND/UBI geometry and chipset changes as separate hardware research.
- Add other ONU models only after board-level compatibility and recovery testing.

## Permanent boundaries

- Do not publish subscriber provisioning, device identities, site-specific infrastructure, private hostnames, monitoring destinations, credentials, backups or captures.
- Do not embed private collectors, monitoring databases or organization-specific configurations. Users choose and operate their own integrations.
- No unsupported throughput claims, speculative kernel settings, management-auth bypass or unqualified PON/OMCI changes.
- No new always-on monitoring daemon, persistent flash-based log history or partition resizing for r8.
- Each production firmware write, one-shot trial and permanent commit requires distinct authorization and independent validation.
