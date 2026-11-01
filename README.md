# AoTT-8311

**Enhanced XGS-PON ONU firmware and management tools for the LL-XS1010 / PRX126-SFP-PON platform.**

AoTT-8311 extends the 8311 community firmware ecosystem with a more accessible web interface, deeper optical and network diagnostics, security visibility, and guarded A/B firmware management.

**Latest privately hardware-qualified and committed firmware:** `AoTT-8311-v2r7` on one qualified LL-XS1010 / PRX126-SFP-PON unit, committed in bank B. Its verified on-device alternative is v2r6 in bank A. The public repository distributes sanitized **v2r7 source only**, not ready-to-flash archives. **v2r8 implementation is underway in a separate development branch, not hardware-qualified or released.**

> **Important:** This repository currently provides a **secret-sanitized source overlay, not a ready-to-flash firmware image**. Proprietary vendor components, actual subscriber provisioning, and production credentials are deliberately excluded.

## Why AoTT-8311?

XGS-PON SFP+ ONUs expose far more operational information than their default interfaces make convenient to access. AoTT-8311 aims to provide **more visibility, more control, and safer recovery** without obscuring the fact that the ISP's OLT controls service provisioning.

## Features

| Area | Capabilities |
| --- | --- |
| **Modern web UI** | Responsive LuCI-based interface, organized navigation, readable light/dark themes, and contextual descriptions. |
| **Optical diagnostics** | RX/TX optical power, module voltage, laser bias, optic temperature, and CPU thermal sensors. |
| **PON and OMCI** | Registration status, GEM ports, allocation IDs, managed-entity exploration, PON counters, and VLAN diagnostics. |
| **Ethernet and traffic** | Host-link negotiation, MAC counters, drop/error visibility, and sampled traffic rates. |
| **Security status** | Authenticated, read-only inspection of password persistence, SSH access settings, management exposure, and warnings, without returning secrets. |
| **Configuration tools** | Validated settings, persistence helpers, and support diagnostics. |
| **Firmware management** | A/B bank inspection, integrity checks, verified full-bank backups, inactive-bank staging, one-shot trials, explicit commit, and rollback. |

## Enhancements over the 8311 Community Version

