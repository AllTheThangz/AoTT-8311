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
- The current vendor remote-log service has **no supported severity filtering knob**. Do not expose a nonfunctional severity setting; collectors may apply their own filtering.

## Validation performed

- Static Lua 5.1 parser checks for the module and LuCI controller.
- Isolated source-level Lua tests using mocked UCI, logging processes and locks. The tests cover invalid configuration, stale revision, successful save, test emission and failed-logging-service rollback.
- The same Lua fixture passed in target MIPS Lua under QEMU. Security-negative tests exercise wrong or missing tokens, non-HTTPS requests, mismatched source and destination IPs, spoofed forwarded headers, stale credential requests, rotation and revocation.
- Full source manifest and privacy/disclosure gates passed after adding the candidate files.
- A **size-only** private SquashFS measurement using XZ and 1 MiB blocks is **5,697,536 bytes** against v2r7 **5,689,344 bytes**, a delta of **8 KiB**. Remaining fixed-bank capacity is **524,288 bytes (512 KiB)**. This is not a qualified flashable image.
- Python regression tests and actual browser tests must be rerun on the final candidate, including CI with the Chromium requirements enforced.

**Important:** this is not firmware qualification. The private size-only filesystem still carries the v2r7 runtime integrity profile. Its hashes are not updated for new files, it is not eligible for an upgrade archive, and it must not be installed onto a device.

## Persistence and vendor-runtime qualification findings

The vendor source explicitly documents that stock boot can delete rootfs_data
while the separate ptconf volume survives. Monitoring settings stored only
in UCI system configuration are therefore not yet guaranteed durable.

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
- The prototype exists under tools only. No early boot restoration or
  persistent-write integration has been added to the firmware.

See [durable monitoring design](V2R8-PERSISTENCE-DESIGN.md).

## Remaining release-blocking work

1. **Collector authorization qualification:** A separate HTTPS-only, read-only token and exact IPv4 allowlist exist in offline source. Verify actual target HTTP header/TLS and management socket behavior, credential permissions, negative requests and persistence in an isolated recoverable environment.
2. **Access network:** Verify management-interface firewall ACLs and the absence of untrusted/WAN exposure on recoverable hardware. The request-level socket destination and source-IP checks are defense in depth, not a substitute for firewall testing.
3. **Persistence:** implement and qualify a small root-owned persistent store, an early boot restore step and fail-closed dual-record collector authentication. The synthetic UCI/jsonfilter tests prove parser compatibility, not live boot behavior. Validate logging and A/B persistence on recoverable hardware.
4. **Performance:** benchmark concurrent basic metrics scrapes, expensive detailed `pontop` reads, idle memory and active CPU usage. Do not implement new background polling before measuring.
5. **Browser UX:** run real Chromium form submission/failure/test-event scenarios at desktop and mobile widths. Resolve all accessibility and styling defects before GUI signoff.
6. **Release freeze:** assign canonical r8 release identity, refresh all source manifest and runtime-integrity pins, verify actual compressed image archive and original vendor ABI, independently rebuild twice and complete full native regression tests.
7. **Hardware:** only after release gating and separately verified full-bank backups, obtain distinct stage-only, one-shot trial and permanent commit authorizations. Long-term reliability still requires evidence.

See [v2r8 plan](V2R8-PLAN.md) and the [monitoring integration design](MONITORING-AND-TELEMETRY.md). The r8 branch remains a candidate until every P0 gate is satisfied.
