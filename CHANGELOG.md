# AoTT-8311 Changelog

## v3r1 (development, post-RC3 A-to-Z configuration work)

### Post-RC3 A-to-Z configuration development
- Expanded the canonical Configuration-page schema from **54 to 55 controls** by repairing and re-enabling `lct_vlan`; all 55 fields now belong to exactly one server-owned mutation route and **no field can silently fall through to generic environment persistence**.
- Added an explicit five-way A-to-Z routing contract for the 55 Configuration controls:
  - **22 live-activation controls** with native consumer/readback contracts, including language, hostname, timezone, NTP, HTTPS redirect, ping/reverse-ARP helpers, console/dying-gasp/RX_LOS behavior, Ethernet override, seven virtual-SFP EEPROM fields, and the three service-VLAN controls.
  - **6 lockout-sensitive management controls** (`lct_vlan`, `ipaddr`, `netmask`, `gateway`, `dns_server`, `lct_mac`) using a persistent guarded transaction with reconnect confirmation, exact runtime convergence verification, timeout rollback, and boot recovery.
  - **22 PON/OMCI controls** using a separate guarded transaction that snapshots environment/UCI/MIB state before mutation, applies fixed native consumers, verifies local readback, requires confirmation, and restores unconfirmed state at boot. Local write success is not treated as OLT acceptance.
  - **4 boot-only controls** (`bootdelay`, `uart_select`, `failsafe_delay`, `persist_root`) using a guarded one-boot trial with persistent pre-change state, watchdog timeout rollback, reboot-aware confirmation, and boot-command recovery.
  - **1 credential control** (`root_pwhash`) using a dedicated secret-safe live shadow transaction with exact redacted readback and restore-on-failure.
- Reworked ordinary configuration persistence into a rollback-capable transaction. Failed sequential persistence restores earlier attempted values in reverse order and verifies the durable restore before returning failure.
- Added independent runtime verification for kernel hostname, active zoneinfo target, live `ntpd` peer arguments, and a subsequent authenticated LuCI request for language.
- Expanded live activation to `https_redirect`, `pingd`, `ping_ip`, `reverse_arp`, `console_en`, `dying_gasp_en`, `rx_los`, `ethtool_speed`, all seven virtual-SFP fields, `fix_vlans`, `internet_vlan`, and `services_vlan`.
- Added fixed-path host runtime helpers for GPIO/ethtool behavior and host-visible virtual-SFP EEPROM verification. Dynamic shell execution is not used.
- Added full management-tuple planning, UCI/environment transactions, persistent recovery storage, Dropbear binding migration, exact active-interface/address/route/DNS/MAC/VLAN verification, and authenticated confirmation from the surviving management path.
- Added guarded PON/OMCI environment, UCI, MIB and auxiliary-runtime transactions with persistent recovery. Sensitive subscriber values remain private and public receipts are redacted.
- Added the **Access & servers** GUI for **22 guarded SSH/uHTTPd/LuCI/remote-HTTPS settings**. It provides validation, exact preview, private recovery snapshots, service reload/runtime verification, HTTPS-only guarded apply, reconnect guidance, timed confirmation, automatic rollback, and boot-time recovery.
- Added a source-derived routing/inventory contract so future GUI fields must be explicitly assigned to `live`, `management`, `pon`, `boot`, or `credential`; mixed high-risk routes are refused instead of being partially applied.
- Added runtime MIB profile introspection for every shipped `/etc/mibs/*.ini` profile. The Configuration selector now shows structure-derived labels and a live capability summary instead of treating the filename as opaque.
- MIB-driven prompts now expose physical UNI topology, T-CONT/queue/scheduler counts, IP Host ME 134 presence, VEIP presence, conditional records, profile-native identity defaults, and whether a single `pon_slot` override is structurally safe.
- Multi-UNI and VEIP-only profiles no longer accept a generic slot override. Profile switches that would carry an incompatible saved slot require an explicit reviewed clear; the controller, guarded worker, and MIB applicator all re-check that rule.
- IP-host identity fields are marked non-applicable/read-only when ME 134 is absent, while existing saved overrides are preserved unless explicitly changed.
- Integrated operator-owned TLS certificate import into the existing inactive-candidate and guarded activation path. PEM/DER leaf/key input, bounded issuer chains, SAN/validity/algorithm checks, exact vendor-uhttpd pair loading, browser confirmation and automatic rollback are source-qualified.
- Added an explicit default-off remote HTTPS firewall policy to Access & servers. Up to eight non-overlapping IPv4 /24-/32 source CIDRs generate only fixed WAN-to-management-HTTPS INPUT rules; SSH, forwarding, NAT, PON and OMCI are outside this feature.
- Completed C-017 as a generated source/browser gate covering all 14 AoTT menu pages, 24 POST write handlers and 4 mixed/multipart write handlers. The audit also fixed missing explicit action-level CSRF/session checks, a Support-page token submission defect, and corrupted Live Health copy.
- Current exact-tree regression: **1,350 source tests**, zero failures/errors, with environment-dependent tests skipped where their runtime is intentionally unavailable.
- Current real-browser regression: **154/154 Chromium/Playwright tests**, zero failures.
- Dedicated A-to-Z qualification against host plus extracted vendor-MIPS runtime passes for the new activation, management, PON, boot, credential, VLAN, runtime-helper and effective-readback paths.
- Release identity and public-source sanitization pass with **172 overlay files**, zero detected secrets, prohibited files, or manifest drift.
- Exact MIB-profile implementation checkpoint: local build-source commit `24535e5b6f4393a2a85a23510c9f59e7997356c1`; public `dev/v3` implementation commit `6d3032002f4d45b46d36130bfcc0ee8bcc5411df`; both resolve to tree `9c3da927c5e914d7284aadd34b2d58ef990d2a1d`.
- Two independent offline builds are byte-identical. Rootfs: **5,849,088 bytes**, **372,736 bytes** fixed-bank headroom, SHA-256 `4a7148e6beaf69b9b445b13950eb08f1f584bfbc5cced499d94c2a8b80d626a2`. Upgrade archive SHA-256: `742398c7c99ec3d07d18bc315d15bcd944666d61a5aa10bb81a8c6606f132af8`.
- Independent build-pair audit status: `PRIVATE_INDEPENDENT_RELEASE_PAIR_REPRODUCIBLE`; hardware-qualified remains false and the production device was not modified.
- Exact post-RC3 A-to-Z source checkpoint built offline: `023b8865a956b6ff13935e1c703bb7e414b0942e` / tree `098cd52047f476667244a2616dd827a2362b209a`.
- Two independent private builds are byte-identical. Rootfs: **5,840,896 bytes**, **380,928 bytes** fixed-bank headroom, SHA-256 `e5c15033e66ea72f65376040be57fb68e6f2a19f7248e020f1fc888ae1c04505`. Upgrade archive SHA-256: `a40504c7e76adcad0a97a00dee111a2e08f3aa604e679fb88875f4de6bc2489d`.
- Independent pair audit status: `PRIVATE_INDEPENDENT_RELEASE_PAIR_REPRODUCIBLE`; hardware-qualified remains false and the production device was not modified.
- This remains substantive `dev/v3` source development, **not a new RC**. The live ONU remains committed r9 A/A. No V3 firmware stage, live A-to-Z mutation, reboot trial, or commit was performed by this source-development batch.
- Hardware qualification remains separate from source completion: disruptive management, PON/OMCI, boot, host-link and provider-facing controls still require the appropriate recovery route, spare/test OLT, reboot, and live effect/revert evidence before being marked `FULLY_QUALIFIED`.

