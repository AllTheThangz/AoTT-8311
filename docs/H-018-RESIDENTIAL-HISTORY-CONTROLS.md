# H-018: Residential monitoring controls and safe source-only preview

**Checkpoint:** November 2, 2026. **State:** offline source prototype only.
**Live collector, persistence, notifications and configuration saving:** NOT DEPLOYED.

## Goal

AoTT-8311 is a residential bridge and should expose useful choices without
unnecessary enterprise configuration. Supported items should be
straightforward to edit; unsupported controls must be visibly unavailable,
not silently ignored. Configuring a shorter interval must not jeopardize
PON registration, bandwidth forwarding, firmware management or flash life.

This milestone defines 17 potential settings in a single dependency-free
Lua 5.1 model at
prototypes/history/8311/history_preferences.lua. The model is neither
registered with LuCI nor included in the firmware overlay.

## Safe defaults

The proposed defaults have local sampling, event delivery, flash history
and remote notifications **off**. A preview can be calculated with these
features disabled, but no test creates a service or changes the running ONU.

| Setting | Default | Supported preview values |
| --- | --- | --- |
| Local collection | Off | On only with hypothetical qualified native profile |
| PON status interval | 60 seconds | 30, 60, 120, 300 seconds |
| Ethernet counter interval | 60 seconds | 30, 60, 120, 300 seconds |
| Optical sensor interval | 120 seconds | 60, 120, 300 seconds |
| Heavy diagnostic interval | Off | Off, 300, 900 seconds; qualified native reader only |
| RAM samples | 120 | 30 through 720 |
| RAM events | 128 | 16 through 256 |
| Compact persistent history | Off | Requires qualified collector and storage |
| Persistent retention target | Off | 0, 7, 30, 90 days; storage qualified first |
| Routine persistent flush | 1,800 seconds | 900, 1,800, 3,600, 7,200 seconds |
| Local event alert delivery | Off | Qualified collector and local-alert transport first |
| PON-change event choice | On | On or off for a future qualified alert source |
| Host-link event choice | On | On or off for a future qualified alert source |
| Missing-sample event choice | On | On or off for a future qualified alert source |
| Reboot event choice | On | On or off for a future qualified alert source |
| Optical RX low threshold | Not configured | Optional half-dBm step, only inside a qualified board profile |
| Remote notifications | Off | Not implemented; cannot be enabled |

Event selection is not event delivery: toggling which events a future alert
source would include does **not** enable any collection or transmission.

A strict source-only profile reports all currently unqualified features
as unavailable. A synthetic all-qualified test profile is used only to
exercise the full validator, not to attest actual board compatibility.

## Conservative resource and wear gates

The preview estimates a worst-case *native process wait budget*, not CPU
utilization: up to 3 seconds for the existing PON command plus 4 seconds
for the Ethernet counter command for each sampling interval. Optional
heavier diagnostics add a fixed simulated 5-second worst case.

The model rejects plans above **720 seconds of command wait per hour**
(20% of the hour), even if every other input is well-formed. This is an
early source-level bound, not an approved production polling frequency.
The final interval must be set using actual PRX126 CPU, memory, GUI,
optical stability, traffic and timeout benchmarks.

Routine journal intervals can never be below **900 seconds**, consistent
with H-015. Changing the proposed interval while persistence is disabled
does not cause a write. A 7/30/90-day target is allowed in the model only
after hypothetical storage qualification; it does not create any retained
history or prove the target duration can be met.

An optical threshold has no universal production-safe value. The source
requires a board-specific qualified minimum and maximum, rejects a
threshold outside that range, and supports explicitly clearing an optional
threshold. Real optical alerting requires verified sensor behavior,
calibration and an actual event delivery path. External notifications
are always unavailable in this milestone.

## Validation and revision contract

The API offers:

    defaults()
    source_profile()
    describe(source_capabilities)
    preview(current, proposed_changes, expected_revision, capabilities)
    simulate(current, proposed_changes, expected_revision, capabilities)

These methods take and return Lua tables only. They make no calls to a
filesystem, native command, network endpoint, background collector, LuCI
handler or actual settings store.

Validation rejects unknown fields, wrong types, nonfinite values, malformed
numbers, unsupported intervals and retention, opt-in features without
qualified prerequisites, inconsistent local alerts, unsafe polling budgets,
stale revisions, and no-effective-change requests.

Simulation returns a *separate new in-memory table* and increments only
its source revision. It does not claim transactional writes or durable
readback. For real configuration, the future worker must separately
implement authenticated read, validate, preview, apply, durable readback,
runtime effect verification, reboot survival and recovery.

## Operator-facing source preview

The following static files add a light/dark responsive and accessible
source-only preview without any save or device call:

    prototypes/history/ui/settings.html
    prototypes/history/ui/settings.css
    prototypes/history/ui/settings.js

The page renders all 17 fields from the actual Lua-generated catalogue,
groups everyday choices above the optional advanced controls, and disables
unqualified features with their explanation. Safe interval and RAM-capacity
changes produce a local resource estimate and can be reset. An unsafe
dual-30-second native polling request is rejected. Alerts and actual device
writes are never sent.

The browser cannot replace the server-side Lua validator. Its calculation
is only a human-readable preview of the same source contract. Every real
setting will need backend authorization and independent hardware proof
before this preview becomes a functioning configuration page.

## Reproduce

From the checked-out repository on a Lua 5.1 host:

    lua5.1 tests/h018_history_preferences_fixture.lua prototypes/history/8311/history_preferences.lua
    lua5.1 tests/h018_ui_seed_fixture.lua prototypes/history/8311/history_preferences.lua
    python3 -m unittest discover -s tests -p 'test_h018_history_preferences.py' -v

The 4,338-assertion validator fixture runs unchanged under the extracted
vendor MIPS Lua interpreter in QEMU. The real Chromium test suite:

    python3 -m unittest discover -s tests -p 'test_browser_history_settings.py' -v

uses the Lua-generated field catalogue and reference preview to check
the genuine source HTML, CSS and JavaScript, input validation, disabled
control behavior, no-save preview, reset, light/dark contrast, mobile
layout and blocked unexpected network requests. Chromium is required
by project GitHub CI, even if absent from the Hermes source host.

## What remains

1. Qualify the actual PRX126 input providers and resource impact on
   recoverable reference hardware before permitting collection.
2. Implement one shared, bounded periodic collector with cancellation,
   failure backoff and no duplicate polling loops.
3. Verify the H-015 UBIFS storage adapter with file/directory fsync,
   power cuts, flash capacity and NAND wear before offering persistence.
4. Introduce a source-authenticated local alert delivery path, real
   optical threshold profiles and a separate opt-in remote alert adapter.
5. Wire an authorized LuCI worker with durable readback, effective-state
   readback, rollback and auditability. No source-only preview is an
   installed or effective setting.

**H-018 remains IN_PROGRESS**. This contribution does not modify the
deployed firmware overlay, live WAN/ISP configuration, boot bank selector
or rootfs image.
