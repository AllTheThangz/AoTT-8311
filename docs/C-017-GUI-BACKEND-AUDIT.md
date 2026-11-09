# C-017 V3 GUI and backend audit

## Result

C-017 is now a generated source/browser release gate rather than a manual
checklist.

The machine-readable artifact is `C-017-GUI-BACKEND-AUDIT.json`.

Current source result:

- 14 AoTT menu pages;
- 14/14 pages mapped to real Chromium evidence;
- 24 POST-routed write handlers;
- 4 mixed-page or multipart write handlers;
- zero write handlers missing an explicit authenticated-session gate;
- zero write handlers missing an explicit CSRF gate;
- zero uncovered menu pages.

## Covered pages

Configuration, PON Status, PON ME Explorer, VLAN Tables, Support, Firmware,
Live Health, Security & access, Monitoring & telemetry, Local history,
Management preflight, HTTPS certificates, V3 status, and Access & servers.

The builder verifies each page route still renders its expected LuCI template
and that the declared Chromium evidence module still exists.

## Defects found during this audit

The audit produced real fixes rather than only documentation:

1. `action_save`, `action_save_hook_script`, and `action_job_cancel`
   now repeat explicit authenticated-session + CSRF checks inside the action.
2. Mixed Firmware and Support POST branches now also repeat the explicit
   session gate before the CSRF/write path.
3. The Support page hidden CSRF token previously had an ID but no form name;
   the production page now submits the token correctly.
4. Live Health contained corrupted explanatory text around O5.1 association;
   the sentence is corrected and browser-regressed.
5. Previously uncovered PON Status, VLAN Tables, Support, Live Health, and V3
   Status now have explicit page-level Chromium evidence.
6. Operator-owned TLS import and remote-access Access-page flows now have real
   Chromium coverage.

## Boundaries

C-017 is a source and browser-functionality qualification. It does not prove
physical PON behavior, external firewall reachability, management lockout
recovery on real hardware, or certificate trust in the user's browser. Those
remain hardware/runtime gates.