### RC3 first-login and hardware-stage readiness
- Current candidate: `release/v3r1-rc3` at `00c6d096a4051a20de80e0fcfe7dc39f257f56ef`.
- Added a first-authenticated-GUI-login password prompt when factory `root/root` is active, with explicit **Change password now** and **Keep root/root** choices. The acknowledgement is device-persistent, CSRF-protected, root-session-only, and does not turn the credential recommendation into a deployment restriction.
- Verified the exact first-login implementation in host Lua, extracted vendor-MIPS Lua/nixio, and real Chromium at desktop/mobile sizes in both light and dark themes.
- RC3 complete source regression: **1,224 tests**, zero failures or errors.
- RC3 deployment-sensitive vendor-MIPS regression: **41 tests**, zero failures.
- RC3 real Chromium/Playwright regression: **134/134 tests**, zero failures.
- Two independent private RC3 firmware builds are byte-identical. Rootfs SHA-256: `42825f13e32fb38d24c668befced9ef87823af1c156fcb46698a9fdd9a200bde`; upgrade archive SHA-256: `dcc2378edc21408517fd17302135e00716c89468cf40a29d05f1c40b808f31a8`.
- RC3 rootfs uses **5,779,456 bytes** of the fixed bank and retains **442,368 bytes** of flash headroom.
- Read-only hardware preflight passes on the unchanged r9 reference unit: A active/committed, B valid as inactive recovery, PON O5.1, 10 Gbps host Ethernet, HTTPS and pinned-key SSH healthy, fresh full-bank backups still matching live receipts, and factory `root/root` accepted.
- RC3 is technically stage-ready, but **no stage, trial, reboot, or commit authorization has been issued** and the live ONU remains unchanged.

### RC2 credential-policy correction
- Restored the public residential-device policy that `root/root` is the documented factory default and is allowed during development and deployment.
- Fresh V3 boots use `root/root` when no valid saved administrator credential exists; supported custom credentials still override the default and are preserved across upgrades.
- Removed RC1's unique-password staging restriction while retaining validation against blank, locked, malformed, or unsupported credential states.

### V3 foundation
- V3 accepts the documented factory `root/root` credential for development and deployment, restores supported saved credentials when present, and defaults fresh boots to `root/root` when no valid persisted root hash exists.
- Promoted the hardware-qualified v2r9 line to the V3 development identity while retaining r9 as the proven PRX126 release-candidate baseline.
- Added an authenticated V3 status page and JSON capability summary that distinguishes integrated, inactive, qualified and disabled features.
- Moved eleven already-tested bounded history/read-only handoff primitives into the firmware overlay for production integration.
- Added an opt-in local-history init service and authenticated administrator History UI/API. The service is disabled by default, has no procd respawn loop, samples into bounded RAM only, publishes through dual kernel-lock freshness gates, and enables no persistent history writer or anonymous endpoint.
- Added an authenticated Management preflight page/API that reads six native management source states without values, verifies /ptconf recovery-storage prerequisites, validates the actual UCI topology, and produces redacted VLAN transition counts. No management apply route or production native writer is enabled.
- Added root-only HTTPS private-key mode hardening, an HTTPS-only self-signed TLS candidate generator using the qualified vendor px5g path, and guarded candidate activation with persistent backup, a 180-second browser-confirmation window, timed rollback, and boot-time pending-transaction recovery. Operator-owned certificate import remains gated.
- Kept remote GUI management disabled by default and preserved the r9 guarded A/B recovery lifecycle.
- Updated V3 cache identities and retained the existing metrics credential digest domain for upgrade compatibility.
- Expanded release tests so shipped history primitives remain bounded and non-autostarting instead of relying on their absence from the firmware overlay.
- Earlier V3 integration checkpoint: 1,217 source tests passed before RC2/RC3 credential and first-login work. The current RC3 qualification counts are recorded above.

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
