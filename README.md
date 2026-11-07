# AoTT-8311

**Enhanced XGS-PON ONU firmware and management tools for the LL-XS1010 / PRX126-SFP-PON platform.**

AoTT-8311 extends the 8311 community firmware ecosystem with a more accessible web interface, deeper optical and network diagnostics, security visibility, and guarded A/B firmware management.

**Firmware source in this checkout:** AoTT-8311-v3r1, the V3 development line promoted from the privately hardware-qualified AoTT-8311-v2r9 release-candidate baseline. V3r1 is source-only and is **not yet hardware-qualified or deployed**. The exact r9 image remains the currently proven PRX126 runtime and recovery reference.

**Private hardware acceptance, November 7, 2026:** the exact qualified `AoTT-8311-v2r9` image is running and permanently committed in bank A on one LL-XS1010 / PRX126-SFP-PON device. Enhanced r8 remains complete and valid in bank B as the recovery image. Independent trial and post-commit checks confirmed PON O5.1, a 10 Gbps host link, recovery access, both complete bank images, and the pinned r9 runtime set. See [r9 hardware acceptance](docs/V2R9-HARDWARE-ACCEPTANCE.md), [r9 integration](docs/V2R9-INTEGRATED-RELEASE.md), and [project continuity](docs/PROJECT-CONTINUITY.md).

> **Important:** This repository currently provides a **secret-sanitized source overlay, not a ready-to-flash firmware image**. Proprietary vendor components, actual subscriber provisioning, and production credentials are deliberately excluded.

## AoTT-8311 V3 development line

V3 turns the r9 release-candidate foundation into a deployment-oriented residential firmware line rather than continuing the v2rN revision cadence. The current V3r1 integration adds a major-version identity, a capability-status surface, and an opt-in RAM-only local-history worker with authenticated History UI/API, bounded exports, dual-lock freshness checks, and independent PON/host sampling. Collection remains disabled by default.

The V3 branch deliberately retains r9's proven PON/OMCI runtime, management-routing compatibility, guarded A/B firmware lifecycle, and recovery assumptions. Remote GUI access remains disabled by default. Local history is volatile and performs no periodic flash writes. Management VLAN read/preview is integrated with recovery-storage admission and native-source classification, but production apply remains gated. V3 also hardens the qualified persistent HTTPS key to root-only mode and supports guarded activation of locally generated self-signed TLS candidates with persistent backup, browser confirmation, and timed automatic rollback; operator-owned certificate import remains gated. Other configuration mutation, durable history, remote-access firewalling, and additional hardware support remain qualification-gated until their exact production paths pass the documented acceptance gates.

See [V3 deployment foundation](docs/V3-DEPLOYMENT-FOUNDATION.md), [V3 local history runtime qualification](docs/V3-HISTORY-RUNTIME-QUALIFICATION.md), [V3 management VLAN preflight qualification](docs/V3-MANAGEMENT-PREFLIGHT-QUALIFICATION.md), and [V3 TLS candidate qualification](docs/V3-TLS-CANDIDATE-QUALIFICATION.md).

## AoTT-8311 v2 r9

The runtime overlay now combines optional syslog and protected external metrics, durable monitoring restoration, HTTPS-key permission visibility, and seven manual Configuration readback panels. The 89-file manifest and runtime integrity checks cover the complete combined runtime.

The readbacks distinguish stored settings, configured values and observed kernel/device evidence. The sensitive-identity panel returns only redacted status. All 54 existing fields have a readback contract; full hardware effectiveness and persistence remain separate qualification work.

The history, certificate, firewall and native VLAN transaction development remains outside the installed overlay. [Release scope](docs/V2R9-INTEGRATED-RELEASE.md) identifies exactly what ships and what remains in development.

### Monitoring implementation references