AoTT-8311 **builds on** the existing [8311 Community Firmware](https://github.com/djGrrr/8311-was-110-firmware-builder) rather than replacing it. The comparison below uses the community **v2.8.3 Basic** release as the reference point. Upstream already includes a LuCI interface, PON/OMCI and VLAN diagnostics, monitoring metrics, firmware uploads, and basic firmware-bank switching. Those are established community features, not AoTT inventions.

| Enhancement | What AoTT-8311 through v2r7 adds or changes |
| --- | --- |
| **Redesigned management experience** | Responsive interface refinements, clearer navigation and explanations, and more readable light/dark styling on top of the community LuCI UI. |
| **Unified Live Health view** | An authenticated, read-only overview combining optical levels, temperatures, voltage, GEM/allocation details, and Ethernet traffic/error counters. This extends, rather than replaces, the community's existing status and metrics endpoints. |
| **Security & Access diagnostics** | A dedicated page and structured API identifying risks such as an unset root password, discrepancies in password persistence, and management-access concerns without returning password hashes or key material. These checks **report** issues; they do not silently fix them. |
| **Guarded A/B upgrade lifecycle** | Additional bank-integrity receipts and compatibility checks, verified full-volume backups, inactive-bank write verification, a one-shot trial boot, and **separate explicit commit or rollback**. The community firmware already supports upgrades and bank selection; AoTT places stronger verification and recovery gates around them. |
| **Reboot and overwrite preview** | Plain-language next-boot and recovery-bank preview, inactive-bank overwrite warnings, expiring boot-state fingerprints, pre-action state checks and native lock-bound guards for firmware operations. |
| **Configuration validation and controlled operations** | More structured server-side checks, revision-aware persistence, and bounded status/background-job handling for sensitive web operations. |
| **Monitoring-friendly health data** | Structured authenticated health/security information for optional external observability, including Prometheus/Grafana integrations. The external collector, dashboards, and alert-delivery infrastructure are **not included** in this source package. |
| **Source release safeguards** | A curated source-only overlay with per-file SHA-256 manifest, automated secret detection, negative security tests, and intentionally nonfunctional factory credential placeholders. |

**What has not changed:** AoTT-8311 does **not** replace the proprietary PON/OMCI stack, provision additional ISP bandwidth, bypass OLT service profiles, or guarantee support for other ONU hardware. Some inherited vendor-kernel issues remain under investigation; they are not presented as fixed in v2r1.

### Live health and monitoring

The source includes authenticated **Live Health** and **Security & Access** views. Health data can be refreshed at selectable intervals without automatically changing configuration. v2r7 improves light/dark Overview graph contrast.

Existing diagnostic JSON can be consumed by external monitoring systems. **v2r8 has an offline development candidate for GUI-controlled remote syslog and HTTPS-only, token-protected read-only metrics collection restricted to one configured collector IPv4 address.** It is not released or hardware-qualified. See [candidate status](docs/V2R8-IMPLEMENTATION-STATUS.md). Users supply their own receiver, Prometheus-compatible collector, storage, dashboards and alerting. See [monitoring architecture](docs/MONITORING-AND-TELEMETRY.md) and [v2r8 plan](docs/V2R8-PLAN.md).

### A/B upgrade safety

The firmware tooling is designed around a deliberate recovery sequence:

1. Verify platform identity, the running bank, boot configuration, and image hashes.
2. Create independently verified, off-device backups of **both** firmware banks.
3. Write only the inactive bank, then verify the image and required runtime files.
4. Boot once into the candidate while preserving the previous committed bank.
5. Check optical registration, management access, Ethernet, logs, and real WAN performance.
6. **Commit explicitly** after acceptance or return to the preserved firmware.

These operations require a compatible complete firmware build and an independently authorized installation procedure. **Cloning this repository does not flash an ONU.**

## Hardware compatibility

| Component | Scope |
| --- | --- |
| Primary device | OEM/Potron LL-XS1010 XGS-PON SFP+ ONU |
| Platform | PRX126-SFP-PON, PRX300-family vendor firmware baseline |
| Latest privately tested firmware | `AoTT-8311-v2r7` (version 2, revision 7; hardware trial and permanent bank-B commit independently verified on one qualified PRX126-SFP-PON ONU) |
| Verified on-device alternative | `AoTT-8311-v2r6` in bank A; earlier versions remain in private off-device backups |
| Next planned revision | `AoTT-8311-v2r8`, optional syslog and metrics integration, resource and UI improvements, security and reliability checks |
| Dependencies | Compatible vendor kernel, boot components, PON/OMCI stack, and authorized ISP provisioning |
| Other ONUs | Not automatically supported; require separate hardware qualification |

A **10Gbps Ethernet link is not a promise of 10Gbps Internet service**. Actual throughput, GEM/T-CONT allocations, VLAN assignments, authentication, and service profiles depend on the provider's OLT and subscription.

The **tested AoTT firmware image** applies to the Potron LL-XS1010
PRX126-SFP-PON firmware lineage. A matching chipset or the generic
WAS-110 archive header does not qualify another device. Read the
[hardware compatibility matrix](docs/COMPATIBILITY.md).

### Lean builds and resource allocation

The PRX126 platform has substantial unallocated NAND space, but
its A/B rootfs volumes are separately limited. Only one logical Linux
CPU was online in the audited boot; the role and startup failures of
the secondary VPEs still require vendor investigation.

The repository includes offline-only pruning tools that remove static
MIB documentation, Nano, and DSL/WiFi Overview widgets from a
PRX126 SFP build. All selected runtime MIB profiles, timezones,
PON/OMCI, crypto libraries, management, RARP, SSH/HTTPS and A/B
recovery remain available in the compact profile.

See [NAND, RAM and CPU allocation](docs/RESOURCE-ALLOCATION.md),
[offline pruning profiles](docs/BUILD-PROFILES.md), and
[MIB template format](docs/MIB-FORMAT.md). The [external reference comparison](docs/EXTERNAL-REFERENCE-PROJECTS.md), [upstream architecture decision](docs/UPSTREAM-ARCHITECTURE.md), and [newer 8311 fork review](docs/UPSTREAM-FORKS.md) describe what can safely be reused from other firmware projects. No complete rootfs,
subscriber credentials or vendor binaries are committed to GitHub.

### Management routing compatibility

The uncommitted v2r2 trial revealed a management-routing regression: it
normalized a saved legacy self-address gateway to an empty setting, removing
a route that some installed PRX126 networks still require to reach the ONU.
The **hardware-tested v2r3 and later firmware** preserve that existing value, while still
allowing an explicitly blank gateway on new installations. Configuration
saves never silently clear a legacy route. Read
[management gateway compatibility and verification](docs/MANAGEMENT-ROUTING.md)
before upgrading. The v2r3 firmware was verified before and after a guarded A/B commit on the supported hardware.

## Getting started: source only

Clone and audit the source:

```bash
git clone https://github.com/AllTheThangz/AoTT-8311.git
cd AoTT-8311
python3 tools/verify_release.py .
python3 -m unittest discover -s tests -v
```

Create a reviewed **offline source staging directory** (the destination must not already exist):

```bash
python3 tools/install_overlay.py --destination /tmp/aott-8311-source-stage
```

This operation copies source files only. It does **not** assemble complete firmware, update a running device, modify PON credentials, or change boot banks.

To build actual firmware, obtain a **legally authorized, clean, compatible vendor base** and follow [the build and qualification notes](docs/BUILD.md). Never use a subscriber's live flash dump as the source of a public release.

## Default access and security

- **Default account name:** `root`.
- **Default password:** None is provided in this repository. Set a **unique, device-specific password** before deployment and verify that it survives reboot.
- **Factory example settings:** [examples/factory-defaults.env.example](examples/factory-defaults.env.example) contains intentionally unusable placeholders, not active credentials.
- **PON identity:** Use only your own authorized registration details from your provider. Never publish a real PON serial, registration ID, LOID, or password.
- **Recovery access:** Verify a separate management path and key-based recovery before restricting password login.

**Do not deploy an ONU with an empty root password or a shared factory password.** Keep production keys, configuration files, certificates, device backups, and credentials out of Git. See [SECURITY.md](SECURITY.md).

## Repository layout

| Path | Contents |
| --- | --- |
| `overlay/` | Curated LuCI views, source modules, CSS/JS assets, and firmware/configuration tools arranged by rootfs path. |
| `examples/` | Non-operational example settings. |
| `tools/` | Source scanner, offline overlay staging, build profiles, runtime integrity checks and independent release-pair auditing. |
| `tests/` | Manifest checks and tests for detecting common secret patterns. |
| `MANIFEST.json` | File modes and SHA-256 hashes for the curated overlay files. |
| `docs/BUILD.md` | Build boundaries and safety qualification. |
| `docs/RELEASE.md` | v2r6 reproducible build notes, hardware acceptance, and compatibility boundaries. |
| `docs/PROVENANCE.md` | Upstream attributions and license review. |
| `docs/PRIVACY-AUDIT.md` | Disclosure rules for source, screenshots and release history. |
| `docs/ROADMAP.md` | Prioritized firmware development and release work. |
| `docs/COMPATIBILITY.md` | Supported hardware and incompatible platforms. |
| `docs/RESOURCE-ALLOCATION.md` | CPU, RAM and NAND capacity audit. |
| `docs/BUILD-PROFILES.md` | Offline slimming profiles and qualification. |
| `docs/MIB-FORMAT.md` | On-repository MIB format documentation. |
| `docs/FEATURE-PRUNING-AUDIT.md` | Package pruning evidence and risk classification. |
| `docs/V2R5-HARDWARE-TRIAL-READINESS.md` | v2r5 bank-B trial safety gates, runtime policy compatibility and recovery consequences. |
| `docs/V2R5-SECURITY-AND-SIZE.md` | Historical v2r5 dependency, binary security and image-size evidence. |
| `docs/V2R6-BOOT-PLAN.md` | v2r6 reboot preview, stale-state protection, pre-action checks and browser tests. |
| `docs/V2R6-REPRODUCIBLE-PAIR.md` | Private archive reproducibility, provenance and unsigned checksum evidence. |
| `docs/V2R6-STATE-GUARD.md` | Server-bound bank-state checks, concurrency protection and qualification limits. |
| `docs/V2R6-HARDWARE-STAGING.md` | Historical recovery-bank consequences, candidate policy bridge and hardware trial prerequisites. |
| `docs/V2R6-HARDWARE-ACCEPTANCE.md` | Completed v2r6 hardware trial and commit, sanitized post-commit acceptance, and remaining limits. |
| `docs/V2R7-RELEASE.md` | Historical v2r7 untried build-stage contract and recovery risks. |
| `docs/V2R7-HARDWARE-ACCEPTANCE.md` | v2r7 hardware trial, verified permanent commit and qualification limits. |
| `docs/V2R8-PLAN.md` | r8 architecture, prioritization, implementation order and release gates. |
| `docs/V2R8-IMPLEMENTATION-STATUS.md` | Current candidate, offline tests, limitations and remaining blockers. |
| `docs/V2R8-PERSISTENCE-DESIGN.md` | Durable monitoring configuration design and offline vendor-runtime evidence; not yet deployed. |
| `docs/MONITORING-AND-TELEMETRY.md` | Deployment-neutral syslog and metrics integration design. |
| `CHANGELOG.md` | Version-by-version development and deployment history. |

### Publication and privacy boundary

The public repository contains no complete firmware image or subscriber provisioning.
Before publishing, run the release manifest scanner and disclosure gate:

    python3 tools/verify_release.py .
    python3 tools/check_disclosure.py .

The disclosure gate rejects embedded network identifiers, concrete MAC addresses,
credentials, unreviewed screenshots and personal environment data. It cannot
replace manual review of Git history, source provenance or future release assets.

See [privacy and publication checks](docs/PRIVACY-AUDIT.md),
[historical v2r6 release notes](docs/RELEASE.md),
[the current v2r7 hardware acceptance](docs/V2R7-HARDWARE-ACCEPTANCE.md), and
[the v2r8 roadmap](docs/ROADMAP.md).

### Privately hardware-qualified releases

**v2r7 is running and permanently committed in bank B** on the single qualified PRX126-SFP-PON unit. Separately authorized staging, one-shot trial and guarded commit passed complete firmware-bank integrity readback, PON O5.1 registration, negotiated 10 Gbps host Ethernet, HTTPS management, WAN, and persistent root/SSH recovery checks. **v2r6 remains a valid on-device fallback in bank A.** Original full-bank backups remain private and off-device. Long-term stress and other board variants remain unqualified.

The original v2r7 source and private archive build-time markers (`offline-candidate`, `UNTRIALED_OFFLINE_ONLY`, `safe_for_live_install=false`) preserve the **immutable build-time** stage. They do not contradict the later independently verified trial and commit. Read [v2r7 hardware acceptance](docs/V2R7-HARDWARE-ACCEPTANCE.md) alongside the [historical build note](docs/V2R7-RELEASE.md).

**v2r6 was separately hardware-qualified and committed in bank A** before v2r7. It added reboot/overwrite previews, expiring bank-state checks, native lock-bound guards and independently audited reproducible private builds. **v2r5** was qualified earlier but is now retained in private off-device recovery archives, not the active on-device fallback. See [v2r6 release notes](docs/RELEASE.md) and [v2r6 hardware acceptance](docs/V2R6-HARDWARE-ACCEPTANCE.md).

## Project status and roadmap

**Included in v2r7 source:** responsive LuCI interface, improved light/dark realtime graph contrast, optical/PON/OMCI/GEM and Ethernet diagnostics, security-state reporting, management routing compatibility, and guarded A/B firmware lifecycle tooling.

**v2r8 development:** Initial remote syslog and authenticated metrics source is under offline review, not merged into stable firmware and not hardware-qualified. Collector HTTP and management-ACL qualification, durable settings restoration, workload validation and A/B hardware acceptance remain open. See the [persistence design](docs/V2R8-PERSISTENCE-DESIGN.md). See [the implementation plan](docs/V2R8-PLAN.md) and [candidate status](docs/V2R8-IMPLEMENTATION-STATUS.md).

**Deferred:** kernel/VPE activation, UBI resizing, vendor PON stack replacement, unsupported ONU hardware and automatic disruptive upgrades. A source-only update is not a firmware image or throughput guarantee.

## Contributions and responsible disclosure

Issues and pull requests are welcome for source improvements, usability, diagnostics, documentation, and test coverage. Run the included checks and inspect your staged diff before submitting changes.

**Do not attach unredacted logs, device backups, subscriber identifiers, live private-network settings, or credentials to an issue.** Report security-sensitive findings without publishing working secrets.

## Credits, licensing, and disclaimer

AoTT-8311 builds on the work of the **OpenWrt/LuCI** and **8311 community firmware** ecosystems. Original upstream notices are retained where present; see [docs/PROVENANCE.md](docs/PROVENANCE.md).

Third-party source licenses and redistribution rights are still being reviewed. **No blanket license is claimed for third-party derivative work or proprietary vendor binaries.** Public firmware releases should not be offered until those rights are established.

AoTT-8311 is an independent community project, not an official vendor or ISP release. Use it only on devices and networks you are authorized to administer. Firmware modifications can interrupt service or render a device unbootable; keep verified recovery options.

---

**AoTT-8311 | v2r7 source-only release | v2r7 privately hardware-committed | v2r8 planned**
