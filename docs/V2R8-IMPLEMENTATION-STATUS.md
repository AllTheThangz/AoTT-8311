# v2r8 implementation status: first offline candidate

Status: **development source only, not merged, not a verified flashable release**.

The base is the committed v2r7 source for the qualified PRX126-SFP-PON hardware family. No production ONU, flash bank, boot selector, provisioned PON identity, or private monitoring system was changed to implement this candidate. All public examples use placeholders rather than addresses from a real deployment.

## Implemented in this development branch

- A lightweight Lua module uses existing UCI and the vendor's OpenWrt logging service. A read-only inspection of the qualified vendor image verified that `/etc/init.d/log` supports `log_remote`, `log_ip`, `log_port`, and `log_proto` with **UDP and TCP** transport options.
- The authenticated Monitoring & Telemetry page configures remote syslog, an exact allowed IPv4 collector address and optional metrics. The administrator can generate, rotate or revoke a separate 256-bit random read-only token. Only a domain-separated SHA-256 digest is persisted. A new token is shown once over HTTPS.
- Form submission requires LuCI session/CSRF validation, rejects unknown fields and malformed addresses/ports, checks a saved-configuration revision, locks concurrent AoTT monitoring writes, applies a single UCI system section, and reloads only the logger. A failed reload attempts to restore and verify the previous configuration.
- A bounded, locally generated test log message returns a correlation marker. It cannot confirm that a UDP or TCP collector received the message.
- The inherited anonymous metrics service is replaced with an administrator-authenticated metrics view and an external read-only metrics route. The external route requires HTTPS, the exact allowed source IP, a socket destination matching the configured management address, and the X-AoTT-Metrics-Token header. Forwarded/proxy identity headers are ignored.
- The existing Live Health page remains authenticated and provides additional Ethernet and GEM diagnostics. No database, Python runtime, exporter service or flash-based historical log storage is installed.
- The external JSON metrics path now bounds the inherited PON registration probe using the already-installed BusyBox timeout and a 1 KiB output limit. A timeout, overflow or failed read yields an unavailable PLOAM value rather than a false zero; interactive PON status remains unchanged. A target-MIPS fixture checks failure modes.
- The current vendor remote-log service has **no supported severity filtering knob**. Do not expose a nonfunctional severity setting; collectors may apply their own filtering.

## Validation performed

- Static Lua 5.1 parser checks for the module and LuCI controller.
- Isolated source-level Lua tests using mocked UCI, logging processes and locks. The tests cover invalid configuration, stale revision, successful save, test emission and failed-logging-service rollback.
- The same Lua fixture passed in target MIPS Lua under QEMU. Security-negative tests exercise wrong or missing tokens, non-HTTPS requests, mismatched source and destination IPs, spoofed forwarded headers, stale credential requests, rotation and revocation.
- Full source manifest and privacy/disclosure gates passed after adding the candidate files.
- A **size-only** private SquashFS measurement using XZ and 1 MiB blocks is **5,701,632 bytes** against v2r7 **5,689,344 bytes**, a delta of **12 KiB**. Remaining fixed-bank capacity is **520,192 bytes (508 KiB)**. This is not a qualified flashable image.
- Python regression tests and actual browser tests must be rerun on the final candidate, including CI with the Chromium requirements enforced.

**Important:** this is not firmware qualification. The private size-only filesystem still carries the v2r7 runtime integrity profile. Its hashes are not updated for new files, it is not eligible for an upgrade archive, and it must not be installed onto a device.

The draft monitoring configuration and credential transitions write the durable desired state before modifying live UCI settings. A failed live apply can leave pending durable settings that **may activate at the next boot**. The interface reports this explicitly and requires review rather than claiming that a failed apply fully cancels the operator's request. Token revocation remains fail closed while the r8 route is active.

## Persistence and vendor-runtime qualification findings

The vendor source explicitly documents that stock boot can delete rootfs_data
while the separate ptconf volume survives. The r8 draft now
restores the reviewed settings from a protected persistent record during
boot. Real hardware persistence and recovery remain unqualified.

- The extracted vendor LuCI UCI model passed synthetic configuration,
  token rotation/revocation and default-value tests under host Lua 5.1 and
  the real vendor MIPS Lua interpreter under QEMU.
- The exact vendor uhttpd Lua request handler passed synthetic TLS, socket
  address and custom HTTP-header mapping checks under both interpreters.
- The host-only atomic private record prototype passed six negative and
  round-trip tests, including symlinks, unsafe permissions, duplicate JSON
  keys, malformed addresses and invalid token states.
- A disposable vendor-runtime lab parsed the proposed record with target
  MIPS jsonfilter and round-tripped settings through the actual target
  MIPS UCI CLI using a fresh temporary configuration.
- The source candidate now includes a root-only, atomic JSON record store on the persistent ptconf UBIFS volume, an optional bounded restore call in the vendor's already-registered S11 sysctl service, before the S12 logger. The original UCI defaults are preserved unchanged. This avoids relying on a first-boot-created rc.d symlink that might disappear during rootfs_data reset. The target-MIPS nixio/jsonc store parser passed offline tests for symlinks, permissions, malformed mounts, canonical JSON and readback.
  persistent-write integration has been added to the firmware.

See [durable monitoring design](V2R8-PERSISTENCE-DESIGN.md).

### Interrupted-revocation and vendor CLI hardening

A security audit found that an ordinary settings save could copy an old live
credential back into durable storage after a prior revocation succeeded
durably but its live UCI commit failed. This loophole is closed: **normal
saves and token rotation now require durable/live consistency**, while
revocation remains available during a mismatch.

