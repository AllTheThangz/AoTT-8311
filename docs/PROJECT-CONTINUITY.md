# AoTT-8311: project continuity and verified state

**Successor source checkpoint:** [November 6 r9 integration](V2R9-INTEGRATED-RELEASE.md) combines the 89-file runtime and assigns the distinct r9 identity. This file retains the original November 2 hardware/source snapshot below. It must not be used as current bank evidence.

## Current local integration checkpoint, November 5, 2026

The last full approved runtime result is `d0d4a799ee660f2ddcebbf2ad444dba052995e0e`: **1,131 distinct tests passed**, zero failures/errors/skips. The current [native-reader resolution](C-014-NATIVE-READER-RESOLUTION.md) has **35 focused tests passing** and requires its own combined regression.

Actual read-only ONU access is available through the existing Hermes-user SSH profile with strict pinned-host verification. The earlier statement that no direct MCP target meant no usable access was incorrect. The baseline showed matching reader/wrapper/library hashes and a working native reader. The new six-key reader also succeeded on-device from standard input: two matching snapshots, three present keys, three unset, none present-empty, without exporting values or installing code.

The emulated reader failure is resolved for the tested configurations. A long custom `-l` argument triggered behavior consistent with the U-Boot 2018.03 lock-path allocation defect. The unpatched reader passes all four private-image cases with a short relative lock path. The original failed evidence is preserved, not relabeled.

The scoped read path now distinguishes unset and present-empty values. Actual setter tests on disposable images confirm ordinary apply/restore and the inability to restore present-empty via an empty setter argument. No live setters were invoked. Production write/restore, cache coordination, durable storage and physical interruption/reboot acceptance remain open. Source publication remains unresolved and the deployable overlay stays unchanged.

## Start here every session

Read these documents in this order:

1. [Project continuity and current state](PROJECT-CONTINUITY.md), this file.
2. [Desired product and engineering requirements](TARGET-STATE-AND-REQUIREMENTS.md).
3. [Configuration coverage baseline](CONFIGURATION-COVERAGE.md).
4. [Delivery backlog, sequencing and acceptance](DELIVERY-PLAN-AND-ACCEPTANCE.md).
5. [Decisions and unresolved questions](ENGINEERING-DECISIONS.md).
6. [Resume and finish protocol](RESUME-CHECKLIST.md).
7. Existing [compatibility](COMPATIBILITY.md), [architecture](UPSTREAM-ARCHITECTURE.md), [monitoring](MONITORING-AND-TELEMETRY.md) and detailed release documents as historical/reference material.

Private operational receipt paths, exact firmware hashes and full-flash recovery archives are kept in the maintainer's root-only operational vault, not on GitHub. A new session must check that vault and the live device, not infer the current bank selectors from a public document.

## Product in one paragraph

AoTT-8311 is an advanced but approachable replacement and extension of the community 8311 firmware for residential XGS-PON SFP+ ONUs. Its intended users want reliable service on compatible user-selected fiber hardware, rather than provider-mandated equipment. Its value is **full supported configurability, honest PON/Internet diagnostics, throughput and uptime history, safe measurable performance improvements, predictable recovery, and expanded board compatibility**. Ordinary use should be simple. Expert controls must be available when the platform actually supports them.

This is not an enterprise firewall appliance, a router, an OLT provisioning system, or a universal image for unrelated chipsets. It cannot grant additional provisioned ISP bandwidth or override OLT-controlled GEM/T-CONT allocations.

## Four different states that must never be conflated

| State | Verified as of this snapshot | What it does and does not establish |
| --- | --- | --- |
| Public repository main | Source-only r7; release.json revision r7, README describes r8 as future | Does not represent the latest private tests or live hardware |
| Existing open draft PR #11 | Earlier source work on r8 syslog and authenticated metrics | Not proof that current private r8 image is published or merged |
| Privately tested firmware | Security-enhanced AoTT-8311-v2r8, one real PRX126 unit | Full image built, staged, trial-booted and independently checked; not publicly distributed |
| Separate vNext development | Source-only next-generation capability/history prototype | 391 source tests and 53 portable Lua fixture checks passed; not flashed or released |

Never label private r8 as merged/public, or vNext as installed. A passing source regression suite does not independently certify all configuration controls on live hardware.

## Last verified live device

An OEM/Potron LL-XS1010 / PRX126-SFP-PON module was running the **security-enhanced r8 trial in bank B**, while **original r8 in bank A remained the committed fallback**. No pending activation existed. Both banks had complete valid records. The device reported XGS-PON O5.1 registration and a 10 Gbps Ethernet host link. The authorized single reboot into B was successful and a separate read-only postboot verifier passed. **Bank B was not permanently committed.**

The original and enhanced images share a human-readable r8 version label, so a proper operator check must distinguish them by bank, precise image fingerprint and component receipt, not by version alone.

The pretrial r7 image remains in separately verified private full-bank recovery archives, but was overwritten on-device when the enhanced r8 was staged. There is no reason to boot r7 merely to move forward with this r8 trial.

Historical issues that must remain documented:
- First trial command used an incorrect native guarded argument order, returned exit code 2 and did not reboot.
- Corrected command selected B and requested one reboot.
- The original postreboot test process exited early on transient SSH reconnection. An independent read-only verifier later confirmed the successful boot, correct hashes, both bank readbacks and service health.
- Do not erase the failure receipts or interpret them as a boot failure.

