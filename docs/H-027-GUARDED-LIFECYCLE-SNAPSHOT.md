# H-027: Source-only lifecycle snapshot publishing and LuCI session gate

**Checkpoint:** November 3, 2026. **Status:** offline source-validated,
live PRX126 hardware-blocked. **No new firmware overlay or LuCI route.**

## Purpose

H-026 established a bounded canonical JSON snapshot that could be
read in a separate process. H-027 connects that snapshot publisher to
the H-023 guarded collector lifecycle, ensures stopped and crashed
producers cannot serve leftover cached history, and validates a
candidate LuCI administrator-session gate against the vendor's
actual dispatcher authentication design.

This is intended for a residential bridge, not a remote enterprise
monitoring system. No external recipient, cloud service, database,
remote GUI exposure, flash storage or daemon is added.

## Integration

H-023's existing source-only history_lifecycle.lua now additionally
exposes:

    configure_snapshot(session, private_test_directory, "offline_synthetic")

Configuration is optional and must occur **before** the first
explicit collector start. The path may only be an isolated private
H-026 test directory, never a user-supplied URL or arbitrary file.

When configured:

1. The collector obtains its existing H-022 cross-process kernel lock
   before it can publish a snapshot.
2. On every new guarded session, it invalidates any previous cache
   and discards only a verified root-owned regular stale staging file.
   Symlinks or ambiguous files fail closed and prevent startup.
3. The first accepted sample produces a validated H-026 snapshot.
   Later accepted samples may update the snapshot **at most once every
   60 source-uptime seconds**. A not-due tick does not publish or run
   a second PON command. This interval is an offline source bound,
   not a qualified production write cadence.
4. H-021 independently schedules PON/host reads and continues to
   represent intentionally skipped channels as not_sampled. H-016
   projects exact counter intervals and excludes boot identifiers.
5. When a verified change of boot identity resets monotonic uptime,
   H-023 can publish a new latest-epoch snapshot without combining
   the old boot's byte counters.
6. A normal stop or shutdown invalidates the cached snapshot while
   the kernel lock is still held, then closes the collector.
7. If snapshot publication fails, H-023 enters bounded cooldown,
   attempts to revoke the current cache and releases the lock.
   If invalidation cannot be verified, the source session becomes
   unsafe and cannot restart.

Source receipts report bounded publication counts and whether
snapshot publishing is configured, without exposing a path, boot UUID,
serial, registration credential or raw counter.

A restart starts with fresh volatile RAM history. The H-015 journal
has not been installed or connected. No 7/30/90-day continuity is
claimed across restarts.

## Crash safety and source reader admission

H-022's process-lock model now offers a passive writer_present check.
It reads the fixed root-owned lock file and tests for actual fcntl
contention through vendor nixio. In the extracted MIPS runtime,
EAGAIN/EACCES (error 11 or 13) is recognized as lock contention.
Unexpected errors fail closed. No new lock file is created, and a
temporary test acquisition is released immediately.

H-026 now additionally exposes read_guarded, which requires the
kernel lock to remain held **both before and after** the bounded,
canonical JSON read. A leftover snapshot on disk after process death
cannot receive an accepted HTTP response without an active lock
owner. The H-026 read-only response contract has a source-only
serve_guarded_offline_ipc variant requiring this condition.

This is still not proof of a current subscriber Internet connection,
freshness beyond the last sampled observation, producer identity
against privileged attackers, or complete retention. A lock holder
can own the kernel lock while data remains stale. The schema
continues to state that calendar time, live resource qualification
and ISP availability are unknown.

## LuCI administrator gate candidate

    prototypes/history/8311/history_luci_route_candidate.lua

A source-only candidate mirrors the actual vendor LuCI dispatcher
contract: dispatcher.context.authsession, authuser and authacl are
populated after a successful local ubus session retrieval on the
inherited authenticated admin route.

The candidate requires a root administrator user, a strictly
structured session ID, and performs a **read-only ubus session.get
and session.access recheck** using that dispatcher-supplied session
ID, rather than a request cookie, query parameter or user-supplied
auth boolean. It prepares a fixed GET response from the guarded
snapshot reader and refuses other methods and unexpected query
strings.

