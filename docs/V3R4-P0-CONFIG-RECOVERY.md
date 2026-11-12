# V3r4 P0 configuration transaction recovery hardening

Development status: **source-only**. Applies to the V3r4 draft; the verified V3r3 firmware remains running on the reference ONU.

## Failure found and corrected

The ordinary configuration writer persists reviewed values in the boot environment and only then calls the native live activation layer. Previously, if activation returned `nil` (for example, because it could not construct its runtime adapter) the writer returned a failure without restoring the startup values. The next boot could therefore apply a value that was reported as rejected.

The writer now treats no receipt, a malformed receipt, and an unexpected Lua activation exception as **unverified activation**. It attempts to restore every saved startup field under the existing lock and verifies each saved value through the native firmware environment getter. It clears any purported successful field list and reports the saved rollback separately from the unresolved live runtime state. It does not echo arbitrary exception text or label an unverified runtime as a complete rollback. Native setter and getter errors during persistence or restoration are also contained, and best-effort rollback still runs when a setter modifies a value and then throws.

## Native runtime rollback proof

`8311.config_activation` no longer equates successfully returned set/commit/reload commands with a completed rollback. It captures command status, configured-state readback, and evidence from each supported runtime consumer. A setter returning success while retaining the wrong configuration is caught by readback. Runtime probes remain bounded; an unavailable, deferred or mismatched probe is explicitly **unverified**, not a success. The receipt includes booleans for commands, configured readback and runtime verification, and field IDs of unverified settings without exposing observed sensitive values.

The outer configuration transaction's second recovery attempt now requires configured and active-consumer evidence for each field. A successful recovery function returning `runtime_pending` cannot be counted as verified runtime restoration.

## Regression coverage

Memory-only Lua fixtures test rejected/no/malformed activation receipts, thrown exceptions, post-write setter exceptions, incomplete rollback and deceptive successful setters, multiple saved fields restored in reverse order, and verified versus pending native recovery. These tests do not change live UCI, PON, Ethernet, administrator credentials or device firmware.

## Remaining work

This change improves truthfulness and recovery for 22 routed lower-risk live-activation fields. It does **not** prove every one of the 55 Configuration-page fields or 22 Access & Servers fields has an independently verified consumer on actual PRX126 hardware. Network/management/optical configuration transactions still require their separate guarded transaction paths and field-level hardware acceptance. A complete power-loss/crash consistency audit also remains open.

The maintainer accepted the completed 24-hour V3r3 stability observation and waived a 7-day soak. That decision does not establish V3r4 hardware qualification.