## What exists and what is unfinished

| Domain | Current verified or source-demonstrated capability | Remaining work |
| --- | --- | --- |
| PON/OMCI | Optical state, MIB and GEM diagnostics; vendor PON/OMCI service and registration preserved | Every supported field must be validated end to end; profiles tested on more providers |
| Basic settings | 54 GUI firmware environment fields with shared schema validation and checked saves | Effective consumer and persistence test per field; repair hidden or absent options |
| Management UI | LuCI organization, dark-mode readability improvements, live health/security views | Full page-by-page function audit, responsive/mobile, clear effective versus saved values |
| Ethernet traffic | Sampled byte/packet counters, errors/drops and browser-calculated short rates | Accurate persistent throughput history, average/peak charts, reset-safe arithmetic |
| PON/ISP history | Current PON state and uptime visible | Durable registration/loss events, outage durations, signal trends and separate Internet reachability |
| Logging | Local logs; optional syslog and metrics source in private r8 | Verified delivery and source/persistence, useful local event viewer, retention controls |
| TLS/access | HTTPS, SSH and a read-only diagnostic page | Self-signed cert generator, owned-domain cert upload, private-key permissions, simple remote-access opt-in firewall |
| Firmware recovery | Native A/B integrity and guarded stages, trials, commit and rollback | Continue verifying on each board; retain original working fallback before each risky update |
| Performance | Hardware forwarded fiber data path and basic resource telemetry | Benchmark, optimize safe supported settings and demonstrate sustained gains |
| Hardware compatibility | One tested PRX126 board profile | Explicit per-board adapters; another PRX126 family; other SoC families as separate ports |

Private observation: the tested HTTPS certificate lacked a SAN and the root-owned private key had permissive local read access. A current security status warning does not itself fix the certificate or permissions. Likewise, optional collector trust, shared-NAT source identity and untrusted network ingress still require qualification when those features are enabled. They are not universal residential release prerequisites.

## Development baseline and reproducibility

The private r8 source regression suite passed **385 tests, zero skips** with host/vendor-MIPS and real Chromium checks. The private image was built as independently matching pairs with measured fixed-bank headroom and successful native hardware stage/readback.

The isolated vNext workspace later passed **391 source regression tests, zero skips**, including six new capability-audit tests. A standalone pure-Lua history model passed **53 checks each** under host Lua 5.1 and the actual vendor MIPS Lua runtime. Both manifest and disclosure gates passed. This is **source-only**. There is still no deployed persistent throughput/history sampler.

The vNext static inventory currently finds **54 GUI firmware-environment settings**, **13 offline vendor UCI configuration domains**, and **three specifically identified missing/disabled candidate controls**. These are evidence of configuration surface, not proof of full coverage. Refer to [the detailed inventory](CONFIGURATION-COVERAGE.md).

## Decisions already settled

- Residential simplicity is the default experience; deep configuration remains available under clear expert sections.
- Every genuinely supported, settable item should be reachable and work through the entire save/apply/effective-readback/recovery chain. Device/OLT-owned values may remain read-only with reasons.
- Monitoring is a core feature, not a synonym for installing Prometheus. Useful local history and an optional user-controlled external collector can coexist.
- Show optical registration, host Ethernet and verified subscriber Internet connectivity as distinct conditions.
- User-generated local HTTPS certificates and imported certs for operator-owned domains are supported goals. Public PKI is optional.
- Remote management and its configurable Linux firewall are opt-in, not a required enterprise dashboard.
- Reliability and actual WAN throughput matter more than inflating apparent CPU or RAM utilization.
- An XGS-PON or PRX126 label alone does not establish binary compatibility. Adapter detection precedes any device-specific write.
- Keep public docs/source free of private provisioning, key material, actual network identifiers and proprietary complete firmware images.

## Canonical near-term work

1. Stabilize and explicitly accept or decline the *current uncommitted r8/B hardware trial*. Never treat ordinary "continue" as approval for a permanent commit.
2. Build the setting-by-setting capability registry and positive/negative tests, starting with the known broken management VLAN path.
3. Connect the tested rate/event model to a bounded sampler and read-only API, with no NAND history writes until wear/retention design is tested.
4. Add persistent event/throughput history, distinguishing PON loss, host link loss, and optional router-side verified Internet outage.
5. Build and test local certificate generation/import, root-only key storage and conditional remote firewall management.
6. Build a board-neutral capability facade, a tested second PRX126 profile, and board-specific recovery-safe firmware packaging.
7. Establish repeatable service performance baselines, apply only measured safe optimizations and document results.

Work-item IDs, dependencies and exit conditions are in [the backlog](DELIVERY-PLAN-AND-ACCEPTANCE.md). Keep every in-progress item either complete with evidence or explicitly open with a next action.

## Document update policy

At each substantial development milestone, update or date-supersede this file, the backlog, any affected coverage entries, and the private operational ledger. Record:
- Evidence source, date, exact test result and relevant image/branch identity.
- What changed and what did NOT change.
- A failure report even when a later independent check recovered the outcome.
- Next concrete task and required approval, not a generic promise to continue.

**Do not silently rewrite this dated checkpoint as though it were current live truth.** Create a newer dated state entry or explicitly update its verification date after fresh checks.