Boot restoration also rejects unrelated pending UCI edits and reverts its
own staged changes when an allowlisted set or commit operation fails.
An isolated harness drives the exact boot-restore module against the real
vendor MIPS UCI CLI using only disposable configuration directories.
It covers successful restore, idempotence, unrelated settings, missing
records, and injected set/commit failures with staged-state cleanup.

The expanded local suite now passes **301 tests** (four browser-dependent skips), including generic external collector, vendor syslog transport and management ACL contracts. These are not power-loss, real UBIFS, or A/B hardware acceptance tests.

### Fully isolated vendor UCI commit tests

The first private vendor CLI harness used a custom staging search path and
incorrectly counted staged values as committed. The vendor UCI command also
needs /proc/self/fd during commit, which was absent from that first chroot.

The corrected test suite clones the extracted vendor rootfs into a private
scratch chroot, binds /proc only inside a temporary mount namespace and
uses the vendor default UCI staging path **inside the chroot**. No host
staging path or running device configuration is changed.

Five end-to-end tests now confirm physical configuration-file readback,
repeated no-op restore, unrelated pending settings rejection, failed
middle-option revert and failed commit revert. An incidental synthetic
staging file from the earlier experiment was preserved off-path in a
private local test backup, not deleted or published.

This is still a disposable filesystem integration test, not proof that
the r8 hook survives actual UBIFS power loss or A/B transitions.

### Vendor syslog, collector endpoints and operator examples

- Source-mocked procd tests run the extracted vendor logger start callback
  and confirm the exact logread command for UDP and TCP, optional TCP null
  framing, receiver port and disabled or rejected settings. They do not
  claim an external collector received a message.
- The controller's actual read-only JSON actions pass positive and
  negative isolated Lua checks: denied bearer, non-GET requests, disabled
  export, authorized numeric-only JSON and bounded sensor error handling.
- A public, optional [off-device Prometheus adapter](../examples/monitoring/README.md)
  uses Python's standard library on the operator's collector machine,
  verifies HTTPS, accepts a private token file, exposes only eight
  documented numeric metrics and rate-limits polls with a cache.
  No collector service or runtime dependency is bundled on the ONU.
- An [ACL audit](V2R8-MANAGEMENT-ACL-AUDIT.md) records that the vendor's
  uhttpd listener binds wildcard IPv4/IPv6. Effective firewall and older
  firmware fallback behavior must still be tested on recoverable hardware.

### Boot startup registration correction

The initial draft shipped a new S11 init script but did not include a
durable startup link in the compressed image. Dynamically creating the
link in UCI defaults is not sufficient when rootfs_data can be discarded.
Adding a symlink to the public source is also prohibited by this project's
source-only verifier.

The reviewed implementation now retains the vendor's existing, immutable
S11sysctl rc.d link and adds one optional 12-second bounded call after
the original sysctl operations. The restore runs only when a durable
monitoring record exists. Stock UCI defaults match the qualified r7
source byte-for-byte, and no additional symlink or resident daemon is
distributed. Real boot timing and behavior remain unqualified.

## Three-pass preboot audit and privately qualified archive

The independent boot audit corrected the r8 startup packaging to reuse
the vendor's immutable S11sysctl rc.d symlink. The source-only project
forbids newly introduced symlinks, so a first-boot-generated startup link
would not survive every possible rootfs_data reset. The vendor sysctl
logic is preserved, with one bounded optional restore after its original
operations; stock UCI defaults remain byte-identical to qualified r7.

A separate private scratch release was assigned canonical v2r8 identity
without changing this public draft's historical r7 labels. Its refreshed
runtime candidate pins passed inspection. Independent r8 SquashFS images
and complete private upgrade archives were byte-identical. The standard
five-component archive, exact kernel and bootcore hashes, hardware
profile and release labels passed separate offline qualification.
The r8 image is **5,697,536 bytes** with **512 KiB** fixed-bank headroom.

All private outputs remain marked **UNTRIALED_OFFLINE_ONLY**. See
[V2R8-BOOT-READINESS-AUDIT.md](V2R8-BOOT-READINESS-AUDIT.md) for the
three-pass evidence, untested risks and the required A/B recovery gates.

## Remaining release-blocking work

1. **Collector authorization qualification:** A separate HTTPS-only, read-only token and exact IPv4 allowlist exist in offline source. Verify actual target HTTP header/TLS and management socket behavior, credential permissions, negative requests and persistence in an isolated recoverable environment.
2. **Access network:** Verify management-interface firewall ACLs and the absence of untrusted/WAN exposure on recoverable hardware. The request-level socket destination and source-IP checks are defense in depth, not a substitute for firewall testing.
3. **Persistence:** the durable store, early restore and fail-closed dual-record authorization are implemented in source and pass offline tests, but have not been qualified on an actual mounted ptconf UBIFS volume or across real reboot and A/B switching. Test interrupted writes, receiver reachability, low-space behavior and the original boot sequence on recoverable hardware.
4. **Performance:** benchmark concurrent basic metrics scrapes, expensive detailed `pontop` reads, idle memory and active CPU usage. Do not implement new background polling before measuring.
5. **Browser UX:** run real Chromium form submission/failure/test-event scenarios at desktop and mobile widths. Resolve all accessibility and styling defects before GUI signoff.
6. **Release freeze:** assign canonical r8 release identity, refresh all source manifest and runtime-integrity pins, verify actual compressed image archive and original vendor ABI, independently rebuild twice and complete full native regression tests.
7. **Hardware:** only after release gating and separately verified full-bank backups, obtain distinct stage-only, one-shot trial and permanent commit authorizations. Long-term reliability still requires evidence.

See [v2r8 plan](V2R8-PLAN.md) and the [monitoring integration design](MONITORING-AND-TELEMETRY.md). The r8 branch remains a candidate until every P0 gate is satisfied.
