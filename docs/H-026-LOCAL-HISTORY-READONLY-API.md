# H-026: Authenticated, bounded history handoff

**Date:** November 3, 2026. **State:** offline source-only integration.
**Not deployed:** No live collector, LuCI history route, flash history,
or PRX126 hardware qualification exists in this milestone.

## Purpose

AoTT-8311 already has H-011 native snapshots, H-014 bounded RAM rates,
H-016 privacy-filtered JSON/CSV, H-021 independent polling and H-022
kernel-lock ownership. A residential history page should read one shared,
bounded view rather than execute a fresh PON or ethtool command for
every page visit.

H-026 implements a small local snapshot handoff and a source-only
administrator-session response contract. It does not register a LuCI
route, activate a service, start probes or change the firmware overlay.

## Files

- prototypes/history/8311/history_snapshot_shape.lua is a pure Lua
  5.1 validator of the complete H-016 projection, including five
  windows, at most 100 samples and 100 events, whitelisted fields,
  bounded numbers, safe status enums, and non-WAN/non-live flags.
- prototypes/history/8311/history_snapshot_ipc.lua is a source-only
  local file adapter using actual vendor MIPS nixio, nixio.fs and
  luci.jsonc. Publishing requires an existing H-022 guarded collector
  handle with an active fcntl kernel lock.
- prototypes/history/8311/history_http_readonly.lua is a source-only
  response contract. An independently trusted LuCI administrator
  session callback must authorize reading; request parameters never
  provide an authentication token, file path, target or hostname.
- prototypes/history/ui/history_authenticated_client.js is an
  uninstalled browser candidate. It only fetches after an explicit
  load action. The existing H-016 static HTML does not load it.
- tests/h026_projection_shape_fixture.lua and
  tests/h026_ipc_fixture.lua cover real Lua source and vendor-MIPS
  cross-process behavior.
- tests/test_h026_snapshot_ipc.py and
  tests/test_browser_h026_authenticated_client.py verify filesystem,
  HTTP-boundary and real Chromium behavior.

## Snapshot flow

The source-only publisher:

1. Confirms offline_synthetic mode and an H-022 guarded collector
   still holding the exclusive kernel owner lock.
2. Calls H-016's sanitized, bounded JSON export with one fixed hour
   projection containing all five window summaries.
3. Validates the entire nested JSON schema before writing anything.
4. Uses a root-owned private 0700 directory and the fixed filenames
   snapshot.json and snapshot.json.new.
5. Creates the staging file exclusively as root-owned 0600, regular,
   single-linked, with no unexpected symlink or inode replacement.
6. Writes no more than 65,536 bytes, synchronizes the staging file,
   and atomically renames it over the previously committed snapshot.
7. Independently reads back the published data and validates the
   full shape before reporting success.

A reader in a separate process validates the private directory,
file-descriptor and pathname inode identity, ownership, mode, link
count, byte length, JSON and nested projection. The extracted
vendor JSON decoder accepts trailing text and duplicate object keys,
so the decoded structure must also re-encode to *exactly* the original
bytes using H-016's canonical sorted serializer. Extra trailing data,
duplicate-key representations and noncanonical snapshots are refused.
Invalid files fail closed without being exposed to the browser.

A valid but abandoned staging file blocks further writes until the
collector's guarded owner explicitly discards that exact verified
staging file. Symlinks and unsafe file types cannot be discarded
by that operation. The last committed snapshot is not removed.

The vendor nixio ABI does not expose O_NOFOLLOW. Strict trusted
directories and fstat/lstat checks remain necessary and do not
protect against a privileged actor who controls the root-owned
directory itself.

**Storage limitation:** Hermes's offline /var/tmp test directories
may be disk-backed. This test does not prove an on-device RAM-backed
snapshot or flash durability. A future qualified runtime must use
a verified root-only volatile directory such as /var/run/aott-history.
The separate H-015 journal remains uninstalled and unqualified.

## Authenticated read-only response

The HTTP candidate accepts GET at the fixed source route
/admin/8311/history_data. It checks a trusted server-provided
administrator session callback before attempting any snapshot read.

Unknown methods, parameters or alternate paths are refused. A
snapshot must be under 65,536 bytes and must pass the strict
projection validator even when the injected reader returned data.
Errors never include a file path, serial number, boot identity,
credential, native report or raw exception.

Success responses use JSON, no-store/private caching, nosniff,
restrictive Content Security Policy, no-referrer and Vary: Cookie.
The fixed browser client requests only the same origin and refuses
redirects. Its response stream is byte-limited and times out after
seven seconds. It never automatically starts network access.

The browser switches between the existing five history windows
locally, without additional native commands, and can use H-016's
existing bounded JSON/CSV export controls.

**Cached history does not mean current WAN health.** The data
retains the flags indicating unknown calendar time, missing optic
history, unverified ISP uptime and lack of hardware qualification.

## Offline acceptance

Host Lua 5.1 and extracted vendor MIPS Lua/QEMU run the exact H-016
projection shape fixture. The MIPS IPC fixture uses genuine vendor
nixio file operations across separate processes and validates atomic
replacement, concurrent read access, stale staging, corrupted JSON,
symlink and hard-link refusal, and exact private permissions.

Commands from the source repository:

    lua5.1 tests/h026_projection_shape_fixture.lua prototypes/history
    AOTT_VENDOR_ROOTFS=/path/to/offline/rootfs python3 -m unittest discover -s tests -p 'test_h026_snapshot_ipc.py' -v
    python3 -m unittest discover -s tests -p 'test_browser_h026_authenticated_client.py' -v

Chromium tests load the source-only H-016 page with the separate
candidate client and intercept all requests. The candidate clears
previously displayed history and disables exports when a session
expires, rather than leaving stale private telemetry visible.
They verify no
automatic fetch, one explicit same-origin GET, authorized rendering,
401/403 and 503 refusal, bad JSON, invalid live/ISP claims,
oversized response blocking, redirect refusal and duplicate-load
suppression.

The public GitHub runner does not have the extracted private
vendor rootfs. Host Lua and Chromium tests run there; vendor-MIPS
kernel/ABI checks run on Hermes and are identified as offline.

## H-027 source-only follow-up

The [H-027 guarded lifecycle source bridge](H-027-GUARDED-LIFECYCLE-SNAPSHOT.md)
now connects the H-023 collector to this IPC publisher, performs
bounded source-clock publication, and verifies the H-022 kernel owner
before and after a reader accesses a cached snapshot. It also tests an
uninstalled LuCI root-admin session gate with local ubus rechecks.
These improvements do **not** provide a real LuCI endpoint, on-device
tmpfs, a running collector or verified WAN connectivity.

## Remaining gates

1. Authorize a direct, recoverable PRX126 management target and
   complete H-025 CPU/RAM, thermal, PON and forwarding acceptance.
2. Qualify a root-owned runtime tmpfs and true process/file
   permissions on that exact device.
3. Integrate the snapshot publisher into one H-023/H-024 collector
   process with a measured safe update cadence.
4. Add a real LuCI route bound to the existing administrator
   dispatcher and verify session expiry and error behavior.
5. Connect the browser client only after real authenticated readback
   succeeds without launching redundant PON probes.
6. Keep H-015 wear-aware flash and H-017 router-side WAN evidence
   as separate, qualified features.

H-026 remains source-validated, not hardware-complete. No live
firmware bank, ISP provisioning, boot selector, active ONU or
deployed GUI endpoint was changed.
