# AoTT-8311 Changelog

## v3r1 (development, source-only, not yet deployed)

### V3 foundation
- V3 accepts the documented factory `root/root` credential for development and deployment, restores supported saved credentials when present, and defaults fresh boots to `root/root` when no valid persisted root hash exists.
- Added a first-authenticated-GUI-login password prompt when factory `root/root` is active, with explicit **Change password now** and **Keep root/root** choices; acknowledgement is device-persistent and does not turn the credential recommendation into a deployment restriction.
- Promoted the hardware-qualified v2r9 line to the V3 development identity while retaining r9 as the proven PRX126 release-candidate baseline.
- Added an authenticated V3 status page and JSON capability summary that distinguishes integrated, inactive, qualified and disabled features.
- Moved eleven already-tested bounded history/read-only handoff primitives into the firmware overlay for production integration.
- Added an opt-in local-history init service and authenticated administrator History UI/API. The service is disabled by default, has no procd respawn loop, samples into bounded RAM only, publishes through dual kernel-lock freshness gates, and enables no persistent history writer or anonymous endpoint.
- Added an authenticated Management preflight page/API that reads six native management source states without values, verifies /ptconf recovery-storage prerequisites, validates the actual UCI topology, and produces redacted VLAN transition counts. No management apply route or production native writer is enabled.
- Added root-only HTTPS private-key mode hardening, an HTTPS-only self-signed TLS candidate generator using the qualified vendor px5g path, and guarded candidate activation with persistent backup, a 180-second browser-confirmation window, timed rollback, and boot-time pending-transaction recovery. Operator-owned certificate import remains gated.
- Kept remote GUI management disabled by default and preserved the r9 guarded A/B recovery lifecycle.
- Updated V3 cache identities and retained the existing metrics credential digest domain for upgrade compatibility.
- Expanded release tests so shipped history primitives remain bounded and non-autostarting instead of relying on their absence from the firmware overlay.
- Full host/source regression after local-history, management-preflight, credential-preservation, and guarded TLS-activation integration: 1,217 tests passed with environment-dependent browser/proprietary-runtime tests skipped; no failures or errors. The history, management-preflight, credential, and TLS contracts also pass under the extracted PRX126 vendor MIPS Lua/nixio runtime.

See [V3 deployment foundation](docs/V3-DEPLOYMENT-FOUNDATION.md).


## v2r9 (privately hardware-qualified and committed on one PRX126)

### Integrated runtime and configuration readback
- Combined the security-enhanced r8 monitoring/runtime source with seven Configuration readback groups covering all 54 existing GUI fields.
- Preserved protected collector credentials, durable monitoring restore, remote syslog, TLS-key permission visibility and guarded A/B controls.
- Added explicit runtime integrity requirements for 15 readback files while preserving inherited monitoring and S11/S12 boot-link requirements.
- Assigned unique r9 machine/display identity and refreshed relevant browser cache labels without changing the compatible monitoring-token digest domain.
- Retained unfinished history, certificate, firewall and native VLAN transaction prototypes outside the 89-file firmware overlay.

### Build and hardware acceptance
- Final combined regression passed **1,304/1,304** tests with zero failures, errors or skips, including 131 real Chromium cases.
- Two independent private builds produced identical rootfs images and upgrade archives; the final rootfs retained 476 KiB of bank headroom.
- Fresh full-volume recovery backups were verified before changing banks.
- Enhanced r8 was committed in bank B as recovery, then exact r9 was staged into A, one-shot trial booted, independently verified, and separately permanently committed.
- Final verified state is **A active / A committed / no pending activation / not running a trial**, with PON O5.1, 10 Gbps host Ethernet, recovery access and both complete bank images valid.
- The permanent commit performed no reboot and no firmware-image write; enhanced r8 remains intact in bank B.
- Hardware qualification is limited to the tested LL-XS1010 / PRX126 device and does not complete per-field setter/persistence qualification, long-duration soak, or other-board support.

See [r9 hardware acceptance](docs/V2R9-HARDWARE-ACCEPTANCE.md) and [r9 release scope](docs/V2R9-INTEGRATED-RELEASE.md).
The immutable `offline-candidate` value in `release.json` remains the historical build-stage marker and is not rewritten by later hardware qualification.

The older release entries below retain their historical acceptance state.

## v2r7 (privately hardware-qualified and committed on one PRX126)

### Graph contrast and web UI
- Improved inherited Overview chart grid, label and RX/TX series
  readability in light/dark themes across equivalent inline styles.
- Added real Chromium contrast, theme-switch and unrelated-element tests.
- Updated revision-specific theme and firmware-page cache identifiers.
- Retained v2r6 native bank guards, vendor kernel, bootcore, PON/OMCI
  compatibility, SSH/HTTPS and cryptographic ABI.

