# AoTT-8311 roadmap and current development stages

## V3r1 RC3 hardware-stage candidate

The exact RC3 source is pinned at `release/v3r1-rc3` / `00c6d096a4051a20de80e0fcfe7dc39f257f56ef`. RC3 adds the first-authenticated-GUI-login password advisory while retaining `root/root` as an allowed public default. It passed 1,224 source tests, 41 deployment-sensitive vendor-MIPS tests, 134 real Chromium tests, and a byte-identical two-build private firmware audit. See [V3r1 RC3 qualification](V3R1-RC3-QUALIFICATION.md).

The unchanged r9 reference unit passes the RC3 read-only pre-stage gate with A active/committed, B as the valid inactive recovery bank, PON O5.1, 10 Gbps host Ethernet, HTTPS and pinned-key SSH healthy, fresh full-bank backups matching current live receipts, and the factory `root/root` state accepted. RC3 is technically stage-ready but no stage, trial or commit authorization has been issued.

## V3r1 RC1 offline-qualified candidate

The exact integrated candidate at `f3e3bbf3029a21ea9c6d8e3ec24cda10e92a1966` is pinned as `release/v3r1-rc1`. It passed the complete source suite, the recovered real Chromium suite, targeted vendor-MIPS qualification for history, management preflight, TLS activation, and credential preservation, and a byte-identical two-build private firmware audit. See [V3r1 RC1 offline qualification](V3R1-RC1-OFFLINE-QUALIFICATION.md).

The reference r9 unit remains unchanged. The prior RC1 administrator-credential restriction has been removed for continued V3 development: documented factory `root/root` is an allowed/default state and does not block an inactive-bank write.

## V3 development branch, November 7, 2026

dev/v3 is now the major-version development line based on the hardware-qualified r9 release-candidate lineage. The first V3 integration cut is AoTT-8311-v3r1 source-only and has not been flashed, trialed or committed on hardware.

V3r1 now integrates an opt-in RAM-only local-history worker and authenticated History UI/API on top of the bounded history model/sampler/export and dual-lock handoff primitives. The worker is disabled by default and performs no periodic flash-history write. Post-RC3 A-to-Z development has expanded the Configuration schema to **55 controls** and now routes every field explicitly: **22 live**, **6 guarded management**, **22 guarded PON/OMCI**, **4 guarded one-boot**, and **1 credential**. No high-risk field may silently fall through to generic persistence. Management changes use persistent recovery, exact runtime convergence, reconnect confirmation and rollback; PON/OMCI changes use separate environment/UCI/MIB recovery and never treat local readback as OLT acceptance; boot-only fields use one-boot trials with watchdog rollback. A new **Access & servers** page adds 20 guarded SSH/uHTTPd/LuCI settings with runtime verification and HTTPS confirmation. These source paths remain hardware-unqualified until the appropriate live apply/effect/revert/reboot or test-OLT evidence exists. TLS candidate activation is integrated; operator-owned certificate import and optional remote-management firewalling remain gated.

The exact committed r9 image remains the proven live PRX126 baseline until a separately authorized V3 inactive-bank stage and one-shot trial pass all deployment gates. V3 preserves any supported configured root credential before bank mutation, including the documented factory `root/root` default. Read-only local-history resource evidence is recorded in [V3 history runtime qualification](V3-HISTORY-RUNTIME-QUALIFICATION.md); live recovery-storage, native-source, and UCI-plan evidence is recorded in [V3 management preflight qualification](V3-MANAGEMENT-PREFLIGHT-QUALIFICATION.md); HTTPS key-mode and inactive candidate evidence is recorded in [V3 TLS candidate qualification](V3-TLS-CANDIDATE-QUALIFICATION.md).

## Current release integration, November 7, 2026

[AoTT-8311 v2r9](V2R9-INTEGRATED-RELEASE.md) has completed its integrated source regression, reproducible private build, guarded hardware stage, one-shot trial, independent postboot acceptance and permanent commit on one LL-XS1010 / PRX126-SFP-PON device. Final verified state is r9 active and committed in bank A, with enhanced r8 preserved as the complete valid bank-B recovery image. See [r9 hardware acceptance](V2R9-HARDWARE-ACCEPTANCE.md).

The public repository remains source-only. The immutable `release.json` `offline-candidate` value records build-time state; later hardware qualification is documented separately. The exact post-RC3 A-to-Z source checkpoint `023b8865a956b6ff13935e1c703bb7e414b0942e` was independently built twice with identical rootfs/archive output; it retains 380,928 bytes of rootfs-bank headroom and remains hardware-unqualified. MIB selection is now configuration-driven rather than filename-only: the selected runtime profile is parsed for UNI topology, T-CONT/queue/scheduler structure, IP Host/VEIP presence, native defaults, and setter applicability, with the same capability rules rechecked in the guarded PON worker. The next P0 work is **qualification, not another routing rewrite or firmware-version bump**: exercise the source-complete transaction classes on appropriate hardware, capture apply/effect/revert/reboot evidence, qualify each alternative MIB/provider-facing profile on a spare/test OLT, and complete the remaining page-by-page C-017 audit.

Persistent history, operator-owned certificate import, remote-access firewall controls, performance qualification and cross-stick support remain follow-on work.

**Verified project checkpoint:** November 7, 2026. For all work IDs, dependencies and completion gates, see [the delivery plan](DELIVERY-PLAN-AND-ACCEPTANCE.md).

## Public source versus private hardware