The integrated monitoring runtime retains the [r8 implementation record](docs/V2R8-IMPLEMENTATION-STATUS.md), [persistence design](docs/V2R8-PERSISTENCE-DESIGN.md), [boot audit](docs/V2R8-BOOT-READINESS-AUDIT.md), [stage-readiness record](docs/V2R8-STAGE-READINESS.md), [historical hardware acceptance](docs/V2R8-HARDWARE-TRIAL-ACCEPTANCE.md), [management-access audit](docs/V2R8-MANAGEMENT-ACL-AUDIT.md), and [generic external collector example](examples/monitoring/README.md). These dated records support the inherited implementation and do not certify r9 hardware acceptance.

## Current development handoff and future direction

The [project continuity record](docs/PROJECT-CONTINUITY.md) now records the November 7 r9 hardware trial and permanent commit, while preserving the older r7/r8 checkpoints as history. The public repository remains source-only; hardware acceptance does not publish the private firmware archive or subscriber-specific recovery material.

For continuity, feature planning and acceptance, read the [complete desired product requirements](docs/TARGET-STATE-AND-REQUIREMENTS.md), [configuration coverage baseline](docs/CONFIGURATION-COVERAGE.md), [ID-based delivery plan](docs/DELIVERY-PLAN-AND-ACCEPTANCE.md), [decision register](docs/ENGINEERING-DECISIONS.md), and [resume checklist](docs/RESUME-CHECKLIST.md). The [machine-readable dated checkpoint](docs/PROJECT-STATE-CHECKPOINT-2026-11-02.json) is a historical summary, not a substitute for current live bank readback.

The goal is a comprehensive, reliable residential XGS-PON bridge and management firmware that retains supported advanced controls and develops useful local history, stable service and separately qualified cross-stick compatibility. Do not treat a source-only proof, a one-shot hardware trial or a similar chipset label as an installed, committed, or universally compatible release.

### C-011 stored-source readback now covers all 54 GUI fields

The [nine-field sensitive identity readback](docs/C-011-SENSITIVE-IDENTITY-READBACK.md)
adds a root-session-checked, manual Configuration-page panel for PON
identity, registration credentials, IP-host identity and the root password
override. It shows only valid/invalid saved format, unset, or unavailable.
No values, credential hashes or lengths are returned. The source coverage
test accounts for all 54 GUI fields. **Effective hardware behavior,
authentication, persistence and deployment remain unverified.**

### C-013 offline crash-safe configuration journal

The [C-013 source-only transaction and recovery harness](docs/C-013-OFFLINE-CRASH-RECOVERY.md)
uses durable Linux file and directory sync, an actual cross-process
kernel lock, a previous verified snapshot and a pending/committed
journal to test synthetic config writes. Separate processes are
deliberately terminated during staging, installation, confirmation and
cleanup; unconfirmed changes roll back and confirmed changes survive.
It does **not** run on the ONU, cover all 54 settings, or prove
PRX126 flash/power-loss recovery.

### S-016 protected configuration backup and offline restore planning

The [S-016 redacted/optional encrypted backup and guarded restore model](docs/S-016-OFFLINE-CONFIG-BACKUP-RESTORE.md)
implements a source-only redacted preview, separate scrypt/AES-256-GCM
private archive, strict device/profile and A/B-bank compatibility checks,
explicit recovery/operator approval and synthetic rollback after injected
failure. The intentionally limited source schema is **not** a complete
production backup of vendor PON, OMCI or every GUI field. No device
configuration is read, restored, flashed, or committed.

### S-014 offline TLS and root-only private-key hardening

The [S-014 private-key and TLS health audit](docs/S-014-OFFLINE-TLS-KEY-HARDENING.md)
validates root-only key modes (0400 or 0600), ownership, regular-file
identity, certificate/key pairing, SAN coverage and expiration using
disposable source-only test fixtures. Extracted vendor-MIPS uhttpd
completed an isolated HTTPS handshake with a 0600 synthetic private
key on Hermes loopback. **No current certificate/key status on the
actual ONU or live HTTPS service has been verified or changed.**

### S-013 optional remote GUI firewall, source-only

The [S-013 disabled-by-default remote HTTPS policy](docs/S-013-OFFLINE-REMOTE-GUI-FIREWALL.md)
models narrowly allowed IPv4/IPv6 source CIDRs, an explicitly verified
management address and ingress zone, disabled fw3 rule candidates,
separate local recovery and bounded rollback with final operator
confirmation. It reads the extracted vendor fw3/UCI source without
changing it. The residential default remains local-only management.
**No rule has been enabled, applied or installed on the live ONU.**