### Offline qualification and hardware acceptance
- 300 source regression tests, including 46 real Chromium cases, passed.
- Matching independent private image/archive builds passed integrity
  verification and retained 520 KiB rootfs bank headroom.
- Separately approved full-bank backups, inactive-bank staging,
  one-shot trial and permanent commit were independently verified.
- v2r7 is committed on firmware bank B. Valid v2r6 remains in bank A.
  Other ONU boards and long-duration stability are not qualified.

See docs/V2R7-HARDWARE-ACCEPTANCE.md for the current acceptance.
Immutable offline-candidate flags in the original build records describe
their earlier build stage, not the later successful hardware trial.
This public package contains only sanitized source, not firmware images.


## v2r6 (privately hardware-qualified and committed on one PRX126)

### Hardware qualification and release status
- Independently built and verified identical private rootfs images and
  firmware archives, then pinned the release candidate and policy bridge.
- Captured and independently verified both full-capacity UBI bank
  backups before installation, retaining earlier v2r4 and v2r5
  firmware off-device.
- Approved a no-reboot, stage-only v2r6 installation into bank A, then
  separately approved a one-shot trial and a guarded permanent commit.
- Confirmed v2r6 running and committed in A, valid v2r5 alternative
  in B, PON O5.1, 10G host Ethernet, HTTPS, WAN and both bank contents.
- Private acceptance evidence is retained separately from the source
  distribution. Other hardware and long-term stress remain unqualified.

### Firmware management
- Added a live preview of the next boot bank and saved recovery bank.
- Distinguished committed operation, scheduled one-shot boot, and running
  uncommitted trials without inventing automatic rollback timers.
- Locked firmware actions on inconsistent, incomplete, or stale state.
- Added a 60-second maximum age for browser bank-status authorization.
- Added a fresh state read and confirmation immediately before an action.
- Added a server-bound SHA-256 fingerprint of live bank selectors,
  firmware receipts, per-boot kernel UUID and a five-minute validity
  window, checked under the native firmware/environment locks.
- Made queued bank operations expire at the next five-minute boundary
  and invalidate on any reboot, even if the same bank remains selected.
- Required validated state fingerprints on authenticated bank-operation
  requests and inside the background job worker.
- Added an inactive-bank overwrite preview and explicit dual-bank
  off-device backup warning before firmware installation.
- Made web-upload installations carry expected active/target bank values
  and the same short-lived, reboot-aware bank-state fingerprint used by
  guarded bank operations.
- Moved fingerprint generation into the shared native upgrade library,
  eliminating separate implementations in the bank-control and installer
  paths. The installer verifies the fingerprint under firmware locks,
  then checks it again before marking the inactive bank incomplete.
- The native installer checks the reviewed active/target pair before
  any receipt changes or flash writes.
- Kept archive validation and upload discard available while installation
  is locked by an unresolved or unverified bank state.
- Corrected firmware-page asset cache versions for v2r6.

### Build safety and verification
- Added independent private-release pair verification of source manifests,
  archive members, component hashes, modes, timestamps and volume limits.
- Rejected duplicate and hardlinked files presented as independent builds.
- Expanded browser, source and regression coverage, including reference
  checks for boot identity, expiry boundaries and stale queued requests.
- Verified BusyBox shell and Lua source syntax using the target MIPS32r2
  interpreters in an isolated QEMU user-mode environment.
- Added candidate runtime-integrity pins for the guarded bank-control
  utility and web job worker.
- Kept the existing vendor kernel, bootcore, OMCI, PON stack, management
  authentication and cryptographic runtime unchanged.
- Preserved substantial flash headroom while keeping the original
  fixed UBI volume sizes and vendor ABI compatibility.

Status: Privately committed on one qualified PRX126 device, bank A.
Public distribution is source-only. The frozen build metadata and
private archive names still describe their earlier offline state.
No public binary firmware publication is authorized.

## v2r5 (hardware trial passed, committed)

- Backported and reproducibly rebuilt the CGI helper request-validation
  protections, including malformed POST-field handling.
- Retained hardened web server, compatible RPC backend, OMCI stack and
  required cryptography.
- Independently verified a one-shot hardware trial, PON O5.1, 10G
  Ethernet, management HTTPS, WAN, root recovery and both firmware banks.
- Separately authorized and verified the permanent bank-B commit.
- Preserved v2r4 in bank A as the valid on-device fallback.

## v2r4 (verified recovery firmware)

- Improved PON Managed Entity Explorer behavior and dark-mode contrast.
- Strengthened firmware bank controls, boot contract verification and
  recovery paths.
- Refined LuCI pages, diagnostic display and bank validation.
- Retained validated full-bank recovery behavior.
