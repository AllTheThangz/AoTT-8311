# AoTT-8311 v2r7 private offline candidate (historical build record)

> This document preserves the untried build's original safety contract.
> A later, separately approved hardware trial and permanent commit
> succeeded. See [v2r7 hardware acceptance](V2R7-HARDWARE-ACCEPTANCE.md)
> for the current status. Frozen build flags below remain historical
> and never authorize an unreviewed firmware installation.

Product: AoTT-8311
Version: v2
Revision: r7
Release identity: AoTT-8311-v2r7
Status: Source-only private offline candidate. NOT installed, trialed or committed.

## Qualified production baseline

The single privately hardware-qualified PRX126-SFP-PON ONU remains on
AoTT-8311 v2r6, active and committed in bank A. The verified v2r5
alternative remains intact in bank B. The original v2r4 and v2r5
full-capacity flash backups are retained off-device and privately.
Nothing about v2r7 authorizes replacing those recovery images.

## Change from v2r6

- Hardens inherited LuCI realtime graph styling in the overview.
- Matches graph presentation regardless of ordinary inline CSS
  whitespace or the order and format of known height/background fields.
- Restores readable SVG labels, grid strokes and separate RX/TX series
  colors under dark and light themes.
- Adds isolated Chromium tests for several equivalent inherited graph
  style representations, color contrast and theme switching.
- Refreshes theme asset cache identifiers and firmware-page version
  identifiers to the new candidate revision.
- Preserves the existing state-guarded bank management, PON/OMCI stack,
  remote access, kernel, bootcore, vendor crypto and compatibility
  profile. No new privileged device feature or boot state is introduced.

## Acceptance criteria

1. Source manifest and release identity must state v2r7 consistently.
2. Offline rootfs must match every reviewed overlay byte and candidate
   runtime-integrity pin while preserving all common ABI records.
3. The native MIPS32r2 BusyBox and Lua inputs must still parse.
4. Real isolated Chromium and full regression tests must pass with
   no missing required browser dependencies.
5. Independently built SquashFS images and five-member private archives
   must match, including checksums, metadata and size limits.
6. A fresh source disclosure scan must detect no subscriber identifiers
   or secrets. Firmware binaries remain outside public source.
7. Full new off-device backups, staging policy review and separate
   hardware approvals would be required before writing bank B.

## Restrictions

The candidate private archive must retain historical build-time
`UNTRIALED_OFFLINE_ONLY` and `safe_for_live_install=false` status.
Those flags are a release safety gate, not an instruction to flash.
No v2r7 deployment is approved. The v2r6 production commit remains
untouched during offline engineering.

A future installation would overwrite the valid v2r5 on-device
alternative in bank B. This is a consequential recovery change and
requires fresh complete backups, a separately approved stage-only
operation, an independently checked one-shot trial, and a distinct
commit approval after successful hardware validation.

Private image creation does not authorize distributing proprietary
vendor firmware, publishing subscriber details or expanding supported
hardware beyond the one qualified PRX126 board.