Response bodies do not contain session IDs or ubus tokens. Errors
are fixed and do not echo credentials, filesystem paths, native
command output or private exceptions. The handler has an optional
source-only method for applying the response headers/body through
trusted LuCI HTTP methods.

The current tests inject trusted fake LuCI dispatcher, ubus and
HTTP modules and run the source adapter in extracted vendor MIPS
Lua/QEMU. **They do not prove actual running LuCI session behavior.**
The additional source authorization regression validates the vendor
dispatcher and rpcd ACL contract: the no-scope `session.access` response
is an `access-group` map, *not* a boolean `access` response. The route
now requires the inherited root dispatcher ACL **and** the separately
refetched ACL to contain the actual `luci-access` read/write group,
as defined in the vendor `luci-base.json`. An empty map, a boolean
`access=false` result, an unrelated group, malformed rights or a
mid-request ACL revocation all return a fixed 403. These tests use
synthetic session data; no live authentication was modified.

A genuine controller route, verified session expiry and browser UI
integration remain separate deployment tasks. This candidate is
not referenced by the current firmware controller or manifest.

## Offline verification

Source fixture:

    tests/h027_lifecycle_snapshot_fixture.lua

It runs the actual H-021/H-022/H-023/H-026 Lua models against fixed
synthetic native observations, including 60-second PON and
30-second Ethernet sampling, bounded snapshot publication,
unexpected failure and protected shutdown, boot-epoch changes and
source-only access refusal.

Additional fixture:

    tests/h027_luci_route_fixture.lua

It checks root session eligibility, trusted dispatcher context,
ubus get/access revalidation, expired/forged/guest sessions, POST
refusal, private error redaction and no alternate query parameters.

Process test runner:

    AOTT_VENDOR_ROOTFS=/path/to/extracted/rootfs \
      python3 -m unittest discover -s tests -p 'test_h027_lifecycle_snapshot.py' -v

It executes the actual vendor MIPS Lua/nixio/jsonc libraries across
distinct OS processes using root-owned private test directories.
Cases include simultaneous readers, clean stop, SIGKILL, deliberate
unclean process exit, cache revocation before a new session,
abandoned regular staging recovery, unsafe symlink staging refusal,
invalidated file permission handling, verified reboot, and
access controlled by the kernel lock.

The regular H-022, H-023 and H-026 test suites must also remain green.
The current test harness does not contact a physical ONU, router
or external endpoint. No target authorization is inferred from these
tests.

## H-028 handoff correction

[H-028](H-028-PUBLICATION-ADMISSION.md) narrows H-027's earlier
owner-only guarantee: a newly acquired `collector.lock` could
temporarily coexist with an old crashed publisher's cached JSON before
new-session invalidation. A separate short-readiness publication lock
is now held only after *this* writer verifies its first snapshot,
and both locks are required across reads. This corrects the known
handoff race without claiming live producer freshness, WAN availability
or PRX126 deployment.

## Production gates

1. Directly authorize a recoverable PRX126 management target.
2. Complete H-025 real on-device PON/host read costs, CPU/memory,
   thermal and forwarding no-regression measurements.
3. Qualify an actually volatile root-owned snapshot runtime directory
   on the PRX126. Hermes /var/tmp may be disk-backed.
4. Add the source-only publisher only to one H-024 collector after
   a production hardware provider, priority, resource limits,
   scheduler and crash recovery are independently qualified.
5. Integrate a read-only LuCI controller route using the real,
   inherited admin authentication dispatcher and confirm actual
   session revalidation, expiry and permission handling.
6. Complete authenticated dark/light/mobile history UI testing
   with live, non-sensitive observations, and verify no additional
   native PON command is run on each page refresh.
7. Keep H-015 flash persistence and H-017 separate WAN/ISP health
   evidence out of scope until independently tested and approved.

**H-027 remains IN_PROGRESS / source validated only.** No active
firmware installation, A/B selector change, ISP registration write,
ONU management change or live daemon activation occurred.
