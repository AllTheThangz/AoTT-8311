# v2r8 implementation status: first offline candidate

Status: **development source only, not merged, not a verified flashable release**.

The base is the committed v2r7 source for the qualified PRX126-SFP-PON hardware family. No production ONU, flash bank, boot selector, provisioned PON identity, or private monitoring system was changed to implement this candidate. All public examples use placeholders rather than addresses from a real deployment.

## Implemented in this development branch

- A lightweight Lua module uses existing UCI and the vendor's OpenWrt logging service. A read-only inspection of the qualified vendor image verified that `/etc/init.d/log` supports `log_remote`, `log_ip`, `log_port`, and `log_proto` with **UDP and TCP** transport options.
- The authenticated Monitoring & Telemetry LuCI page can configure forwarding, receiver address/port and protocol, and enable or disable an **authenticated** read-only JSON metrics endpoint.
- Form submission requires LuCI session/CSRF validation, rejects unknown fields and malformed addresses/ports, checks a saved-configuration revision, locks concurrent AoTT monitoring writes, applies a single UCI system section, and reloads only the logger. A failed reload attempts to restore and verify the previous configuration.
- A bounded, locally generated test log message returns a correlation marker. It cannot confirm that a UDP or TCP collector received the message.
- The inherited anonymous `/cgi-bin/luci/8311/metrics` route is no longer registered. The replacement `/cgi-bin/luci/admin/8311/metrics` inherits LuCI administrative authentication, is disabled unless enabled in UCI and returns no more than the existing basic optical/PON metrics.
- The existing Live Health page remains authenticated and provides additional Ethernet and GEM diagnostics. No database, Python runtime, exporter service or flash-based historical log storage is installed.
- The current vendor remote-log service has **no supported severity filtering knob**. Do not expose a nonfunctional severity setting; collectors may apply their own filtering.

## Validation performed

- Static Lua 5.1 parser checks for the module and LuCI controller.
- Isolated source-level Lua tests using mocked UCI, logging processes and locks. The tests cover invalid configuration, stale revision, successful save, test emission and failed-logging-service rollback.
- The same Lua fixture passed in QEMU using the target MIPS userspace Lua interpreter.
- Full source manifest and privacy/disclosure gates passed after adding the candidate files.
- A **size-only** private SquashFS rebuild using the same XZ/1 MiB block settings measured **5,693,440 bytes**, versus the verified v2r7 **5,689,344 bytes**, a **4 KiB** increase. Remaining aligned rootfs capacity is **528,384 bytes (516 KiB)** in the unchanged 6,221,824-byte bank.
- Python regression tests and actual browser tests must be rerun on the final candidate, including CI with the Chromium requirements enforced.

**Important:** this is not firmware qualification. The private size-only filesystem still carries the v2r7 runtime integrity profile. Its hashes are not updated for new files, it is not eligible for an upgrade archive, and it must not be installed onto a device.

## Remaining release-blocking work

1. **Collector authentication:** determine a secure non-administrator read-only collection method or document an independently reviewed, tightly controlled authenticated proxy. Using the full LuCI administrator session for an unattended monitoring agent is not the desired final integration.
2. **Access network:** verify management-interface ACLs and no untrusted/WAN exposure on a recoverable test instance. A route under `admin` enforces session authentication, but does not itself prove an interface-bound firewall policy.
3. **Persistence:** test UCI reload, readback and log forwarding against the actual vendor build, including an unreachable receiver, failed reload, configuration conflict, reboot and bank switch. Lua mocks do not prove a procd runtime behavior.
4. **Performance:** benchmark concurrent basic metrics scrapes, expensive detailed `pontop` reads, idle memory and active CPU usage. Do not implement new background polling before measuring.
5. **Browser UX:** run real Chromium form submission/failure/test-event scenarios at desktop and mobile widths. Resolve all accessibility and styling defects before GUI signoff.
6. **Release freeze:** assign canonical r8 release identity, refresh all source manifest and runtime-integrity pins, verify actual compressed image archive and original vendor ABI, independently rebuild twice and complete full native regression tests.
7. **Hardware:** only after release gating and separately verified full-bank backups, obtain distinct stage-only, one-shot trial and permanent commit authorizations. Long-term reliability still requires evidence.

See [v2r8 plan](V2R8-PLAN.md) and the [monitoring integration design](MONITORING-AND-TELEMETRY.md). The r8 branch remains a candidate until every P0 gate is satisfied.
