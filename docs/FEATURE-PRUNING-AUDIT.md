# AoTT-8311 PRX126 feature and package pruning audit

## Audit scope

The offline reference tree is based on the tested Potron LL-XS1010
firmware lineage. The rootfs includes 1,856 SquashFS inodes with
approximately 27 MiB of extracted files, compressed into a 5.9 MiB
image. This report separates actual hardware/runtime dependencies,
features that are still configurable, and strictly optional assets.

The initial audit is not an exhaustive proof that every firmware file
is unused by every PRX126 installation. A module can be opened
dynamically, loaded conditionally on a specific OLT, or invoked by
a recovery workflow. The removal list is intentionally conservative.

## Confirmed unused for the audited SFP board

| Asset | Evidence | Compact action |
| --- | --- | --- |
| DSL status Overview include | PRX126 SFP module has no DSL modem or DSL hardware driver | Exclude the generic DSL Overview widget |
| WiFi radio Overview include | No wireless interfaces, radio configuration or matching drivers | Exclude the generic WiFi Overview widget |
| Wireless realtime page and two SVGs | The menu requires a wireless UCI device; none is configured on the audited SFP board. The SVGs are referenced only by this page | Exclude in compact profile with menu/config/import validation |
| Standalone Nano editor | Optional interactive CLI editor, not a boot or PON service | Exclude from compact build; keep in diagnostic build |
| Static MIB-format readme | Only documentation, not a MIB data file | Keep in GitHub docs/MIB-FORMAT.md and exclude from firmware |

Generic LuCI network infrastructure and the unmodified
wireless route implementation are not yet removed. Removing common
network modules without testing their dynamic imports could make
pages fail even without a wireless radio.

## Optional runtime-lean profile

The runtime-lean profile extends the compact profile by removing optional
stress tests, OMCI simulation, MTR, serial file-transfer programs,
Zstandard commands/wrappers, and the terminal/compression libraries
whose retained consumers are checked on each build. It preserves all
components listed in the next section, including OpenSSL `libssl`.

Review of the previous local proposal found two missing dependencies:
`zstdless` and `zstdgrep` still invoked the removed `zstdcat`, and the
vendor root login profile still defined an alias for removed MTR.
The revised plan removes both wrappers and only the exact audited
MTR alias, preserving any other login-profile content. Modified or
additional command references cause the planner to reject the image.

On the audited offline reference tree, the corrected plan removes
47 file/symlink paths totaling 1,612,270 unpacked file bytes, and removes
the 48-byte stock alias line. It checks 149 retained ELF files,
518 text files, and 280 retained symlinks before and after staging.
Those counts describe static review, not hardware or WAN qualification.

The checks cover ELF `DT_NEEDED`, embedded removed-library names,
retained source references including shell defaults such as
`${ZCAT:-zstdcat}`, optional symlink destinations, and stale runtime
integrity pins. Newly introduced dynamic construction, external scripts,
provider-specific behavior and recovery paths still require runtime
qualification. Keep the full diagnostic image available for optional
tools deliberately omitted from the lean profile.

## Explicitly retained

| Feature or artifact | Why it stays |
| --- | --- |
| OMCI daemon and libcrypto.so.1.1 | Running OMCI process loads OpenSSL libcrypto |
| Kernel, bootcore, PON drivers, PON microcode | Proprietary platform compatibility and forwarding |
| All seven selectable prx300 MIB templates | The user can select MIB variants for different OLT profiles |
| Timezone database | The system init and LuCI timezone picker reference it |
| SSH, HTTPS and Mbed TLS | Recovery and authenticated management |
| tcpdump and libpcap | The 8311-rarpd management daemon uses tcpdump as part of reverse-ARP handling |
| VLAN, QoS, GEM, PTP and multicast components | May depend on provider/OLT and configured service profiles |
| Both A/B bank controls and runtime integrity profile | Required for safe installation, rollback and recovery |
| LuCI page labels, form descriptions and necessary inline hints | Functional, user-facing interface elements |
| libiwinfo runtime database | Internal LuCI lookup data; not a user manual |

The current device exposes a 10G host interface and GEM/T-CONT
interfaces. It does not have built-in wireless or DSL hardware.
The physical SoC advertises other capabilities, such as PTP, which
may be legitimately used by some operators even when not currently
active.

## Higher-risk future candidates

- **OpenSSL libssl.so.1.1:** No direct executable dependency and
  no process mapping observed in a snapshot. The web TLS stack uses
  Mbed TLS. The file is pinned by the upgrade profile, so only the
  experimental offline profile removes it and updates that pin.
  Late runtime loads, alternative certificates and other operator
  features remain unqualified.
- **Other LuCI wireless pages and protocol handlers:** Remove only
  after mapping all menu routes, module imports, and network
  configuration options.
- **Unused netfilter/NAT helpers:** Many drivers are loaded, and
  provider traffic and multicast behavior can depend on some of
  them. Requires service-mode testing across OLT profiles.
- **Vendor PTP and debug utilities:** Leave in place until their
  feature dependencies and troubleshooting requirements are tested.

## Measured capacity changes on the offline PRX126 image

RootfsA and rootfsB are each allocated 6,221,824 bytes.

| Build | Image bytes | Headroom | Status |
| --- | ---: | ---: | --- |
| Full v2r1.1 source staging | 6,180,864 | 40,960 bytes (40 KiB) | Historical size, below preferred reserve |
| PRX126 compact with regenerated runtime pins | 6,127,616 | 94,208 bytes (92 KiB) | Offline checks pass, no boot qualification |
| Experimental compact without libssl | 5,988,352 | 233,472 bytes (228 KiB) | Offline checks pass, runtime compatibility unverified |

The runtime-lean unpacked byte count above is not a compressed saving.
Its exact image size must be recorded from the final assembled candidate
after version identity and runtime pins have been synchronized.

The three additional wireless-only assets had zero extra 4 KiB-aligned image savings compared with the existing compact image.
Removing CSS comments/whitespace saved zero padded image bytes.
Hardlinking duplicate `libnl` files also saved zero padded image
bytes because SquashFS already deduplicates matching content.
Dropping tcpdump/libpcap appeared to save significant space, but
it was rejected after finding the live rarpd source dependency.

## Integrity review

The original runtime profile pinned eight source paths that changed
in the v2r1.1 development branch. An unmodified profile would
reject those files even when their code compiled correctly.

The new offline profile refresher allows only source-manifest-matched
candidate files to be repinned. It forbids unreviewed changes to
vendor, common, kernel and bootcore components.

The PRX126 compact tree passed the exact shell-based runtime
profile checker in both candidate and common modes. The compact
SquashFS image also passed the bundled SquashFS superblock checker.
Neither test proves an installed ONU will boot or register to the OLT.

## Firmware packaging and GitHub safety

All audit explanations, MIB documentation, compatibility notes,
build profiles and this report remain in the GitHub source repo.
No full firmware images, private flash backups, configuration, SSH
keys, MAC addresses, or subscriber serials are included.

The historical compact test rootfs used the older v2r1 firmware
version identifiers. Proper release versioning, hardware qualification,
a tested rollback and an explicitly approved installation are required
before deploying a newly assembled release candidate.

Further details and reproducible read-only evidence are in
[the PRX126 dependency and resource audit](PRX126-DEPENDENCY-AND-RESOURCE-AUDIT.md).
