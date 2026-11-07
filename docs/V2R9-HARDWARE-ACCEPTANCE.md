# AoTT-8311 v2r9 hardware acceptance

Status: **Privately hardware-qualified, running and committed** on one
Potron LL-XS1010 / PRX126-SFP-PON device as of November 7, 2026.

The public repository remains a secret-sanitized source distribution.
No subscriber provisioning, credentials, private keys, full flash backups,
or ready-to-flash firmware binary are published by this acceptance.

## Qualified source and image identity

The tested firmware was built from the source tree shared by the private
tested commit and public r9 candidate:

- Tested private source commit: `ed227423ba25e8768f7994c5f5490693f706ee50`
- Public source commit with the identical Git tree: `6865d9bf347fc3ac96329c6e1bd51374cc4441e9`
- Git tree: `6e7723194bc22ef1c414114080aeab7968259e75`
- Firmware identity: `AoTT-8311-v2r9`
- Hardware profile: `potron-prx126-aott-v1`
- r9 rootfs SHA-256: `e97b77d77cd4bceb50cc99d4bec4bba9b504077ca55ee7f66aecd6b5facfe987`
- Kernel SHA-256: `d66b24cf873cc1071a3aa2d155bf677f503f10d221513e469083f8a591f6b96c`
- Bootcore SHA-256: `e99e25332bdcb3c9b0447abad1be9b1e54511b6bda99f2b51ae2499db5b905a4`

The source-level combined regression passed **1,304 of 1,304** tests with
zero failures, errors, or skips. That total included 335 configuration
tests, 969 integration tests, 131 real Chromium cases, and seven genuine
vendor-MIPS effective-readback cases. Two independent private builds
produced byte-identical rootfs images and upgrade archives.

## Hardware transition and recovery preservation

The hardware transition used separate guarded stages rather than treating
a successful write as authorization to boot or commit:

1. Fresh private off-device backups of all six UBI volumes were verified
   against independent second reads.
2. The already-running enhanced-r8 bank B was committed as a known recovery
   point without rebooting.
3. The exact qualified r9 image was staged into inactive bank A and both
   banks passed native integrity checks.
4. Bank A was selected for one trial boot and exactly one reboot was
   requested. No automatic retry or second reboot was allowed.
5. The r9 boot was independently verified before any permanent commit.
6. A later, separately authorized guarded commit made the running r9 bank A
   the normal committed bank. That final commit required no reboot.

The enhanced-r8 image remains complete and valid in bank B. Committing r9
does not overwrite that recovery image.

## Final verified device state

After the permanent r9 commit:

| Property | Verified state |
| --- | --- |
| Running firmware | `AoTT-8311-v2r9` |
| Active bank | A |
| Committed bank | A |
| Pending one-shot boot | none |
| Running trial | false |
| PON state | O5.1 |
| Host Ethernet | 10,000 Mbps |
| Recovery SSH | present |
| Saved root recovery check | matched |
| Bank A native integrity | passed |
| Bank B native integrity | passed |

The final commit left the running boot ID unchanged and performed zero
firmware-image writes. The complete r9 immutable runtime check covered
41 regular files and three symlinks after boot. Management HTTPS was
reachable and the operator subsequently confirmed browser access.

## What this acceptance does and does not prove

This acceptance proves that this exact r9 image boots, preserves the
qualified A/B recovery contract, registers PON O5.1, maintains the 10 Gbps
host link, preserves management/recovery access, passes the selected
runtime integrity checks, and can be permanently committed on the tested
PRX126 device.

It does **not** claim:

- qualification on other ONU boards, SoCs, OLTs, or service profiles;
- long-duration thermal, traffic, or power-interruption soak acceptance;
- that every one of the 54 configuration fields has a hardware-qualified
  native setter, persistence path, and independently observed effect;
- completion of the source-only history collector, certificate-management,
  remote-firewall, configuration-transaction, or cross-stick work;
- browser trust of the current TLS certificate or exhaustive authenticated
  testing of every GUI route.

Those remain roadmap work and must retain their own evidence boundaries.

## Build-time metadata remains historical

The r9 `release.json` value `status: offline-candidate` is an immutable
build/source-stage marker used by the release tooling. It documents the
state when the source candidate was assembled and must not be silently
rewritten to imply that the later hardware trial had already occurred.

This acceptance record is the authoritative public-safe statement of the
later hardware qualification and permanent commit. The same convention is
used for earlier hardware-qualified AoTT releases.