### S-012 offline management listener isolation evidence

The [S-012 residential management isolation audit](docs/S-012-OFFLINE-MANAGEMENT-ISOLATION.md)
finds wildcard IPv4/IPv6 HTTP/HTTPS listener settings in the extracted
vendor r8 uhttpd configuration, without claiming live WAN exposure.
A source-only policy gate cross-checks UCI, separately declared uhttpd
process arguments, TCP socket evidence, independent management IPs and
trusted/untrusted access outcomes. Unsafe binds and incomplete IPv4/IPv6
evidence fail closed. **No listener, firewall, bridge or firmware
configuration has been changed on the actual ONU.**

### S-011 operator-owned certificate import preview, source only

The [S-011 offline certificate import validator](docs/S-011-OFFLINE-CERTIFICATE-IMPORT.md)
checks PEM/DER leaf certificates and matching private keys, required
DNS/IP SAN coverage, certificate validity and supplied CA signature
links. It also rejects incomplete or unsafe bundles and redacts
operator management identities from preview receipts. A user-provided
root does not establish browser trust. **No import route, HTTPS reload,
private key migration or active firmware configuration change exists.**

### S-010 source-only residential HTTPS certificate qualification

The [S-010 vendor-native SAN certificate study](docs/S-010-OFFLINE-VENDOR-SAN-CERTIFICATES.md)
demonstrates that the extracted vendor MIPS `px5g` already supports
hostname, IPv4 and IPv6 SAN creation using `-addext`, with independently
checked EC P-256/RSA-2048 key pairs, SHA-256 signatures and strict test
file permissions. A source-only offline harness rejects invalid SAN
input, mismatched keys and expired/altered certificates. It **does not**
create a live GUI action, install certs, reload uhttpd or change banks.

### H-028 source-only publication-admission handoff protection

The [H-028 verified snapshot admission gate](docs/H-028-PUBLICATION-ADMISSION.md)
prevents the live collector lock from mistakenly authenticating a
previous crashed writer's cached JSON. A separate kernel fcntl lock is
held only after a new snapshot passes canonical readback; both main and
publication locks must be present before and after an independent
history read. Competing, missing and unsafe publication locks fail
closed. Vendor-MIPS/QEMU tests reproduce the original restart race.
**No collector or route is installed on the ONU.**

### H-027 active-owner guarded source history publishing

The [H-027 lifecycle snapshot bridge and LuCI gate candidate](docs/H-027-GUARDED-LIFECYCLE-SNAPSHOT.md)
now connects H-026's bounded canonical JSON publisher to H-023's guarded
source-only collector lifecycle. It publishes at most once per 60 seconds
of accepted source uptime, revokes old cache on stop/restart, and checks
an actual H-022 kernel lock before and after each separate-process read.
Stale leftover snapshots after SIGKILL are rejected. A source-only LuCI
candidate rechecks root administrator session facts through local ubus,
but **no real LuCI route or live collector is installed**.

### H-026 authenticated local history snapshot contract

The [H-026 bounded cross-process history handoff](docs/H-026-LOCAL-HISTORY-READONLY-API.md)
now tests a guarded collector writing a sanitized 65,536-byte-limited
snapshot for a separate reader, with strict file ownership, atomic
replacement, nested JSON verification and an authenticated GET-only
response contract. An independent, explicit browser loader rejects
unknown sessions, redirects and oversized responses without ever
triggering native PON reads. The source GUI client and LuCI route are
**not installed**. Real PRX126 resource and session qualification
remain prerequisites for any live service activation.

### H-025 read-only hardware admission and resource evidence gate

The [H-025 hardware admission and evidence screen](docs/H-025-HARDWARE-ADMISSION.md)
adds a bounded, sanitized one-shot PON/host/CPU/memory/thermal resource
probe with injected providers, an extracted vendor-MIPS ELF/ABI preflight,
and a fail-closed workload evidence evaluator. The live PRX126 is **not**
a direct authorized gateway target, so these source tools **cannot**
authorize automatic sampling or claim verified ISP uptime. Even complete
synthetic readings are marked unapproved and hardware-unqualified.

