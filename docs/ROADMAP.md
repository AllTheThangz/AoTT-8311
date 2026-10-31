# AoTT-8311 roadmap after v2r3

The privately hardware-qualified v2r3 release is the stable reference for
LL-XS1010 / PRX126-SFP-PON development. The GitHub repository distributes
sanitized source only, not subscriber-specific firmware images.

## v2r4: Interface, diagnostics and resilience

1. Perform a page-by-page LuCI audit, including default dark mode, high
   contrast, keyboard accessibility, responsive layout, navigation,
   footer and firmware view labels.
2. Finish PON Managed Entity Explorer functionality. Treat OMCI-derived
   values as untrusted data and display errors clearly without exposing
   registration credentials.
3. Improve optical telemetry, PON/GEM statistics, Ethernet errors, and
   resource health. Use bounded polling and authenticated read-only APIs.
4. Add regression tests for source-only, rendering, configuration persistence,
   and A/B state transitions. Preserve the known-good kernel/bootcore and
   avoid untested boot-environment changes.
5. Ensure no public documentation, code, CI logs, screenshots, or release
   assets contain actual device/network or personal identifiers.

Acceptance: complete static tests, privacy gates, source manifest checks,
MIPS/Lua compatibility tests, protected off-device backups, trial boot,
PON/management/WAN checks, and separate commit approval.

## v2r5: Runtime size and security

- Audit reachable runtime dependencies before removing packages.
- Remove only provably unused MIB templates, assets, documentation, and
  duplicate resources. Keep validated recovery and optical dependencies.
- Examine TLS/cryptographic libraries and server-side auth without disabling
  required security features to save space.
- Measure flash and RAM utilization without falsely promising access to
  reserved storage or additional CPU cores.
- Keep externally maintained help and detailed documentation in GitHub
  rather than in the deployed rootfs.

Acceptance: byte-level source/runtime profile checks and full live regression.

## v2r6: Reproducibility and source provenance

- Produce deterministic source overlays and independently check archive
  entries, manifests, file modes, and firmware-partition boundaries.
- Add signed source-release attestations and provenance verification where
  publisher credentials are available.
- Separate public source from any private, authorized vendor base.
- Harden release automation against accidentally publishing executable
  firmware binaries, device captures, or personalized metadata.

## v3: Isolated hardware and kernel research

- Investigate vendor SMP initialization, offline secondary CPU cores,
  kernel/device-tree options, and the PON 1PPS pin-selection conflict.
- Qualify hardware variants individually with independently recoverable
  test equipment and ISP authorization.
- Keep kernel and bootloader experiments away from production firmware
  until their safety and fallback behavior have been demonstrated.

## Permanent design constraints

- Do not publish subscriber provisioning, device identity, credentials,
  specific site addresses, private infrastructure, screenshots, or captures.
- Do not weaken management authentication or automatic bank recovery.
- Do not infer throughput from Ethernet link rate.
- Avoid modifications to a working PON/OMCI stack without explicit tests.
- Every production commit or disruptive change requires a separate
  authorized action and independent confirmation.
