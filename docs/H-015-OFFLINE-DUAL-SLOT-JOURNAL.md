# H-015: Bounded two-checkpoint persistence model and failure recovery

**State:** offline source-only prototype, November 2, 2026. **Not deployed.**

## Purpose

AoTT-8311 should preserve useful compact history across a restart without
turning a residential XGS-PON stick into a high-frequency NAND database.
Existing H-011 to H-014 fine-grained telemetry remains RAM-only. Only
whitelisted *change events* and coarse *hourly host-Ethernet summaries*
are candidates for flash persistence.

The pure Lua 5.1 model resides at
prototypes/history/8311/history_journal.lua. It performs no real
filesystem I/O, network probe, timer, shell command, LuCI request or
firmware change. An injected test adapter models storage. There is
**no deployed UBIFS adapter** and no on-device persistence claim.

## Journal capacity and logical limits

The compact ASCII format contains a version header, generation counter,
monotonic write epoch, fixed numeric fields, record count and Adler-32
checksum. Adler-32 detects accidental byte corruption and truncation;
it is **not** an authentication signature or defense against malicious
local file edits.

| Constraint | Source-only limit |
| --- | --- |
| History copies | Two alternating generation checkpoints, A and B |
| Staging allowance | One same-filesystem temporary image |
| Encoded image cap | 160 KiB per slot |
| Two copies plus temp | 480 KiB maximum logical payload |
| Retained state events | 256, oldest first |
| Coarse hourly summaries | 2,160, oldest first |
| Routine flush cadence | At least 15 minutes between writes in one boot epoch |
| New boot minimum | No routine flush before 15 minutes of new-boot uptime |
| Read-only export | At most 100 whitelisted records |
| Calendar queries | 7, 30 and 90 days relative to most recent explicitly verified record timestamp |

The 480 KiB figure is **only the logical content budget**. It excludes
UBIFS metadata, journal overhead, compression, write amplification,
erase-block allocation, bad-block reserve, power-failure replay costs
and other firmware consumers. It does not prove that a real 512 KiB
flash partition is usable. The maximum 2,160 hourly summaries describes
a theoretical 90-day hourly source stream, not promised real retention.

## API and safety behavior

    M.recover(storage_adapter)
    M.append(state, sanitized_candidate)
    M.flush(state, storage_adapter, current_epoch, now_uptime_seconds)
    M.inspect(state, limit)
    M.calendar_counts(state, days)
    M.pack(records, generation, epoch, uptime_milliseconds)
    M.unpack(encoded_checkpoint)

Append only updates RAM. Flush checks a minimum 900-second interval,
valid source epoch and monotonic clock, then prepares the next generation
in the inactive slot. It requires exact readback with valid integrity
before announcing a committed checkpoint. The previous slot remains
the recovery source.

After an uncertain write or readback the writer becomes frozen; it
cannot blindly retry until an independent recovery has resolved the
current best generation. Recovery chooses the newer valid generation.
With one torn or corrupt slot it can fall back to the older verified
copy. With both slots corrupt it fails closed rather than silently
erasing history. With the same generation but differing valid contents,
it refuses to guess.

## Required, unimplemented UBIFS adapter

Before enabling this feature, a board-specific storage adapter must
independently prove the following:

1. Only two fixed private slot names under a root-owned directory,
   with strict ownership, permissions, hard-link and symlink checks,
   plus one exclusive writer lock.
2. An exclusive, no-follow same-directory temporary file, a fully
   written size-limited image, followed by **file fsync**.
3. An atomic same-filesystem rename replacing only the *inactive* slot,
   then **parent-directory fsync** for durability.
4. Fresh readback with size, ownership, checksum and generation
   validation, preserving the previously good slot.
5. Injected cut points before staging, mid-write, after file sync,
   after rename and after directory sync. Independently check the
   next-boot recovery outcome.
6. Disk-full, write-protection, power-cut and simultaneous-writer
   scenarios must fail without degrading PON registration or routing.

A desktop POSIX filesystem test does **not** establish durability
on the vendor kernel or its UBIFS implementation. Real write tests
require separate, explicit operator authorization and hardware
recovery preparation.

## Clock, privacy and provenance

No boot UUID, serial, MAC, LOID, private registration value, raw
64-bit counter, device log, router address or arbitrary user text is
encoded in the checkpoint. Event types and numeric fields are strictly
whitelisted. The persisted epoch is a small counter, not an identity.

A future collector must map each recovered boot into a strictly
increasing storage epoch. Boot-relative uptime alone cannot be
joined into continuous calendar history.

A wall timestamp is stored only when a caller explicitly declares
it verified. This model cannot authenticate NTP or diagnose a false
clock. When there is no verified timestamp, the 7/30/90-day queries
return an unknown calendar anchor rather than inventing dates.
Even with verified synthetic records, the query explicitly refuses
to claim uninterrupted retention, present-day freshness or ISP uptime.

These hourly host-Ethernet summaries are not a customer Internet
speed test. Optical registration O5.1 is not proof of Internet
availability.

## Reproduce offline

From the repository source root:

    lua5.1 tests/h015_journal_fixture.lua prototypes/history/8311/history_journal.lua
    python3 -m unittest discover -s tests -p 'test_h015_journal.py' -v

For vendor-MIPS testing, use an independently extracted local rootfs
with the environment variable AOTT_VENDOR_ROOTFS and QEMU. No vendor
rootfs, customer credentials or private firmware images are included
in the public repository.

The deterministic fixture executes 2,624 assertions on each runtime.
It covers interrupted and truncated writes, prior-generation fallback,
dual-slot corruption, ambiguous sequences, cadence enforcement,
freezing after uncertain writes, 2,160 synthetic hourly records,
256-event bursts, 7/30/90-day filters, out-of-range values, untrusted
clock data, privacy stripping and rejected forged staged records.

## Remaining H-015 hardware gates

The genuine UBIFS adapter, locked and power-fail-safe writes,
runtime CPU/memory/thermal measurements, page and erase-cycle wear,
disk-full behavior, repeated reboots without NTP, hourly aggregation
scheduling, authenticated history GUI integration, and verified
7/30/90-day field retention **have not been delivered**.

The [H-018 residential preferences prototype](H-018-RESIDENTIAL-HISTORY-CONTROLS.md)
exposes a disabled-by-default persistence target and strictly limited
proposed flush intervals. The preview cannot call the journal adapter or
write real UBIFS records.

The source model occupies no deployed rootfs space. The live ONU,
its boot banks and ISP provisioning were not touched. H-015 remains
**IN_PROGRESS**.