### H-024 controlled foreground worker and inert procd candidate

The [H-024 source-only process supervisor](docs/H-024-SUPERVISOR-OFFLINE-PROCESS.md)
adds a tested vendor-MIPS/QEMU foreground worker, low-priority shell
wrapper, cooperative TERM/HUP/INT shutdown, bounded escalation, and
parent-death detection so a killed wrapper cannot leave an orphan
collector. The H-022 kernel lock and H-023 restart circuit breaker
remain authoritative. An intentionally inert procd init candidate
registers an error instead of starting a service or unlimited respawn.
The QEMU virtual-address allowance is not a qualified PRX126 RAM limit.
**No live daemon, firmware overlay entry or ISP setting is changed.**

### H-023 bounded restart and lifecycle control, offline source

The [H-023 controlled collector lifecycle](docs/H-023-COLLECTOR-LIFECYCLE.md)
adds manual startup, shutdown, backoff and a finite circuit breaker for
the H-022 guarded, independently scheduled H-021 collector. Real
vendor-MIPS QEMU processes verify kernel lock exclusion, release on
normal exit and SIGKILL, and bounded restart after synthetic read
failures. A stopped or failed collector cannot launch duplicate polling
processes or silently start itself. This **does not install procd**, enable
live hardware polling or create a firmware or flash-data write.

### H-022 true cross-process lock, tested with vendor MIPS nixio

The [H-022 guarded collector ownership layer](docs/H-022-CROSS-PROCESS-LOCK.md)
adds a genuine nonblocking Linux fcntl advisory lock, using the extracted
vendor MIPS Lua/nixio library under QEMU. Actual competing processes,
normal exit and forced process death, unsafe file types/permissions, and
an H-021 collector protected by the same lock are tested offline.
This source-only layer has **no automatic startup, LuCI endpoint or
PRX126 installation**. Its private root-owned runtime directory,
filesystem and firmware process lifecycle still require direct hardware
qualification before production use.

### H-021 independent native PON and Ethernet cadence

The [H-021 selective PON/host scheduling prototype](docs/H-021-INDEPENDENT-PON-HOST-CADENCE.md)
now supports independently configured 30/60/120/300-second intervals
subject to the conservative native process-wait budget. The fixed
native reader skips commands that are not due. History separately
records **not sampled** and **probe unavailable**, and exact host RX/TX
rates use the elapsed time between real counter observations, without
inventing zero traffic. A verified changed boot identity resets the
schedule safely. H-020's legacy equal-cadence model is preserved.
This source-only mode still needs real PRX126 qualification, a supervised
single writer and authenticated LuCI integration before deployment.

### H-020 one-owner source history collector integration

The [H-020 guarded single-collector model](docs/H-020-SINGLE-COLLECTOR-INTEGRATION.md)
now connects the existing PRX126 fixed one-shot reader, RAM history,
rate windows and sanitized JSON/CSV exports under one private Lua owner.
It rejects overlapping requests, honors a shared 60/120/300-second
manual tick cadence, backs off from failed probes and does not invent
Internet availability or false PON outages. Continuous missing-channel
observations generate one event instead of filling the RAM event ring.
This source remains **offline-only**: the administration gateway does
not currently expose the ONU as a direct authorized target, and no
service, scheduler, storage adapter or authenticated GUI endpoint is
installed. Unequal PON/host intervals are explicitly unsupported by
this first collector, not silently approximated.

### H-018 residential history configuration preview

The [H-018 source-only monitoring preferences](docs/H-018-RESIDENTIAL-HISTORY-CONTROLS.md)
add a 17-setting Lua 5.1 validator and an accessible light/dark settings
preview. Collection, persistence, local alert delivery and all remote
notifications are disabled by default and cannot be enabled without
qualified prerequisites. Polling schedules are bounded by a conservative
source-level process-wait budget, and users can preview permitted changes
without any firmware writes, network probes or delivered alerts.
The preview is not a working installed LuCI configuration endpoint.

