# AoTT-8311 start-of-session and end-of-session checklist

This is the standing protocol for continuing the project without rediscovering requirements, losing test evidence, confusing firmware releases or silently abandoning an unfinished feature.

## Start of every engineering session

1. Read [project state](PROJECT-CONTINUITY.md), [requirements](TARGET-STATE-AND-REQUIREMENTS.md), [coverage](CONFIGURATION-COVERAGE.md), [backlog](DELIVERY-PLAN-AND-ACCEPTANCE.md) and [decisions](ENGINEERING-DECISIONS.md), in that order.
2. Read the latest root-only private operator state and evidence if authorized and available. Public GitHub documents intentionally exclude private bank hashes, credentials, exact private paths and flash images.
3. Reconcile the active repository branch and open pull requests against public main. Main may lag a private hardware trial. Do not mistake a source PR or offline candidate for an installed firmware.
4. For any real ONU interaction, make a **read-only state check first**: board identity, firmware, active/committed/pending/running-trial, both bank receipts, PON association, host link, SSH/HTTPS recovery and available backup evidence. The dated checkpoint is not authoritative after another boot.
5. Select the first genuinely unfinished work ID from the backlog, unless the user names a higher-priority dimension. Update only that dimension and preserve all other constraints.
6. State what can safely be done now without a firmware write and what will require an explicit user operation or independent target approval.
7. Work in a separate source workspace for new features until source, vendor-MIPS and browser tests pass. Never use the live flash bank as a code editor or development scratchpad.

## Required controls during source work

- Reproduce the original input and capture a small negative/positive test.
- Identify authoritative backend and hardware capability before adding a GUI control.
- Ensure read, validation, preview, durable readback and actual effective state are distinguished.
- Confirm browser behavior in light and dark themes, mobile and authenticated contexts.
- Never serialize actual registration, passwords, MACs, hostnames, public IPs or private keys into a public test fixture.
- Preserve vendor PON/OMCI, MIB, crypto, device calibration and firmware compatibility pins.
- Update the source overlay manifest whenever an overlay file changes.
- Run applicable Lua 5.1/vendor MIPS, shell, Python, Chromium, manifest and disclosure tests.
- A passing test says only what was exercised; source tests do not prove physical OLT or WAN service.
- Record test invocation, counts, failures, environment and exact source change/commit.

## Required controls during live firmware work

Only use the authorized device and independently verified image/board profiles. No automatic permission can be inferred from "continue" for a permanent firmware commit or destructive action.

1. Verify current selectors and unique image hashes before considering a write.
2. Confirm a full recovery copy of the bank to be overwritten, original committed fallback and alternate management/physical recovery.
3. Distinguish stage-only installation, one-shot trial selection, reboot, permanent commit and rollback. Obtain the approval for the specific action.
4. Never stage over the only known-good bank, even when off-device recovery exists.
5. Use native locks and fresh state fingerprints, not old session approvals.
6. On timeout or disconnect, inspect the native state, boot ID and all relevant receipts before deciding whether anything succeeded. Do not retry the operation automatically.
7. Prove optical PON, 10G host link, relevant router Internet service when testable, management, recovery and full bank integrity after boot.
8. Save an independent acceptance receipt before calling a firmware hardware-tested.
9. Keep the original committed fallback during a trial; permanent commit is a separate explicit decision.
10. Document deviations, including a rejected command and an overly eager verifier. Do not erase failed attempts after a later successful outcome.

## Test completion, not appearances

A setting is not complete because:
- a GUI widget renders;
- a UCI or environment variable has a value;
- a backend process exited with status zero;
- a firmware version string looks correct;
- the PON says O5.1;
- the Ethernet host reports 10 Gbps;
- a single source-unit test passes.

A setting becomes complete only when all applicable source, effective-state, persistence and recovery gates pass on a documented supported platform. Mark unfinished behavior explicitly rather than assuming success.

A WAN/ISP history feature becomes complete only when optical, Ethernet and actual Internet reachability are not conflated, the sample clock is reliable, event gaps are reported and storage wear is controlled.

Cross-hardware support becomes complete only after real board detection, image/driver compatibility and tested recovery. A marketing name is not enough.

## End of every substantial work session

Write a dated successor or update the canonical state records with:

| Item | Required contents |
| --- | --- |
| What changed | Source paths, branch/commit, setting IDs, firmware identity |
| What passed | Test count, test environment, native readback or hardware result |
| What failed | Exact failure and whether action outcome is known or uncertain |
| Live device | Last observed active/committed/pending/trial, image identity and PON/host health |
| What was untouched | Flash, selectors, credentials, public release and other sensitive operations |
| User decisions | New accepted requirements or constraints, no reversals by guesswork |
| Remaining work | Specific backlog IDs, next concrete independent operation and dependencies |
| Approval | Whether a new explicit and target-issued approval is needed |
| Evidence | Durable private receipt plus sanitized public documentation reference |
| Date | Verification timestamp, not just assistant message date |

If there is not enough evidence, state "not verified" rather than guessing.

## Continuous documentation discipline

- A public documentation branch is a candidate, not a merged release.
- Keep the public handoff navigable using relative links and preserve upstream attribution.
- Never publish the private operator ledger, flash dumps, provisioning, subscriber serial, real MAC, public IP or TLS keys.
- Archive completed source milestones and known-good release artifacts in persistent storage, with SHA-256 verification and root-only permissions for private files.
- Prefer immutable dated checkpoints plus a current index over silently rewriting old records.
- After new firmware milestones, explicitly reconcile public main, open PRs, source release metadata and the true private hardware state.

## Current first actions as of 2026-11-02

- Live operations: preserve original r8 as committed fallback until a new separately authorized permanent B commit, after practical residential trial acceptance.
- Development: C-010 capability registry; then C-011/C-012 per-field backend tests and C-014 broken management VLAN diagnosis.
- Observability: H-011 bounded in-memory sampler and H-012/H-013 event/rate integration, without writing persistent history to the live stick.
- Compatibility: X-010 board adapter capability interface; X-012 second real PRX126 hardware candidate only with recovery proof.
- Release/publication: keep the sanitized documentation in a reviewable PR until it is deliberately merged; public main is not the private r8 image.

A useful session completes one or more of these work IDs with evidence, updates the applicable files and reports exactly what remains.
