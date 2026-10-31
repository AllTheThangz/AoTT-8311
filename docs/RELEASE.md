# AoTT-8311-v2r4 development source candidate

Product: AoTT-8311
Version: v2
Revision: r4
Machine identity: AoTT-8311-v2r4
Display identity: AoTT-8311-v2 r4
Hardware profile: potron-prx126-aott-v1
Status: Offline-qualified development candidate; no hardware trial or commit

## Firmware lineage and qualification

The previously qualified firmware is AoTT-8311-v2r3. Its tested compatibility
scope is limited to the LL-XS1010 / PRX126-SFP-PON hardware profile and the
approved vendor kernel, bootcore, and PON/OMCI stack.

The v2r4 source has been built in a private offline workspace using the
verified v2r3 vendor components. The private image and archive passed
reproducible SquashFS assembly, pinned component checks, independent extraction,
source manifest verification, runtime profile readback, and partition capacity
checks. The PON Explorer controller also passed synthetic tests under the
MIPS Lua 5.1 interpreter from that offline image.

These results do not constitute a production hardware trial. **No public
firmware binary is provided, and v2r4 has not been flashed or committed.**

## Changes relative to v2r3

- Build read-only PON Managed Entity Explorer links using LuCI's canonical
  route builder rather than page-relative browser paths.
- Validate decimal class/instance identifiers before requesting attributes.
- Escape untrusted OMCI listing content and render returned attributes as
  plain text rather than executable markup.
- Prevent caching and browser content sniffing of authenticated OMCI views.
- Reject malformed or external-protocol-relative attribute URLs.
- Improve dark-mode text and mobile layout readability with synthetic
  Chromium browser tests, including a contrast threshold.
- Replace ambiguous interface placeholders with readable status messages.
- Retain the existing A/B rollback, credential persistence, and management
  routing safety requirements.

## Quality gates

    python3 tools/verify_release.py .
    python3 tools/check_disclosure.py .
    python3 -m unittest discover -s tests -v

The CI workflow separately enforces browser JavaScript syntax, Lua 5.1
regression fixtures, and screenshot-free headless Chromium interaction tests.
A later hardware trial still requires authorized flashing of an inactive
bank, verified off-device recovery backups, real PON and WAN acceptance,
and a separate explicit commit.

## Source privacy and redistribution

The public repository contains text source only. It excludes actual PON
identities, subscriber provisioning, management/WAN addresses, MACs, personal
details, passwords, SSH keys, copied rootfs/vendor images, full-bank backups,
and screenshots. Public release notes contain no private build artifact hash,
device-specific hardware identity, or live diagnostic dump.

Upstream copyright notices remain for legitimate attribution. The audited
source disclosure gate is not a substitute for manual code and history review.