| Stage | Current status |
| --- | --- |
| Public source | `AoTT-8311-v2r9` sanitized source; no public ready-to-flash firmware image |
| Private r9 | Built reproducibly, staged in A, trial-booted, independently accepted and permanently committed in A |
| Private security-enhanced r8 | Complete and valid in bank B as the on-device recovery image |
| Older releases | r7/r6 and earlier recovery material retained privately as historical evidence |
| vNext | Configuration transaction, history, certificate, firewall, performance and compatibility work continues source-first |

Exact image hashes and live bank inspection remain required before any future device operation. A dated acceptance does not authorize a later flash, trial, rollback or commit.

## Completed historical firmware milestones

- **v2r4:** LuCI and PON Managed Entity Explorer fixes, dark-mode improvements, network-management recovery.
- **v2r5:** Web request-validation hardening, size/dependency audits, private trial and commit.
- **v2r6:** Boot/reboot consequences, native guarded action fingerprints, A/B recovery and reproducibility checks.
- **v2r7:** Successful private firmware commit, improved light/dark Overview graph contrast, and comprehensive source/browser and independent hardware acceptance.
- **Original v2r8:** Private stage to A, successful one-shot trial and then committed A without rebooting into r7.
- **Security-enhanced v2r8:** New private source, manifest/privacy tests, independent matching image pair, stage and one-shot trial in B, then later committed as the verified recovery image before r9 staging. Historical transient-SSH and acceptance receipts remain preserved.
- **v2r9:** Integrated 89-file runtime, 1,304/1,304 combined regression, reproducible private build pair, guarded A-bank stage, one-shot hardware trial, independent runtime/bank/network verification and permanent A-bank commit. Enhanced r8 remains the bank-B recovery image.
- **vNext foundation:** Configuration-transaction, history, certificate, firewall, performance and compatibility prototypes continue source-first beyond the committed r9 runtime.

The earlier release documentation retains the history appropriate to each revision, but it must not be read as an up-to-date report of the currently active firmware. See [project continuity](PROJECT-CONTINUITY.md).

## P0: finish what exists and make controls real

- Treat committed r9 as the current PRX126 baseline. Do not change banks or create a new firmware revision merely to continue source development.
- Build a unified capability registry for every actually supported setting, not merely those currently rendered in the GUI. Track backend owner, applicability, constraints and saved versus effective values.
- Validate each settable item **A to Z**: read, validate, preview, apply, durable readback, runtime readback, restart/bank persistence and recovery. Mark unsupported, read-only and experimental items clearly.
- Repair the hidden management VLAN control and investigate upstream-documented device serial/factory-mode fields, where hardware behavior is proven and a recovery route is available.
- Audit all UI pages, forms, status graphs and API actions so no control claims to work without real functional evidence.
- Preserve the working PON/OMCI services, fixed A/B bank geometry and appropriate firmware fallback.

## P1: core historical monitoring and better residential operation

- Show true sampled Ethernet/GEM throughput, utilization, rolling and peak rates, errors and reset-safe counters, not an implied ISP speed from the host's 10G link.
- Keep bounded optical power/temperature and PON state history, outage and reconnection counts, host Ethernet changes, and verified router-side Internet-path tests where supported.
- Use a single low-overhead sampler, RAM ring, bounded flash event/summaries and explicitly tested retention/power-loss behavior. No unbounded database or aggressive NAND logging.
- Implement local self-signed certificate generation with correct SAN, secure key handling, and import of a user's own domain certificate.
- Keep local HTTPS/SSH simple by default; add a configurable basic Linux firewall only when remote GUI access is deliberately enabled, without affecting bridged PON traffic.
- Retain optional external syslog and read-only metrics for users who want their own collectors, not as mandatory enterprise infrastructure.
- Measure safe performance gains under repeatable throughput, latency, packet-loss, CPU, thermal and PON stability testing. Do not increase CPU or consume reserved DMA memory merely to show higher utilization.

## P1 and P2: actual cross-stick support

- Separate a shared management/UI/history model from adapters that declare each board's real capabilities and setters.
- Verify another PRX126 board profile independently with its own ABI, optics, bootcore/kernel, storage geometry and recovery.
- Expand to further independently tested PRX126 variants, then use read-only adapters or separate native ports for unrelated SoCs such as Cortina or Realtek.
- Do not flash a single image to all XGS-PON SFP+ modules based on form factor, reseller name or chipset family alone.

## Release and privacy principles

- Preserve complete private recovery backups off-device and an on-device known-working committed bank during a trial.
- Every flash, trial/reboot and permanent commit is an independent, explicitly authorized action, with native state and integrity verification. Never automatically retry a write on uncertain SSH results.
- Do not publish subscriber identity, provider credentials, private addresses, complete flash backups, proprietary vendor firmware blobs or private keys.
- Public source-only docs and working prototypes do not amount to a supported firmware release.
- Credit the upstream [8311 Community Firmware](https://github.com/djGrrr/8311-was-110-firmware-builder) and do not characterize inherited features as new AoTT inventions.

## Canonical project handoff

Read [project continuity](PROJECT-CONTINUITY.md), [target-state requirements](TARGET-STATE-AND-REQUIREMENTS.md), [configuration coverage](CONFIGURATION-COVERAGE.md), [delivery plan](DELIVERY-PLAN-AND-ACCEPTANCE.md), [engineering decisions](ENGINEERING-DECISIONS.md) and [resume checklist](RESUME-CHECKLIST.md) in order. Update the dated evidence and unfinished work IDs after each substantial session.
