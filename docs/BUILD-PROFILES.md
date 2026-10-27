# PRX126 rootfs pruning and build profiles

## Policy

Only prune functionality that cannot operate on the target hardware
or is deliberately optional. Do not remove any runtime dependency
because a file was not seen in one short process listing. Libraries
may be loaded on demand, and all protected components require
full interoperability testing.

**These utilities work exclusively on a local, offline rootfs directory.
They cannot flash, reboot, resize UBI, restore credentials, or change
a running ONU.** Outputs may still contain the source image's vendor
binaries or configuration and must remain outside public Git history.

## Profiles

| Profile | Exact exclusions | Status |
| --- | --- | --- |
| \`documentation-free\` | \`etc/mibs/readme\` | Offline documentation cleanup |
| \`prx126-compact\` | Documentation cleanup, Nano editor, DSL and WiFi Overview panels, the wireless realtime view and its two SVG resources | Offline PRX126 SFP candidate |
| \`experimental-no-libssl\` | Compact removals plus OpenSSL \`libssl.so.1.1\` | Explicitly experimental, not hardware-qualified |

The removed Overview panels require physical DSL and wireless radios.
They are not usable on the audited PRX126 SFP board. The standalone
wireless realtime page and its SVGs are pruned only if the LuCI menu
retains its wireless-device UCI condition and no wireless configuration
is present. The resulting extra space savings round down to zero in
the 4 KiB-aligned compressed image. Other generic
LuCI code remains until its dependencies and routes are reviewed.

All profiles retain:

- The PON daemon, proprietary OMCI and firmware dependencies.
- OpenSSL \`libcrypto.so.1.1\`, which the OMCI daemon loads directly.
- Mbed TLS runtime libraries for the HTTPS interface.
- A/B bank controls, boot safety and recovery utilities.
- All MIB \`.ini\` templates and user-selectable timezones.
- Nano, tcpdump and libpcap in the diagnostic/full path as appropriate.
- \`tcpdump\` and \`libpcap\` even in compact builds, because the
  existing \`8311-rarpd\` management service uses tcpdump.

OpenSSL \`libssl.so.1.1\` has no observed direct ELF consumers or
active process mappings on the audited module, but another program
could load it later. Experimental pruning requires an explicit flag.
The corresponding candidate pin in the runtime integrity profile
is updated only in the offline copied tree. No production deployment
claim follows from that change.

## Plan without changes

\`\`\`sh
python3 tools/prune_rootfs.py \
  --source /path/to/CLEAN-offline-rootfs \
  --profile prx126-compact
\`\`\`

## Create a new offline stage

\`\`\`sh
python3 tools/prune_rootfs.py \
  --source /path/to/CLEAN-offline-rootfs \
  --profile prx126-compact \
  --destination /path/to/NEW-offline-stage \
  --stage
\`\`\`

The destination must not already exist. Existing source files and
settings are never changed by this command.

## Refresh the source integrity contract

An AoTT code update changes the hash of several files pinned in the
firmware's runtime compatibility profile. A correct source tree can
still fail the installed firmware's readback verification if those
pins are stale.

The offline profile refresher allows updates **only** to explicitly
reviewed candidate files included in \`MANIFEST.json\` with matching
file sizes and SHA-256 values. It refuses drift of vendor components,
links, unlisted files and all \`common\` runtime records.

\`\`\`sh
python3 tools/refresh_runtime_profile.py \
  --rootfs /path/to/NEW-offline-stage \
  --source-manifest MANIFEST.json \
  --refresh-reviewed-candidate-pins
\`\`\`

The resulting \`lib/8311-release-profile\` belongs inside the
assembled offline firmware tree. It is a runtime integrity contract,
not user documentation.

## Measure compressed capacity

Use the target's actual UBI volume capacity, not nominal NAND size.

\`\`\`sh
mksquashfs /path/to/NEW-offline-stage /path/to/out.squashfs \
  -comp xz -b 1048576 -no-xattrs -noappend \
  -no-progress -processors 2
\`\`\`

Re-extract and verify before any hardware testing. The separate
\`tools/qualify_offline_image.py\` verifies a completed five-member
upgrade archive, including hashes, image padding, and the UBI
capacity budget.

Measured offline on the audited rootfs, removing Nano alone saved
about 48 KiB of final image size. Excluding \`libssl.so.1.1\` saved
about 136 KiB, but is not qualified for production use.
Removing CSS comments and creating hardlinks for content duplicates
did not reduce the final padded image size.

## Documentation location

Static MIB format notes, manuals, troubleshooting guides and build
documentation live in GitHub under \`docs/\`, not on the ONU.
Short, essential labels and explanations visible in the web UI remain
runtime user-interface content, not build documentation.

The following files are **not** disposable documentation:

- \`usr/share/libiwinfo/hardware.txt\` is a runtime lookup database.
- \`usr/share/fw3/helpers.conf\` contains firewall-related configuration.
- \`etc/modules.d/nf-nathelper-extra\` controls module loading.
- \`lib/8311-release-profile\` verifies firmware consistency.
- \`etc/mibs/*.ini\` are selectable runtime MIB inputs.

## Current v2r1.1 source candidate is not a release image

The current offline staging tree still identifies itself as
FW_VERSION=AoTT-8311-v2r1 and FW_REVISION=r1. This is intentional
while the source changes are being qualified. Do not label, sign,
publish, flash or attempt to commit it as v2r1.1.

Before any installation, an independently reviewed release builder
must synchronize the version fields in /etc/8311_version, the
Lua version module, release metadata, upgrade control file and
all runtime integrity pins. It must then verify the generated archive,
the active and fallback bank identities, and the target hardware.

Source-only tests and a valid compact SquashFS image are not evidence
that the new release is bootable. The experimental OpenSSL library
removal also requires its own boot and late-loading test.

## Installation qualification

Profiles are not interchangeable with tested binaries. Never publish
a complete firmware image with user-specific provisioning or
proprietary vendor dependencies until redistribution rights and
board-specific recovery and bootability testing are complete.

Further details and reproducible read-only evidence are in
[the PRX126 dependency and resource audit](PRX126-DEPENDENCY-AND-RESOURCE-AUDIT.md).
