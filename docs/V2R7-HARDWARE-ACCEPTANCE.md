# AoTT-8311 v2r7 hardware acceptance and current release status

Status as of 2026-11-01: **Privately hardware-tested, running and permanently committed** on one qualified OEM/Potron LL-XS1010 / PRX126-SFP-PON unit. The public distribution is a sanitized **source overlay only**, not an installable firmware image.

## What changed

v2r7 refines inherited realtime Overview graph rendering: optical and traffic series labels, grid lines, and light/dark contrast remain readable across equivalent inline CSS styles. It refreshes revision-specific web asset identifiers. It retains the v2r6 firmware-bank guards, vendor PON/OMCI dependencies, kernel, bootcore, cryptographic ABI, management access and fixed UBI geometry.

## Independently verified offline qualification

- 300 source regression tests passed, including 46 real Chromium browser scenarios.
- All 29 static stage-only safety checks passed.
- Two independently built private rootfs images and firmware archives were byte-identical.
- The aligned rootfs occupies **5,689,344 bytes** of the fixed **6,221,824-byte** bank, leaving **532,480 bytes (520 KiB)** headroom.
- 68 curated overlay source files were manifest-verified. The original common vendor ABI pins remain unchanged.
- Source disclosure and secret scans passed. Only source text, documentation, fixtures and test tooling may be published; private archives, captures and provisioning are excluded.
- The private release archive's `UNTRIALED_OFFLINE_ONLY` and `safe_for_live_install=false` fields are immutable **build-time** records. They do not describe the subsequent approved hardware trial or authorize unreviewed flashing.

## Hardware trial and permanent commit

The exact reviewed v2r7 candidate was staged into the inactive bank after fresh full-bank off-device backups had been captured and independently verified. A separately approved one-shot boot established the new running firmware without changing the then-committed recovery bank.

Independent posttrial checks verified the new boot identity, PON O5.1 registration, negotiated 10 Gbps host Ethernet, management HTTPS, WAN connectivity, persistent root/SSH recovery, and complete readbacks of both firmware banks.

Under another distinct approval, the running v2r7 bank was permanently committed. The independent postcommit readback verified that v2r7 was committed in bank B:

| Check | Verified result |
| --- | --- |
| Running and committed version | AoTT-8311-v2r7 |
| Active and committed firmware bank | B / B |
| Valid on-device alternative | AoTT-8311-v2r6 in bank A |
| Pending activation or uncommitted trial | None |
| PON and host link | O5.1 registration / 10 Gbps Ethernet negotiation |
| Management, WAN and root/SSH recovery | Passed |
| Both complete firmware-bank integrity checks | Passed |
| Full private recovery backups | Verified off-device |
| Flash write or reboot during commit | None |

These are point-in-time acceptance checks on one device, not a throughput guarantee or evidence that other chipset/board variants are supported. Longer-term stability and high-load behavior remain unqualified.

## Release and redistribution boundaries

Do not convert this private hardware acceptance into a public binary firmware release. Distribution rights for proprietary vendor components and third-party dependencies require separate review. The source tree cannot by itself produce a safe universal flashable image.

The historical [v2r7 candidate notes](V2R7-RELEASE.md) preserve what was known **before** trial and commit; this document records the later successful private acceptance. For future work, see the [v2r8 plan](V2R8-PLAN.md) and the [roadmap](ROADMAP.md).

No registration identifiers, site-specific networking, private hostnames, device-specific credentials, capture logs, or full-bank images are included in this documentation.