### H-015 wear-aware persistent journal prototype

The [H-015 offline two-slot journal model](docs/H-015-OFFLINE-DUAL-SLOT-JOURNAL.md)
defines versioned and checksummed compact hourly summaries and event
records, a minimum 15-minute routine write cadence, bounded logical
storage, and recovery tests for interrupted checkpoints. It refuses to
invent calendar timestamps or 90-day continuity when clock evidence is
missing. A real atomic UBIFS adapter, flash wear tests, and field recovery
acceptance are **not** implemented. Nothing is written to the live stick.

### H-016 bounded historical view and exports, source preview only

The [H-016 history UI and export prototype](docs/H-016-HISTORY-UI-EXPORT.md)
introduces a static, accessible dark/light preview and Lua 5.1 JSON/CSV
projection for at most 100 latest-epoch samples/events. The view supports
1-hour/24-hour/7-day/30-day/90-day queries without inventing missing
traffic, optical readings, ISP outages, or full 90-day retention. Reboots,
interface changes and long gaps receive separate epoch markers so older
boot-relative timestamps cannot masquerade as new data. Nothing is
installed in the live firmware overlay or connected to an ONU yet.

### H-013/H-014 bounded Ethernet throughput windows

The [H-013/H-014 RAM rate aggregation model](docs/H-013-H-014-RAM-RATE-AGGREGATION.md)
provides measured-time-weighted host RX/TX Mbps averages, observed peaks,
separate direction-specific coverage, and bounded 1-hour/24-hour/7-day/
30-day/90-day queries. Unmeasured periods, reboot/interface boundaries,
missing probes and partial intervals never become invented throughput.
A revision-aware RAM-only cache avoids rescanning unchanged samples during
repeated history viewing; it invalidates on the next accepted observation.
The prototype does not run on an ONU yet, provide WAN speed/availability,
or extend RAM retention to its 90-day query length.

### H-017 independent router-side WAN evidence prototype

The [H-017 router/WAN probe evidence model](docs/H-017-INDEPENDENT-WAN-EVIDENCE.md)
now distinguishes ONU PON registration, Ethernet host speed and externally
reported router-side test results. Source-level history handles pass/fail/
unknown readings, sample gaps, reboots, bounded latencies and retention,
without pretending a single failed probe proves an ISP outage. This is
offline code only, not a router integration, deployed Internet monitor,
flash history or ready-to-flash firmware image.

### H-012 independent PON and host-link event handling

The [H-012 partial-observation update](docs/H-012-PARTIAL-PON-ETHERNET-OBSERVATIONS.md)
tracks native PON registration and host Ethernet link availability independently.
A failed read of one channel no longer hides a confirmed state transition in
the other. Missing readings remain unknown rather than being interpreted
as a disconnection, and rate calculations still require valid comparable
samples. This remains source-only: no runtime history, WAN probe, firmware
image growth or deployed collector is claimed.

### H-019 synthetic resource benchmark and hardware acceptance

The [H-019 offline resource qualification](docs/H-019-RESOURCE-QUALIFICATION.md)
provides a repeatable CPU/heap and host-process-RSS benchmark for the
existing RAM-only history reader under host Lua 5.1 and vendor MIPS QEMU.
It reports mock observations only, with strict host/process boundaries.
This does not measure real ONU CPU or driver performance, enable sampling,
claim WAN availability, alter firmware, or authorize a field deployment.

### H-010/H-011 exact-counter history and RAM prototype

The [bounded history-source prototype](docs/H-011-RAM-HISTORY-PROTOTYPE.md)
adds exact 64-bit traffic counter calculations, sampled PON/host-link events,
missing-observation and reboot gaps, and a finite RAM-only event/sample ring.
It passes source-level Lua and offline vendor MIPS checks. Prototype files
live outside the deployable overlay and do not use firmware image space.
There is no collector daemon, automatic sampling, flash history, Internet probe, web
history page or changed live firmware. Real hardware integration and
resource qualification are required before a residential history feature
can be described as operational.

