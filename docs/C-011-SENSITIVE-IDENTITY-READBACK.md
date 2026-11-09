# C-011: Redacted source readback for the nine remaining sensitive overrides

**Checkpoint:** November 4, 2026. **State:** source integration and offline validation, not device deployment.

## What changed

The configuration page now includes a manual **Check redacted identity status** control. A new administrator-only GET endpoint at `/admin/8311/effective_identity` reads exactly nine named 8311-prefixed overrides:

- PON serial and vendor ID: `gpon_sn`, `vendor_id`
- Registration and logical ONU credentials: `reg_id_hex`, `loid`, `lpwd`
- Reported IP-host identity: `iphost_mac`, `iphost_hostname`, `iphost_domain`
- Root password-hash override: `root_pwhash`

Together with the previous 45 fields, every one of the **54 existing GUI fields now has a source readback contract**. The executable coverage test derives the GUI fields from the actual controller schema and checks all seven readback groups for omissions and overlap. This is not 54 independently proven hardware effects.

## Stored override is not effective state

Each row returns only one of four fixed statuses: saved override passes format checks, saved override has an invalid format, override unset, or read unavailable. An unreadable value is never described as absent. The model reuses `8311.config.validate`, which is the existing save-path validator; schema field identities and maximum lengths are checked against the actual controller.

A blank or absent override can still leave a vendor-derived or legacy value active. The native source has a legacy registration-ID fallback, derived vendor ID, cached IP-host data and separate root-password startup handling. This endpoint deliberately does not resolve these defaults, read the active shadow database, populate a cache, trigger a native setter, or infer that the OLT accepted an identity. It is not an authentication test, root-login check, reboot-persistence result or actual MAC-change proof.

## Privacy and access controls

The server returns no raw values, substrings, hashes, salts, fingerprints, lengths, command output or exception details. Native capture is bounded by the individual schema limit plus one record terminator, and each fixed getter is wrapped in the existing three-second timeout. No client-supplied field name, command argument or comparison candidate is accepted.

The endpoint inherits the LuCI administrator route and additionally verifies a nonanonymous root session and its management read ACL using the vendor's session get/access contract. Authorization is checked before reading and again before returning a response. Revocation, an expired session, an unrelated/empty ACL, a non-root user or an ambiguous session identifier fails closed. These authorization semantics are tested against synthetic adapters, not a real on-stick login session.

Responses are private and noncacheable. Reads occur only on an explicit button click; no automatic polling, export, local browser storage or write action is added. The browser constructs display text from fixed labels, rejects extra secret-bearing row keys and never echoes a server error string. Unsupported or failed responses clear the previous table.

## Source and tests

- `overlay/usr/lib/lua/8311/effective_identity_state.lua`: privacy-preserving classification using the real validator.
- `overlay/usr/lib/lua/8311/effective_identity_probe.lua`: bounded fixed-key reads and root-session checks.
- Existing controller, configuration template and browser JavaScript: route and manual status panel.
- `tests/effective_identity_fixture.lua`: real 54-field schema, host/vendor Lua, failed reads, format rejection, no-leak traversal, authorization and actual handler tests.
- `tests/test_effective_identity.py`: portable runner, integration and no-mutation contracts.
- `tests/test_browser_effective_identity.py`: real Chromium tests of the shipped template and JavaScript with synthetic intercepted requests.

The source overlay grows from 81 to 83 files and its manifest is regenerated for the two modules and three changed UI/controller files. No firmware image is built or installed by this change. The S-016 source test now checks exact manifest/file agreement rather than pinning all future releases to the old 81-file count.

## Reproduce

```sh
AOTT_VENDOR_ROOTFS=/path/to/extracted/vendor/rootfs \
  python3 -m unittest discover -s tests -p 'test_effective_identity.py' -v
AOTT_REQUIRE_BROWSER=1 \
  python3 -m unittest discover -s tests -p 'test_browser_effective_identity.py' -v
```

Only synthetic credential strings are used in fixtures. No production secrets or live ONU are read during development. The source validators accept the existing formats; they do not recommend insecure passwords or a particular provisioning identity.

## Validation receipt, November 4, 2026

The basic source regression ran 728 tests: 714 passed, 14 environment-dependent tests skipped, and zero failures. A separate mandatory real-Chromium run passed **120 browser tests with no skips**, including all eight new identity-panel tests. The recorded combined vendor/browser run then passed **848 tests with zero skips and zero failures** against the same source tree. Host Lua and the extracted vendor MIPS runtime exercise the actual validator, controller handler and full 54-field coverage union. Disclosure and manifest checks pass with 83 source overlay files. These results do not assert physical ONU deployment or live authentication correctness.

## Still required

Actual read-only PRX126 acceptance must confirm the deployed getter version, real LuCI session behavior, process/output bounds and service impact before this source change is considered hardware-qualified. Independent runtime consumers, safe setter behavior, persistence, recovery and the missing/hidden controls remain separate C-011/C-013/C-014/C-015 tasks. Do not mark C-011 DONE_HARDWARE based on this historical 54-field source-coverage milestone. Current V3 has 55 Configuration-page controls and separate A-to-Z transaction routing, but hardware qualification still requires per-route live evidence.

No live PON identity, password, HTTPS service, network configuration, firmware bank or boot selector was changed.
