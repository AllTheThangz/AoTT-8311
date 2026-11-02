# AoTT-8311 roadmap and current development stages

**Verified project checkpoint:** November 2, 2026. This roadmap describes historical work, private hardware milestones and desired future work separately. For all work IDs, dependencies and completion gates, see [the delivery plan](DELIVERY-PLAN-AND-ACCEPTANCE.md).

## Public source versus private hardware

| Stage | Status at the checkpoint |
| --- | --- |
| Public `main` | Source-only `AoTT-8311-v2r7`; no public ready-to-flash firmware image |
| Existing draft PR #11 | Earlier v2r8 syslog and metrics source work; not a verified complete image |
| Private original r8 | Verified and committed in bank A on one qualified PRX126 device |
| Private security-enhanced r8 | Built, staged, successfully trial-booted and independently accepted in bank B; **not permanently committed** |
| vNext | Source-only configuration coverage and portable history-math prototype; not deployed |

Both private r8 variants share a human-readable version label. Exact image hashes and live bank inspection, retained in the private operational record, are required before any device operation. A dated checkpoint does not automatically remain current after a reboot or commit.

## Completed historical firmware milestones

- **v2r4:** LuCI and PON Managed Entity Explorer fixes, dark-mode improvements, network-management recovery.
- **v2r5:** Web request-validation hardening, size/dependency audits, private trial and commit.
- **v2r6:** Boot/reboot consequences, native guarded action fingerprints, A/B recovery and reproducibility checks.
- **v2r7:** Successful private firmware commit, improved light/dark Overview graph contrast, and comprehensive source/browser and independent hardware acceptance.
- **Original v2r8:** Private stage to A, successful one-shot trial and then committed A without rebooting into r7.
- **Security-enhanced v2r8:** New private source, manifest/privacy tests, 385 regression tests, independent matching offline image pair, stage in B and one-shot trial. The original r8 in A remains committed. A postreboot helper stopped on transient SSH while a separate independent read-only hardware acceptance succeeded. Historical failure receipts remain preserved.
- **vNext foundation:** Separate source-only workspace with 391 passing regressions and 53 host/vendor-MIPS history-math fixture checks; static audit identifies 54 currently exposed environment controls, 13 vendor UCI config domains and three candidate gaps. This is not an installed firmware build or completed on-device history service.

The earlier release documentation retains the history appropriate to each revision, but it must not be read as an up-to-date report of the currently active firmware. See [project continuity](PROJECT-CONTINUITY.md).

## P0: finish what exists and make controls real

- Complete the practical residential acceptance of the active private r8 trial. Never permanently commit on the basis of a routine development instruction.
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
