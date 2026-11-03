# AoTT-8311 decisions, rejected approaches and open questions

**Last reconciled:** 2026-11-02. This is the project's decision register, separate from implementation progress and private device credentials. Decisions are not claims that a feature already exists.

## Accepted decisions

| ID | Decision | Why and consequence |
| --- | --- | --- |
| D-001 | Build an enhanced replacement/extension of community 8311 | Credit upstream capabilities and improve usability, observability, complete functionality, recovery and hardware support |
| D-002 | Residential fiber bridge first | Avoid enterprise firewall, mandatory PKI, local monitoring databases and general-router scope |
| D-003 | Make every *actually supported* settable property configurable | Hardware-specific adapters and explicit read-only/unsupported states are more truthful than hidden controls or fabricated setters |
| D-004 | No dead GUI controls or pretend saves | Validate, preview, write, durable and effective readback, persistence and recovery per field |
| D-005 | Expert options remain available | Show risk and dependencies, do not erase useful knobs merely to simplify the default view |
| D-006 | Local configuration should normally be easy and quiet | Everyday dashboard and simple setup, with searchable expert controls and diagnostics |
| D-007 | Strong history is a core feature | Throughput, optical/PON transitions, errors and outages are more useful to homeowners than optional enterprise monitoring |
| D-008 | Distinguish PON, host Ethernet and Internet health | O5.1 and 10G Ethernet do not establish router WAN connectivity, ISP speed or access to the Internet |
| D-009 | Local certificate generation and owned-domain import | Self-signed is acceptable; include correct SAN and protect private keys. Public CA trust optional |
| D-010 | Configurable basic Linux firewall only for explicit remote GUI access | Default local management still requires actual listener/path isolation; avoid touching bridged service traffic |
| D-011 | Metrics/syslog are optional | Useful for advanced owners, but not universal residential release blockers or built-in commercial dependencies |
| D-012 | Optimize by measurement, not component utilization | Dedicated forwarding/optical hardware and reserved DMA resources should remain protected |
| D-013 | Hardware compatibility is board-specific | Same SoC/marketing name/SFP+ fit does not establish kernel, bootcore or flash compatibility |
| D-014 | Preserve one known working firmware bank | Reboot, stage, trial and commit remain separate actions. Never repeat a write on uncertain transport |
| D-015 | Do not boot r7 unnecessarily when an r8-to-r8 path is safe | Original r8/A was committed without reboot, updated r8 staged to B and trial-booted while A stayed committed |
| D-016 | Exact image hash is authoritative | Original and security-enhanced r8 share a version string but are different rootfs builds |
| D-017 | Preserve failures and corrective actions in evidence | First guarded trial command was syntactically rejected; second reboot succeeded; original verifier reconnect failed before independent confirmation |
| D-018 | Public source/documentation must be sanitized | Never publish complete vendor images, private backups, subscriber identities, passwords, IPs, domain-specific TLS material or private hostnames |
| D-019 | Durable resume material is mandatory | A dated state register, goal spec, backlog and operator protocol must be updated whenever a milestone changes |

## Explicitly rejected or deferred approaches

- Treating enterprise CA trust, an external Prometheus stack or remote syslog receipt as mandatory for every residential installation.
- Hiding valid advanced settings simply because they are rarely used.
- Exposing every kernel/sysfs or vendor register as writable with no board support or rollback proof.
- Calling a firmware environment write a completed configuration if the consuming daemon has not applied it.
- Inferring ISP uptime from a PON association or Internet throughput from a 10 Gbps host-link speed.
- Continuous speed tests that consume subscriber bandwidth or create thermal/load pressure.
- Storing unbounded high-frequency logging/metrics in flash or bundling a monitoring database on the stick.
- Enabling all VPEs, increasing CPU utilization or using reserved DMA/CMA memory without vendor-specific evidence and an independent recovery device.
- Flashing a PRX126 image to Realtek, Cortina, CIG or a different flash layout merely because it supports XGS-PON.
- Blindly replacing an inactive bank that currently holds the only working recovery image.
- Automatically retrying an ambiguous flash/reboot action or reusing a target approval ID.
- Removing vendor PON/OMCI or dynamically loaded crypto components solely to make a smaller SquashFS.
- Publishing private r8 binaries or claiming current public main is r8 before a deliberate source-only publication decision.