The [H-011 one-shot PRX126 native readback contract](docs/H-011-ONE-SHOT-NATIVE-READBACK.md)
adds a strictly bounded opt-in source adapter for exact Ethernet counter
samples, PON state and boot-safe monotonic observations. It has no running
service, firmware-overlay footprint, flash storage or WAN-path proof. The
vendor commands remain unqualified on production until independent hardware
measurement and acceptance.

### C-012 offline configuration save/readback contract

The [C-012 validation matrix](docs/C-012-OFFLINE-CONFIG-SAVE-CONTRACT.md)
executes the real 54-setting LuCI schema and configuration worker under
isolated host Lua and vendor-MIPS QEMU, with simulated boot-environment
setters. All 54 synthetic positive saves and readbacks, field-specific
invalid inputs, secret masking, stale-revision rejection and seven failure
or concurrency-guard cases pass. This **does not prove** a field applied on
an actual ONU, survived reboot or is safe on other hardware. The publicly
available source remains a source-only r7 overlay, not a new firmware image.

### C-011 redacted OMCI reporting and software labels

The [C-011 redacted OMCI reporting readback](docs/C-011-OMCI-REPORTING-REDACTED.md)
adds a manual authenticated GET for ten noncredential OMCI/software
reporting fields. It displays presence, source-format validity and
limited reported-versus-boot-image version-label matches, **never raw
identity strings, firmware labels or regular expressions**. OMCI
reported active/committed bank controls are not actual boot or
firmware commit operations. Source-level C-011 coverage now reaches
**45 of 54** settings; nine identity/credential controls and all
real hardware runtime effects remain unqualified.

### C-011 advanced system and host readback

The [advanced device/host C-011 readback](docs/C-011-ADVANCED-SYSTEM-READBACK.md)
adds a manual, authenticated source-only comparison for eight boot,
UART, serial console, dying-gasp, RX_LOS, Ethernet override, OMCI
startup delay and debug persistent-root controls. It separates
environment overrides, configured optical dying-gasp mode,
GPIO electrical outputs and negotiated Ethernet speed. These do
not establish serial signaling, optical alarm delivery, applied
speed override or recoverability. Sensitive login hashes are never
read or returned by this endpoint. C-011 source-level coverage
reached 35 of 54 fields at that checkpoint; the later redacted
OMCI reporting extension raises current coverage to 45 of 54.
Complete hardware qualification remains open.

### C-011 scoped native VLAN TC rule readback

A [read-only native TC verification enhancement](docs/C-011-ISP-VLAN-READONLY-EVIDENCE.md)
can independently inspect the exact built-in VLAN flower selectors
when a root-owned validated native reconciliation receipt, matching
topology hash, and explicit built-in mode are present. It uses the
firmware's existing strict tc_flower_matches reader and never
installs, removes or modifies rules. A selected-rule match does not
prove hardware offload, all rule priorities or Internet connectivity.
On the privately trialed r8 stick the last reconciliation receipt is
absent, so no native TC success is claimed. Public r7 remains
source-only and this helper is not installed on the running device.

### C-011 ISP VLAN readback milestone

The [ISP/VLAN C-011 extension](docs/C-011-ISP-VLAN-READONLY-EVIDENCE.md)
adds a manually requested authenticated readback for the three
ISP service VLAN settings. It distinguishes saved overrides, source
defaults, and any historically validated built-in reconciliation
receipt. A running VLAN daemon, an unchanged topology hash or O5.1
registration does not prove current traffic-control rules or Internet
availability. This source-only milestone expands readback coverage
to 27 of 54 GUI fields, without installing firmware or changing the
working provider mapping.

### C-011 noncredential PON/OMCI readback

The [PON/OMCI C-011 extension](docs/C-011-PON-OMCI-READONLY-READBACK.md)
adds a manual authenticated, read-only comparison for four existing
configuration fields: optical access mode, OMCI channel version, IOP mask
and MIB profile. It separately reports PON registration state without
claiming O5.1 proves Internet connectivity or that the OLT applied
individual values. No PON registration identities or credentials are
read. C-011 source coverage is now 24 of 54 fields and remains unqualified
on live hardware until separately installed and tested.

