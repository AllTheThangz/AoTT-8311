# AoTT-8311 v2r8 boot readiness: independent offline audit

Audit date: 2026-11-01. Status: **OFFLINE QUALIFIED, NOT HARDWARE TRIALED**.
No live ONU, management route, PON identity, firmware selector or flash
bank was modified in this audit. This report is source-only; private
firmware images, recovery backups and device-specific data are excluded.

## Scope and source

Public development: draft PR #11, based on the privately accepted v2r7
LL-XS1010 / PRX126-SFP-PON firmware. A separate **private** audit copy
was assigned canonical v2r8 release metadata and refreshed runtime
candidate pins. The public development branch retains historical v2r7
release labels until source and hardware qualification are signed off.

This audit checks a particular qualified device family. It is **not**
a universal flashability guarantee for other ONU chipsets or boards.

## Audit pass 1: boot and compatibility

- Private A/B r8 builds independently regenerated the release identity
  and reviewed runtime profile; both passed the source integrity rules.
- Vendor kernel, bootcore, kernel modules and PON firmware components
  are unchanged from the accepted v2r7 baseline.
- The immutable vendor boot, logger, firewall, uhttpd and UCI defaults
  remain untouched. The existing S11 sysctl service is retained with
  one optional, at-most-12-second monitoring restoration call after the
  original sysctl operations. The pre-existing S11sysctl and S12log
  startup links remain unchanged.
- **Important correction:** The prior draft attempted to register a new
  S11 startup link in UCI defaults. The source-only verifier prohibits
  symlinks, and relying on a dynamically registered link is unsafe
  across rootfs_data resets. The corrected source uses the already
  installed vendor startup link instead.
- The optional monitoring restore is skipped if no private persistent
  record exists. Failure does not reboot, change PON state, or block
  subsequent normal shell startup beyond the outer timeout.
- Exact rootfs file catalog comparison: **5 additions, 9 modifications,
  0 deletions**, all within reviewed overlay paths and refreshed runtime
  profile; zero unreviewed changes to the vendor baseline.

## Audit pass 2: build reproducibility and release format

- Two independently assembled **private** r8 rootfs images matched
  byte-for-byte.
- Aligned XZ SquashFS: **5,697,536 bytes**.
- Fixed bank capacity: **6,221,824 bytes**.
- Remaining rootfs headroom: **524,288 bytes (512 KiB)**.
- Kernel and bootcore bytes match previously accepted vendor hashes.
- Two private complete upgrade archives match byte-for-byte.
- The archive's standard five components, hardware target, ABI profile,
  release identity, size, SHA-256 records and independent unpacking
  pass the project's offline release builder and a separate archive
  qualifier.
- Every private output remains **UNTRIALED_OFFLINE_ONLY** with
  `hardware_qualified=false`. No private firmware binary was added
  to public GitHub.

## Audit pass 3: runtime and failure behavior

- Native Lua 5.1 parser and actual vendor MIPS Lua/QEMU fixtures.
- Existing vendor LuCI UCI and uhttpd Lua handler compatibility.
- Actual vendor MIPS UCI CLI in a private chroot and mount namespace,
  including committed-file readback, repeated no-op restore and
  partial-write rollback. No host UCI staging pollution.
- Durable monitoring record read/write, file ownership/permissions,
  symlink and malformed-document denial, fsync and atomic rename.
- Credential token issuance, revocation, failed active-UCI commit,
  stale-state protection, HTTPS-only collector authorization,
  exact collector IP and management destination checks.
- Monitoring metrics time/output bounds, safe unavailable values,
  vendor syslog UDP/TCP service-command contract and external
  standard-library-only Prometheus conversion.
- Source manifest, public disclosure checks, and the full local
  regression suite. GitHub source and real browser checks are required
  on the final draft commit; private MIPS suites are not bundled into
  public CI.

## Remaining unknowns

These are explicit release blockers, not failures demonstrated by the
offline tests:

1. Actual cold boot on a recoverable PRX126 with mounted UBIFS,
   `rootfs_data` reset behavior, service startup and watchdog timings.
2. PON O5.1, OMCI/GEM/VLAN service continuity, negotiated Ethernet,
   upstream WAN, HTTPS/SSH management and full-bank readback.
3. Network-layer firewall and management-interface ingress filtering
   over both IPv4 and IPv6. Vendor uhttpd uses wildcard listeners.
4. Real syslog collector receipt for UDP and TCP, including unreachable
   receivers, reboot and A/B transitions.
5. Optical and GEM polling under concurrency, CPU/RAM usage and
   long-duration operation. External caching reduces demand but does
   not prove hardware performance.
6. All four recovery stages: independently verified full-bank backups,
   inactive-bank stage, separately approved one-shot trial and only
   then a separately approved permanent commit.

The latest privately verified pretrial state is committed **v2r7 in bank B**
with valid **v2r6 in bank A**. Staging r8 into inactive bank A would
overwrite that bank's v2r6 image, while retained committed B/v2r7
must remain independently verified as the fallback. Fresh on-device
state and full-bank backups must be checked before any such action.

## Boot prediction interpretation

The unchanged vendor boot and PON stack, accepted prior r7 hardware
operation, reproducible private r8 images, spare bank capacity and
bounded optional startup integration are strong **positive indicators**
for basic boot success. They do not provide a measured boot success rate.

The prediction for the eventual r8 one-shot trial must be explicitly
conditional on fresh hardware baseline evidence, current bank selector,
verified backups, independently accepted inactive-bank staging and
a fully reviewed release profile. It cannot replace the hardware test.
Device-independent examples or previous success on one unit do not
prove wider compatibility.

**Disposition:** promising for a controlled one-shot trial after the
remaining safety gates, **not yet an authorized or production-ready boot**.