## Items not yet decided

| ID | Open question | Required evidence before decision |
| --- | --- | --- |
| Q-001 | Exact 7/30/90-day history retention and sample intervals | Sustained event count, RAM/CPU measurements, UBIFS write endurance and power-cut recovery |
| Q-002 | Best way to independently verify ISP Internet reachability | Router integration, management-plane routing analysis, multi-vantage tests and provider behavior |
| Q-003 | Which additional PRX126 device is the first native port | Physical spare hardware, exact PCB/kernel/bootloader/UBI info, recovery proof and representative OLT tests |
| Q-004 | Which non-PRX126 families should have a read-only adapter first | Open management API/protocol availability, board restrictions and device availability |
| Q-005 | Whether all current 54 controls map to genuine effective writers | Per-field backend trace and tests, not source annotations alone |
| Q-006 | How to expose factory-mode and device serial related controls | Vendor semantics, dangerous side effects, security model and per-board applicability |
| Q-007 | Vendor px5g SAN generation source-proven; safe rotation still open | [Offline vendor MIPS certificate evidence](S-010-OFFLINE-VENDOR-SAN-CERTIFICATES.md) confirms repeated px5g SAN extensions without adding OpenSSL CLI. Production private-key storage, live uhttpd DER load, browser validity, certificate import, guarded reload and rollback remain unqualified. |
| Q-008 | Remote management transport and firewall behavior | Which ingress interfaces exist, actual IPv4/IPv6 filtering, reliable local recovery and no bridge disruption |
| Q-009 | Default alerts and optical thresholds | Optic manufacturer limits, module revision, baseline history and user preferences |
| Q-010 | Unique next release/build naming after two r8 variants | Reproducible source identity, product cadence, hardware target and manifest/UI display |
| Q-011 | Whether low-risk monitoring and logging controls must survive bank transitions | Actual persistent UCI behavior, platform firmware migration and rollback semantics |
| Q-012 | Which performance tunables can measurably improve throughput/latency/stability | Repeatable test harness, vendor documentation, spare hardware and adverse-case tests |
| Q-013 | When to permanently commit the currently running enhanced r8 bank B | Residential acceptance and **separate explicit operator approval**; source work does not confer permission |
| Q-014 | How to reconcile public main r7 and draft PR #11 with private r8 developments | Provenance review, secret/privacy validation, source-only PR strategy and a deliberate release decision |

## Design choices needing quantitative validation

The following are proposed starting points, not proven device settings:
- Optical/PON observation interval 15 to 30 seconds.
- Ethernet counter observation interval 15 to 60 seconds.
- Slow, bounded polling for expensive GEM/OMCI diagnostics.
- On-device RAM ring plus roughly 512 KiB persistent compact history.
- Normal persistent summary flushes at most every 15 minutes.
- Event-based sampling, bounded queue and oldest-first history eviction.
- 90-day availability aggregates only if the measured storage budget permits.

All require actual overhead and retention testing. A configurable interval should never imply the vendor hardware can service it without performance impact.

## How to revise a decision

Every change must include:
1. Decision ID and old/new status.
2. User-requested product intent or new measured evidence.
3. Consequences for GUI, API, hardware, release and migration.
4. Tests and actual affected hardware profiles.
5. Unresolved risks, rejected alternatives and rollback plan.
6. Corresponding updated backlog work IDs and public/private state records.

Do not silently reverse an accepted decision because a future session starts without context.

## Relationship to implementation

The [requirements](TARGET-STATE-AND-REQUIREMENTS.md) specify the desired complete product. The [backlog](DELIVERY-PLAN-AND-ACCEPTANCE.md) determines engineering order. The [configuration coverage registry](CONFIGURATION-COVERAGE.md) lists the currently known surface and test evidence. The [continuity checkpoint](PROJECT-CONTINUITY.md) records the last verified state. This decision register explains why those choices exist.