### Source-only device and SFP effective-state extension

The [device/SFP C-011 extension](docs/C-011-DEVICE-AND-SFP-SOURCE-READBACK.md) adds a manual authenticated comparison for four system fields and seven virtual SFP EEPROM fields, bringing source readbacks to 20 of 54 GUI controls. A kernel hostname is independently observed; LuCI language, NTP synchronization, active time zone and host-router EEPROM presentation remain explicitly unverified. Source-only, not installed on the running ONU.

### C-011: read-only active management comparison

The [C-011 effective management readback](docs/C-011-MANAGEMENT-EFFECTIVE-READBACK.md) adds a manual, authenticated configuration-page comparison between saved overrides, UCI configuration and independently observed kernel values for nine management settings. It does not claim service success from a configuration match, require external collectors, or alter the ONU. **Source-only until independently hardware qualified.**

### Source-only capability registry milestone

The [C-010 capability registry implementation](docs/C-010-CAPABILITY-REGISTRY-IMPLEMENTATION.md) now provides source-derived configuration coverage tooling and tests. It inventories all 54 current GUI settings, traces static native references, and records missing/hidden options without claiming that each setter works on physical hardware. C-011/C-012 effective-state and persistence qualification remain open. The firmware on this stick was not changed by this source milestone.

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

| Enhancement | What AoTT-8311 through v2r9 adds or changes |
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

Existing diagnostic JSON can be consumed by external monitoring systems. **r9 includes the GUI-controlled optional remote syslog and authenticated read-only metrics source functionality inherited from the qualified enhanced-r8 runtime**, together with the configuration readback modules. The r9 hardware acceptance verified the installed runtime and management path; optional external receiver/collector delivery remains environment-specific. Users supply their own receiver, collector, storage, dashboards and alerts. See [monitoring architecture](docs/MONITORING-AND-TELEMETRY.md), [r9 hardware acceptance](docs/V2R9-HARDWARE-ACCEPTANCE.md), and [project continuity](docs/PROJECT-CONTINUITY.md).

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
| Current source | `AoTT-8311-v2r9` integrated source; no public full firmware image |
| Latest privately hardware-qualified firmware | `AoTT-8311-v2r9` running and committed in bank A as of November 7, 2026 |
| Verified on-device recovery image | Enhanced `AoTT-8311-v2r8` remains complete and valid in bank B; earlier images remain preserved privately off-device |
| Next-generation development | vNext capability, history, reliability and broader hardware support; source-only, not installed |
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
- **V3 credential preservation:** future V3 upgrades refuse bank writes when the running administrator credential is blank, unsupported, or still the known factory root password. See [V3 administrator credential preservation](docs/V3-CREDENTIAL-PRESERVATION.md).
- **Initial credentials:** No login password is supplied by this source repository. Configure unique device credentials and verify persistence after reboot.
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
| `docs/V2R8-PLAN.md` | Historical r8 architecture, prioritization, implementation order and release gates. |
| `docs/V2R9-INTEGRATED-RELEASE.md` | r9 integrated source scope, build identity and shipped-runtime boundaries. |
| `docs/V2R9-HARDWARE-ACCEPTANCE.md` | r9 hardware trial, permanent commit, recovery state and qualification limits. |
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
[the historical v2r7 hardware acceptance](docs/V2R7-HARDWARE-ACCEPTANCE.md),
[the current v2r9 hardware acceptance](docs/V2R9-HARDWARE-ACCEPTANCE.md), and
[the roadmap](docs/ROADMAP.md).

### Privately hardware-qualified releases

**Current v2r9 acceptance:** v2r9 was privately built reproducibly, staged into bank A, one-shot trial booted, independently verified, and permanently committed on one LL-XS1010 / PRX126-SFP-PON device. Enhanced r8 remains valid in bank B as the on-device recovery image. PON O5.1, 10 Gbps host Ethernet, management/recovery access, both complete bank images and the selected r9 runtime integrity set passed acceptance. See [v2r9 hardware acceptance](docs/V2R9-HARDWARE-ACCEPTANCE.md).

