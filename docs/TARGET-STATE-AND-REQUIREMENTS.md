# AoTT-8311: desired future state and acceptance requirements

**Status:** vNext product requirements, 2026-11-02. This describes the desired complete product. A listed feature is not implemented merely because it appears here.

## Mission and product boundaries

Build an enhanced residential XGS-PON stick firmware platform on top of the [8311 Community Firmware](https://github.com/djGrrr/8311-was-110-firmware-builder).

The primary goal is real hardware choice for residential fiber connections: users with a compatible ONU should be able to own their module, configure legitimate required service parameters, use their own router, measure their actual link behavior, diagnose failures and safely update firmware.

Preserve upstream achievements and attribution. Do not advertise existing upstream LuCI, PON/OMCI, VLAN, metrics, SFP and firmware-bank functions as wholly new features. Differentiate with **complete working controls, usability, historical observability, recoverability, measured performance gains and more tested hardware families**.

Non-goals: an enterprise firewall or monitoring appliance; a substitute for the ISP's OLT; a guarantee of OLT authorization or extra provisioned service bandwidth; a universal binary for unrelated chipsets; an always-on speed-test generator; or removing critical vendor PON/OMCI dependencies for cosmetic image-size savings.

The normal residential flow should be: **identify compatible hardware, preserve a backup, configure supported service fields, verify optical association and actual Internet service, connect a router, and leave it running**. Advanced troubleshooting must be accessible without being compulsory.

## R01: complete configuration discovery and control

The requirement is all genuinely supported, settable items on the detected platform, not just an arbitrary fixed list of 54 existing GUI fields.

The system must register and expose each capability from supported backends:
- PON identity, service registration, LOID/PLOAM where required, OMCI attributes and interoperable MIB profiles.
- GEM/T-CONT and VLAN bridging, multicast/IPTV, UNI port mapping and tagged/untagged behavior where the ONU is allowed to configure them.
- Host Ethernet link and supported negotiation modes; SFP EEPROM identity and DDM diagnostics.
- Optical and chipset status, thresholds that are *actually user-writable*, signal pins, PTP/time and SerDes properties where safely implemented.
- Management interface, routing/VLAN, local web and SSH, DHCP/DNS/NTP and system identity where the platform offers them.
- Firmware bank controls, backups, recovery, logs, history, diagnostics, certificates, optional remote access and integrations.
- Device-specific advanced options that are proven on that hardware, rather than falsely hidden or exposed for all boards.

Distinguish four states for every property:
1. **Verified settable:** native backend accepts the value and effect, durability and recovery are tested.
2. **Verified read-only:** status is real but controlled by the OLT, optics firmware or hardware.
3. **Experimental:** native interface exists but consequences are not proven; expert-only, backed by tested recovery.
4. **Unsupported:** not present or inappropriate for this board; explain why and do not render a fake toggle.

**A-to-Z mutation contract for every verified settable item:**
- Discover backend and capability, with accurate hardware profile and dependencies.
- Read default, saved, active/effective value and units; distinguish unset and unavailable.
- Validate type, bounds, allowed enumerations and related constraints server-side.
- Describe affected services, risks and the exact proposed diff before applying.
- Execute a bounded, privilege-minimized native setter; no untrusted shell construction.
- Verify write durability from the authoritative source and verify the actual runtime consumer when possible.
- Explain whether live reload, service restart or next startup is needed.
- Test persistence across reboot, and firmware-bank switching where that data is intended to survive.
- Support recovery or an alternate management path if applying it can disconnect management or Internet.
- Handle partial write, stale form revision, concurrent request, lost session, backend errors and sensitive values.
- Maintain a per-platform evidence record for positive, negative, restart and recovery tests.

No general "Saved" banner may imply a daemon actually applied a value if only flash-environment storage was confirmed. Examples of independent effect checks include active netlink address after management IP change, real interface/VLAN state, an OMCI-visible field after a compatible restart, or a readback from the vendor-specific device interface.

## R02: usable configuration GUI and APIs

- One consistent capability schema shared by GUI, read-only API, validation and application. Do not duplicate hardcoded options that disagree.
- Essential controls in a clear residential view. Expert and diagnostic views expose full supported breadth.
- Searchable, grouped, responsive controls, accessible labels, dark/light contrast, contextual help, warnings and descriptions in ordinary language.
- Read and display values accurately. Mask secret inputs by default; support controlled replacement without echoing keys, PLOAM data or password hashes.
- Display unavailable features with explicit reasons and requirements. No silent no-op, ignored input or disabled field masquerading as a working control.
- Provide preview, confirm, apply, verified readback, required restart notice, saved/effective comparison and revert wherever supported.
- Offer backup of user configuration, migration between compatible firmware/boards and explicit restore conflict handling.
- Provide human-readable error logs or correlation references without leaking credentials.
- Every page, button, tab, graph, editor, firmware action and API endpoint must pass browser and backend tests. Include touch/mobile and both themes.

## R03: accurate live telemetry and performance monitoring

Minimum useful metrics:
- PON registration state and connection duration, loss-of-signal and registration attempt counts when observable.
- Optical RX/TX power in dBm, laser bias in mA, optic/CPU temperatures and supply voltage with actual data freshness.
- 10G host Ethernet negotiated link, direction-labelled bytes, packets, pause, FCS, alignment, drops and ring/queue errors.
- GEM/XGEM port counters, allocation state, payload limits and useful OMCI diagnostics with provider-controlled semantics clearly identified.
- CPU, RAM available, hardware and DMA reservations, process restart statistics, NAND/UBI capacity, wear/errors where exposed, boot and bank status.
- Optional ping/HTTP checks and thresholds when an actual routable management path exists.

Display proper units, sample age, data source and "unavailable" instead of invented zeroes. Any displayed warning threshold must be grounded in board-optics limits or explicitly configured by the user. Provide endpoint response size, rate and timeout limits.

### Throughput calculation

- Use monotonic hardware byte counters and elapsed monotonic time for directional rates, not advertised 10G Ethernet or OLT allocations.
- Handle unsigned 64-bit decimals without floating-point precision loss, especially values above 2^53. Convert only bounded valid delta values to rate calculations.
- Reject or reset samples after reboot, source/interface switch, counter reset/wrap, missing values, invalid elapsed time or impossible deltas. Record why a rate cannot be shown.
- Show instantaneous sampled Mbps, 5-minute rolling, 1-hour and daily averages, peak rates and total usage with clear interface direction.
- Distinguish Ethernet host data, GEM payload, optical service and router-measured end-to-end WAN traffic. None is interchangeable without evidence.
- No continuously running speed test. User-initiated tests should run from an appropriate endpoint, with consent and resource safeguards.

The existing vNext pure-Lua counter and event model is the starting point only. A source-tested library is not a running sampler or local database.

## R04: historical link/ISP connectivity and diagnostics

Record bounded, useful events:
- Startup, shutdown/reboot cause when available and actual bank transitions.
- PON O-state changes, O5.1 loss/recovery, LOS, OMCI restart or prolonged reauthentication.
- Host Ethernet link up/down and speed changes.
- Optic/thermal abnormalities, rising error and drop counters, service resets.
- User-initiated configuration, update, certificate and remote-access changes, without logging secret values.
- Optional tested management-to-gateway, DNS, ICMP or HTTPS probe results, if expressly configured and genuinely routable.
- Optional router integration to establish the subscriber's actual Internet availability and WAN throughput independent of the ONU optical status.

**Always separate three states:** optical/PON associated, host Ethernet connected, and actual external Internet path verified. An O5.1 association does not mean the router can reach the Internet.

History views should support last hour, 24 hours, 7 days, 30 days and an aspirational 90 days subject to storage budget. Show start/end, outage count, best available duration estimate, sample blind spots, reconnection, event severity, rolling utilization and trends. Export bounded JSON/CSV. Local history must not require a collector, but optional user-chosen external syslog or metrics is supported.

Before NTP is reliable, store boot-relative monotonic time and explicitly mark calendar time as uncertain. Do not invent wall-clock timestamps across offline periods, confuse a sample timestamp with an exact transition time, or calculate negative outage durations.

### Wear-aware persistence requirement

Use one low-overhead sampling subsystem with in-memory high-resolution ring buffers and only compact change events and coarse aggregate snapshots on persistent UBIFS. Initial engineering targets, not proven limits:
- 15 to 30 seconds for cheap PON/optical values.
- 15 to 60 seconds for Ethernet counters.
- Slower or on-demand heavier pontop, OMCI, or GEM interrogations.
- No more frequent than every 15 minutes for routine flash summary writes, with capped emergency/event flushes.
- Start with a bounded persistent history budget around 512 KiB, eviction of oldest entries and an explicit 90-day longevity test. Do not promise 90-day retention until validated against real event rates.
- Atomic write and rollback recovery after power failure; overflow must never block PON service or prevent management.
- Hard timeouts, shared sampling/caching, bounded CPU and RAM usage, backoff on failures and no duplicate competing agents.

High-cardinality, indefinite or subsecond history belongs on an optional external collector, not on the ONU.

## R05: safe measurable performance and stability engineering

First obtain repeatable baselines over multiple runs, including throughput from a capable router/endpoint, latency and packet loss, PON registration stability, optical power/temperature, Ethernet errors/drops, CPU/RAM use and power/thermal behavior.

Then optimize only where supported by the vendor/board and proven:
- Keep vendor hardware PON/SerDes/DMA packet forwarding as the primary datapath.
- Cache expensive status commands, reduce repeated LuCI/PON subprocess spawning, coalesce concurrent UI polls and prioritize optical service.
- Tune documented Ethernet negotiation, interrupt/queue paths, VLAN/OMCI and multicast behavior only after testing actual modes and rollback.
- Audit process supervision, bounded automatic daemon recovery, watchdog limits, logging pressure and startup race conditions.
- Measure effects of log volume, sampling interval, flash writes, routing and configuration on management load and subscriber service.
- Test full-rate idle/sustained/thermal scenarios, tagged/untagged traffic, PPPoE, multicast/IPTV, IPv4/IPv6, WAN loss with O5.1 maintained and power interruption.
- Consider safe package pruning only after dependency and late-loading tests, and preserve essential vendor libraries, microcode, trust/crypto libraries, recovery tooling and board profiles.

Avoid forcing extra PRX126 VPE/CPU cores online, overclocking, filling reserved DMA memory, changing optical laser calibration, NAND geometry or experimental kernel PON queue settings on the production stick. "More used memory" and "100% CPU" are not performance goals. The only acceptable improvement claim is measured service or recovery benefit under a repeatable test.

## R06: certificate management, management isolation and remote firewall

- Default local authenticated HTTPS and SSH reachable only through the intended management path, not unsolicited Internet exposure.
- Generate a device-local certificate with a correct SAN for the actual management IP and/or configured hostname. Display expiry, regenerate/replace safely and protect the private key with root-only access.
- Import a certificate, matched private key and optional CA chain for an operator-owned domain. Validate chain, key pairing, identity, expiry and target uhttpd support before activation.
- Public trusted CA services and enterprise PKI are optional, not basic residential requirements.
- Remote GUI access is explicitly disabled by default. When enabled, present a simple Linux firewall editor limited to relevant inbound management interfaces, source IP/CIDR, TCP ports, IPv4/IPv6 where supported and an easy revert. Always preserve a tested local recovery route.
- Firewall changes must never interfere with OLT management, OMCI, PON GEM traffic, ISP VLAN bridging or host dataplane throughput.
- Optional read-only metrics credentials and syslog settings remain separate from browser administrator authentication. NAT can collapse several clients into one apparent source address, so IP filtering alone is not proof of a unique collector.

## R07: multiple XGS-PON stick families

Separate **management-plane compatibility** from **native firmware image compatibility**.

A common app may monitor another stick via adapter without flashing it. Native AoTT firmware requires a hardware-specific build and independent qualification.

Core adapter interface should declare:
- Exact board/SoC/revision, ABI, bootloader, NAND/UBI geometry, optics/EEPROM and capability identification.
- Supported read-only telemetry, editable settings, units, validation and access controls.
- Source-of-truth native getters/setters, apply state, persistence and recovery procedure.
- MIB/service/UNI/GEM/VLAN options and any provider-specific constraints.
- Compatible kernel/bootcore/userspace/vendor libraries and exact archive/recovery safeguards.
- Per-feature test status and per-platform support level; never fabricate support by marketing label.

Initial stages:
1. Current Potron LL-XS1010 / PRX126 board as the deeply verified reference.
2. Individually verified PRX126 relatives, including appropriate WAS-110, ECI V2 and reseller variants, with separate board/flash profiles.
3. Read-only adapters or independent native ports for CIG, Cortina, Realtek and other SoCs. Never flash a PRX126 image onto another ABI/flash layout.
4. Additional tested OLT/service profiles, ensuring registration, VLAN/PPPoE/multicast, management recovery and optical behavior.

Each new device must have verified identification, private original firmware backups, recovery path, offline build, candidate image qualification, one-shot boot, network/PON acceptance and explicit final commit. Until then: candidate only, not supported.

## R08: safe firmware and release lifecycle

- Every private or public release has a unique build identity and exact per-bank image hash. Do not rely solely on r8 text strings when two different images share the same name.
- Keep both bank receipts, bootloader selections and component checksums inspectable, plus a read-only diagnostic recovery report.
- Preserve a known-working boot bank before any inactive-bank write. A one-shot trial does not auto-commit.
- Separate approval for staging, trial selection/reboot and permanent commit or rollback. A command timeout is not permission to rerun flash or reboot.
- Independent postboot acceptance must check PON, Ethernet, actual service where observable, management access, security/runtime files, durable credentials and both-bank readbacks.
- Release docs must distinguish source-only, built, staged, booted, committed, published, and tested on which exact board.
- Keep firmware binaries, per-subscriber settings, full flash, private keys, ISP registration identifiers and internal operator paths out of public releases.
- Attribute upstream community work and document what AoTT genuinely adds.

## R09: complete functional and release acceptance

A release can be considered residential-ready when basic fiber registration, Internet service via the user's router, administration, recovery and all advertised working controls are proven on at least one declared hardware profile. It does not require optional enterprise PKI or an external telemetry collector.

For every new/changed setting, complete: read -> validate -> preview -> set -> durable readback -> effective readback -> service consequence -> persistence -> recovery. If one step is not verifiable, mark the feature partially supported and state its limits.

For history, test: exact 64-bit counter math, loss/reset/reboot, NTP-unsynced clock, outage windows, retention eviction, flash-full handling, write interruption, corrupt recovery, API/UI graph rendering and privacy.

For compatibility, test: detection positive/negative cases, explicit board refusal, recovery archive geometry, actual hardware trial and OLT/service behavior.

For performance, report: setup, baseline, measured deltas, thermal/load conditions, statistical variability, regression outcomes and whether changes remain enabled.

## Definition of final target state

A user can choose compatible hardware, configure and verify every supported property, inspect real-time and historical PON and subscriber-service behavior, understand failures and optimize supported performance safely. The system explains unsupported/hardware-owned values, maintains durable settings and recovery, and expands to additional boards without pretending that every XGS-PON stick is firmware-interchangeable.

This document sets acceptance criteria. Implementation order and work IDs are in [Delivery plan](DELIVERY-PLAN-AND-ACCEPTANCE.md).
