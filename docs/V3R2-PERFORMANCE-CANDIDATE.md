# AoTT-8311 V3r2 performance candidate

Status: SOURCE CANDIDATE, NOT STAGED OR FLASHED.

## Why a new revision

The installed firmware identifies as AoTT-8311-v3r1. The performance
improvements merged from PR #56 must not be delivered with the same
firmware label because identical version strings conceal different
rootfs and archive contents. V3r2 uses the existing canonical release
identity generator to update firmware version, SSH banner, Lua
version, UI display and web-asset cache tokens.

## Changes from V3r1

- Preserve the verified PRX126 vendor hardware forwarding architecture,
  PON/OMCI service mapping, current 10 Gbps Ethernet configuration and
  MIPS/kernel/bootcore ABI.
- Reduce Live Health GEM subprocess diagnostics from every normal refresh
  to a five-minute cadence, retaining manual full refresh. Optical and
  Ethernet snapshots continue at the configured interval.
- Bound PON status calls; skip secondary GEM probes on failed status.
- Add private host-side passive throughput/CPU/thermal sample tooling.
- Include source-only watchdog admission and disconnected-network
  simulation tests, without changing the established A/B bank contract.
- No administrator password, temporary password, VLAN, MAC, PON identity,
  DMA, CPU frequency, firewall, boot selector or online firmware is
  changed by this revision preparation.

## Acceptance

- All Python source tests: 1,374 executed, no failures (407 skipped).
- Release identity, manifest integrity and disclosure checks passed.
- Dual independent offline SquashFS and archive reproducibility must be
  generated from the exact published V3r2 commit before staging.
- Active/committed bank and both image receipts must be re-read before
  any new stage-only authorization.
- Bank A currently contains the accepted alternative r9 recovery image.
  A stage targeting bank A would overwrite that image. Capture and
  verify a current full bank-A backup and preserve committed V3r1 in
  bank B, with a separately approved stage operation.
- The next stage operation, trial boot and permanent commit are distinct
  actions. There is no implicit firmware write, reboot or commit.
