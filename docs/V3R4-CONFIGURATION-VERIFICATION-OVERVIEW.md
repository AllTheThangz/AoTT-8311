# V3r4: Configuration Verification Overview

Status: **source-only development**, no device installation or hardware-qualification assertion. This improvement accumulates in draft PR #64 rather than triggering a fresh V3r4 trial.

## User-facing functionality

The Configuration page now contains a manual **Check all configuration evidence** action and a compact overview table with seven independent readback groups, covering the currently source-routed 55 Configuration controls:

| Group | Source-backed fields |
| --- | ---: |
| Management and access path | 10 |
| Device and host-visible SFP | 11 |
| Noncredential PON / OMCI | 4 |
| Redacted sensitive identity | 9 |
| Redacted reported metadata | 10 |
| Local ISP/VLAN | 3 |
| Advanced host and hardware | 8 |
| **Total** | **55** |

A result shows the number of successfully examined groups, independently observed runtime fields, supported saved/configured differences and invalid stored formats. Unreadable groups are **Unknown**, not zero, healthy, or automatically reconciled. Expanded group tables show each fixed setting identifier and a human-readable evidence classification. No configured, saved or observed **values** are displayed.

The overview never infers Internet access from PON O5.1 or host link speed. Historical VLAN reconciliation is labeled historical, rather than current throughput or forwarding proof. A source format check for a PON or OMCI field is not a claim that the OLT accepted it. A host-visible SFP setting that is only present in virtual EEPROM configuration is not a proven host readback.

## Integration and security

- Reuses the seven existing authenticated, read-only LuCI effective-state JSON endpoints. **No additional backend device probes, CLI writers or network service** are introduced. The individual detailed readback panels remain available.
- Bound same-origin, queryless controller paths are checked against a static seven-group allowlist before network activity. Each pass is **operator-triggered only**, with a maximum of two requests in flight and a 9-second deadline per request; no automatic polling.
- Verifies group and field source contracts and refuses data that attempts to claim unauthorized hardware qualification or lacks the expected secret-redaction flags.
- Displays **only fixed source field identifiers, static descriptions and computed counts** using DOM text nodes. Does not copy identity strings, IP/MAC values, credentials, hashes, command output, server errors or unknown response fields into HTML.
- Uses one polite screen-reader status region and labeled expandable tables. The default is no data until the operator clicks the action.
- The seven readbacks occur over several seconds; they are **not** a simultaneous/atomic configuration snapshot and do not establish reboot persistence.

## Offline tests

`tests/test_browser_config_verification_overview.py` executes the shipped LuCI template and real JavaScript in Chromium against intercepted synthetic replies. Five tests verify:

1. No automatic requests; seven authenticated read-only GETs after a click; all 55 fields presented in source-only classifications.
2. Genuine runtime evidence versus saved/runtime mismatch, plus distinct historical-reconciliation evidence.
3. Partial-failure behavior when a native probe fails or a field claims unsupported hardware qualification.
4. Rejection of an altered destination before any request is issued.
5. Untrusted HTML, private source values and unrecognized format flags are never rendered or executed.

This is a meaningful usability and evidence-accuracy improvement, but not a substitute for live per-field apply/verify/revert or hardware fault injection. The actual running reference ONU remains V3r3 with its previously accepted 24-hour passive capture. The maintainer does not require a seven-day soak, and has specifically deferred a fresh V3r4 deployment trial until more development work is complete.
