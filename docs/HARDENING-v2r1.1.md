# AoTT-8311 v2r1.1: Security and management reliability

**Status:** Source changes and offline regression tests only. Not a firmware image.
**Production behavior:** The v2r1 firmware and committed bank are unchanged.

## Observed v2r1 problems

1. Management routing: With an unset gateway, the old helper substituted the
   ONU management address, which generated a self-referential next hop. The
   running device previously required a guarded management route repair.
2. Root credentials: The original sysinit attempted to apply a saved
   password hash but did not verify the live /etc/shadow field afterward.
   Saved-versus-running credential mismatches could therefore go unnoticed.
   Never restore an unknown hash or create a shared password by default.
3. Exposure: Earlier firmware defaults enable password-based SSH login and
   wildcard management listeners. Operators should verify key recovery,
   restrict reachability and explicitly configure device-unique credentials.
4. Component provenance: The vendor-derived uhttpd and other services
   require a binary-specific audit against recent OpenWrt advisories.
   No vulnerability is attributed to a specific binary solely from a
   package family name.

## Implemented in this source branch

- An absent gateway and the historic self-address sentinel now both
  represent **no default route**.
- Both tagged and untagged management UCI defaults delete a stale gateway
  when no valid next hop is configured.
- The configuration UI displays legacy self-gateway settings as unset.
  A configuration save clears the legacy sentinel, preventing the old
  address becoming a route after a management IP change.
- Management IP and netmask validity is checked independently of gateway
  presence. A configured gateway must be a different, valid host in the
  management subnet.
- The root startup code validates its post-write state without emitting
  password hashes. It logs explicit errors on write/readback failure and
  warns when no valid saved root credential exists. No shared password is
  generated, and the current device is not changed.
- Offline regression tests cover valid, blank, legacy and invalid routes;
  credential success, readback mismatch, write failure, and missing hash.
- CI now runs Lua 5.1 syntax and behavioral tests in addition to Python,
  source security scanning and shell syntax checks.
- Overview and realtime-graph dark/light contrast has been corrected for
  network cards, progress bar labels, axes, grid lines, and RX/TX traces.
  Theme-specific text and background colors are regression-tested against
  WCAG AA 4.5:1 text contrast and 3:1 graphical-element contrast.
- Browser CSS URLs now include a new version marker to invalidate stale
  stylesheets after an upgrade.
- A read-only offline upgrade-archive qualification tool checks five-member
  tar layout, declared component hashes, SquashFS v4/XZ structure, zero
  padding, configured UBI capacity and the reserved size budget.
- The vendor web-service binary inventory and pending security patch-level
  review are documented in [SECURITY-WEBSTACK-AUDIT.md](SECURITY-WEBSTACK-AUDIT.md).

## Security and upgrade boundaries

The changes **do not**:

- Flash, reboot, commit, reconfigure, or restart the production ONU.
- Restore an unknown saved root hash to the live account.
- Disable SSH password access without a separately tested recovery path.
- Modify provider PON identity, VLANs, GEMs, T-CONTs, or the proprietary
  OMCI/driver stack.
- Assert that vendor uhttpd vulnerabilities have been patched.
- Create a distributable binary or sign a firmware release.

If a saved-versus-running password mismatch occurs, remediation requires
a known device-unique password, verified SSH-key recovery and confirmed
behavior across reboot. Do not transplant a hash from another device.
Compressed rootfs size and flash-layout checks are prerequisites to any
release build, independent of local filesystem free space.

## Qualification gate before any v2r1.1 image

1. Validate the offline source scanner, manifest, unit and Lua tests.
2. Review third-party redistribution rights and obtain a clean, compatible
   factory firmware base with the correct kernel and PON/OMCI ABI.
3. Check source and generated rootfs size against each target UBI volume.
   First, verify the offline image before any installation attempt:

       python3 tools/qualify_offline_image.py --archive /path/to/upgrade.tar --volume-bytes 6221824 --min-headroom 65536

   The volume capacity above is the known LL-XS1010 layout example, not a
   substitute for measuring the actual target. The historical v2r1 image
   leaves 40,960 bytes in that volume and therefore needs more optimization
   to meet a 65,536-byte preferred headroom target.
4. Compare old/new management-gateway behavior in isolated network fixtures
   and confirm reconnection and rollback after an intentional address change.
5. Test root password setup and persistence with a **known** device-specific
   credential, without recording it in the build or public logs.
6. Verify both full-volume backups, bank receipts and flash readback.
7. Trial boot with explicit authorization; check O5.1, 10G link, management
   access, WAN throughput, optical counters, NAND errors and fallback.
8. Commit only after a separate approval and independently verified state.

## References

- Upstream 8311 community baseline: https://github.com/djGrrr/8311-was-110-firmware-builder
- OpenWrt 25.12.6 security release notes:
  https://openwrt.org/releases/25.12/notes-25.12.6
- Source security policy: ../SECURITY.md
