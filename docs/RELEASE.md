# AoTT-8311-v2r3 source-only release

Product: AoTT-8311
Version: v2
Revision: r3
Machine identity: AoTT-8311-v2r3
Display identity: AoTT-8311-v2 r3
Hardware profile: potron-prx126-aott-v1

**Release status:** The corresponding private firmware image was tested and
committed on one compatible LL-XS1010 / PRX126-SFP-PON device. This public
repository remains a text-source overlay and is not a complete firmware image,
a redistributable binary package, or a guarantee of other-device support.

## v2r3 changes

- Preserve an existing management gateway when normalizing UCI settings.
  This fixes the management return-path regression observed in v2r2 while
  retaining support for deliberately unset gateways on new installations.
- Correct persisted root-password hash validation so diagnostic output cannot
  be mistaken for password hash material when applying the saved credential.
- Strengthen boot-time recovery checks, bank integrity verification, and
  password/key persistence validation.
- Retain guarded A/B install, trial boot, explicit commit, rollback, and
  independently verified off-device backups. These actions require
  appropriate administrator approval.
- Improve dark-mode graph readability, firmware labels, diagnostic messages,
  rootfs size qualification, and source regression tests.
- Retain the same qualified vendor kernel, boot components, PON/OMCI
  dependencies, and hardware ABI profile. No change to ISP provisioning.

## Qualification evidence

On the specifically qualified device, the private build passed staged-image
validation, independent bank readback, a single trial boot, and an explicit
permanent commit. Post-boot checks confirmed PON registration, host link
negotiation, authenticated SSH, HTTPS management, recovered configuration,
and retained fallback firmware.

The public source tests check release identity, credential persistence, UCI
gateway behavior, A/B state guards, runtime dependencies, LuCI compatibility,
and build/archive integrity. These tests are **not** a substitute for full
hardware qualification or authorized ISP interoperation.

## Known limitations

- The inherited vendor kernel did not start the three secondary CPU cores
  in the tested configuration. This requires separate platform research.
- A vendor device-tree pin-selection conflict was reported for the PON
  1PPS function. PON registration was functional in the qualified test.
- Other PRX-family, CIG-derived, or otherwise similar ONUs are not
  automatically compatible.
- A firmware source overlay alone cannot rebuild the proprietary vendor
  PON/OMCI binaries, kernel, bootcore, or a ready-to-flash archive.

## Publication boundary

No actual subscriber serial, registration credential, MAC address, production
WAN or management address, site hostname, personal account, SSH key, image,
screenshot, full-bank backup, or live configuration has been included in
the public source package.

Run the release and disclosure gates before publishing:

    python3 tools/verify_release.py .
    python3 tools/check_disclosure.py .
    python3 -m unittest discover -s tests -v

Review every change manually, along with Git history and any release assets.
Third-party attribution and license obligations must still be honored.

See [compatibility](COMPATIBILITY.md), [build qualification](BUILD.md),
[privacy policy](PRIVACY-AUDIT.md), and [roadmap](ROADMAP.md).