**Historical v2r7 acceptance:** v2r7 was privately hardware-tested and permanently committed in bank B with v2r6 then present as bank-A fallback. Its independently verified bank readbacks, PON O5.1, 10 Gbps host Ethernet, management and recovery checks are documented in [the v2r7 acceptance](docs/V2R7-HARDWARE-ACCEPTANCE.md). **Later private r8 transition:** original r8 was committed in A without an intermediate boot to r7; security-enhanced r8 was staged in B and successfully trial-booted. At the November 2 checkpoint B remained uncommitted, A remained the original-r8 fallback, and both banks passed integrity checks. Full historical recovery backups remain private. Other board families and long-duration stress remain unqualified.

The original v2r7 source and private archive build-time markers (`offline-candidate`, `UNTRIALED_OFFLINE_ONLY`, `safe_for_live_install=false`) preserve the **immutable build-time** stage. They do not contradict the later independently verified trial and commit. Read [v2r7 hardware acceptance](docs/V2R7-HARDWARE-ACCEPTANCE.md) alongside the [historical build note](docs/V2R7-RELEASE.md).

**v2r6 was separately hardware-qualified and committed in bank A** before v2r7. It added reboot/overwrite previews, expiring bank-state checks, native lock-bound guards and independently audited reproducible private builds. **v2r5** was qualified earlier but is now retained in private off-device recovery archives, not the active on-device fallback. See [v2r6 release notes](docs/RELEASE.md) and [v2r6 hardware acceptance](docs/V2R6-HARDWARE-ACCEPTANCE.md).

## Project status and roadmap

**Included in v2r9 source:** responsive LuCI interface, improved light/dark realtime graph contrast, optical/PON/OMCI/GEM and Ethernet diagnostics, security-state reporting, management routing compatibility, guarded A/B firmware lifecycle tooling, optional remote syslog/protected metrics, durable monitoring restoration, and readback contracts for all 54 existing GUI configuration fields.

**Current hardware state:** v2r9 is privately hardware-qualified and committed on one PRX126 stick, with enhanced r8 preserved in bank B for recovery. This does not establish complete end-to-end qualification of every setter, optional external collector, other ONU hardware, or a public firmware binary. **Next goals:** genuine A-to-Z control of every supported configuration item, persistence/recovery qualification, complete GUI correctness, local throughput and connectivity history, safe measurable performance improvements, certificate management, optional remote GUI firewall and independently qualified additional stick hardware. See [complete target requirements](docs/TARGET-STATE-AND-REQUIREMENTS.md) and [delivery plan](docs/DELIVERY-PLAN-AND-ACCEPTANCE.md).

**Deferred:** kernel/VPE activation, UBI resizing, vendor PON stack replacement, unsupported ONU hardware and automatic disruptive upgrades. A source-only update is not a firmware image or throughput guarantee.

## Contributions and responsible disclosure

Issues and pull requests are welcome for source improvements, usability, diagnostics, documentation, and test coverage. Run the included checks and inspect your staged diff before submitting changes.

**Do not attach unredacted logs, device backups, subscriber identifiers, live private-network settings, or credentials to an issue.** Report security-sensitive findings without publishing working secrets.

## Credits, licensing, and disclaimer

AoTT-8311 builds on the work of the **OpenWrt/LuCI** and **8311 community firmware** ecosystems. Original upstream notices are retained where present; see [docs/PROVENANCE.md](docs/PROVENANCE.md).

Third-party source licenses and redistribution rights are still being reviewed. **No blanket license is claimed for third-party derivative work or proprietary vendor binaries.** Public firmware releases should not be offered until those rights are established.

AoTT-8311 is an independent community project, not an official vendor or ISP release. Use it only on devices and networks you are authorized to administer. Firmware modifications can interrupt service or render a device unbootable; keep verified recovery options.

---

**AoTT-8311 | v2r9 privately hardware-qualified and committed on one PRX126 | enhanced-r8 recovery bank preserved | further features in source development**

