# H-011: PRX126 one-shot native telemetry reader, offline qualification

**Status:** source-only, not deployed. **Baseline:** November 2, 2026.

This continues the [RAM history prototype](H-011-RAM-HISTORY-PROTOTYPE.md).
It is **not** a resident collector, web dashboard, daemon, crontab entry,
procd service, firmware release, or flash-history store. The reader lives at
prototypes/history/8311/history_native_probe.lua and is deliberately excluded
from the production firmware overlay and release manifest.

## Native input contract

A future qualified local caller can explicitly invoke one snapshot. There
are only two potentially slow subprocesses, with immutable argv and the same
native command families already used by the current status handlers.

| Source | Bounded read | Interpreted value |
| --- | --- | --- |
| /proc/sys/kernel/random/boot_id | Max 80 bytes, read twice | Boot UUID, used internally to reject mixed boot epochs, never exported |
| /proc/uptime | Max 80 bytes, read twice | Monotonic start/end in seconds; the end marks the sample timestamp |
| /sys/class/net/eth0_0/speed | Max 32 bytes | Host-facing negotiated link Mbps only |
| /usr/bin/pon psg | BusyBox timeout 3 seconds, 1-second kill grace; max 1,024 bytes | Exactly one bounded current= state code, using existing strict parser |
| /usr/sbin/ethtool -S eth0_0 | BusyBox timeout 4 seconds, 1-second kill grace; max 16,384 bytes | Exact decimal RxGoodBytes and TxGoodBytes strings; no float conversion |

**Acquisition window gate:** end uptime must not precede start uptime and
the window must not exceed 12 seconds. The post-read boot UUID must equal
the initial UUID. If either condition fails, the entire observation is
rejected and the RAM sampler state is not modified.

If boot ID or monotonic uptime is unavailable, no native commands are run
and no sample is admitted. A PON or Ethernet command failure, timeout,
output overflow, conflicting state, malformed counter, or missing link speed
is marked unavailable, **not** an inferred outage, zero rate, or proof
of Internet connectivity.

The exact 64-bit counter parser rejects values above unsigned 64-bit
maximum and repeated counter fields. It does not serialize the raw ethtool
output. No registration credentials, LOID, SFP or subscriber MAC are read.

## Test and execution boundaries

The test fixture injects fake native providers and verifies exact paths,
argv, bounded outputs, boot-time consistency, synthetic reboots,
timeouts, missing measurements, interval rates, event classification,
redacted return values, and the optional native wrapper's behavior with
mocked dependencies.

    python3 -m unittest discover -s tests -p 'test_h011_native_probe.py' -v

With an independently extracted offline vendor rootfs, the same fixture
also runs through vendor MIPS Lua under QEMU by setting AOTT_VENDOR_ROOTFS.

No test launches native PON or ethtool commands, contacts a live ONU,
writes firmware environment variables, changes ISP VLANs or modifies
firmware banks. Real hardware qualification and operator-controlled
installation approval are deliberately excluded.

## Remaining H-011 and downstream work

- Validate kernel boot-ID availability and real parser output on a
  recoverable PRX126 reference module, read-only first.
- Measure sample latency, CPU, RAM, optics/host stability, dropped packets
  and management UI interference under idle and full-speed loads.
- Decide whether one-shot manual diagnostics should be available in the
  UI before adding a single periodic collector. The current prototype
  creates **zero** scheduled processes and zero flash writes.
- Independently validate PON event sampling, Ethernet accuracy, driver
  counter direction/reset behavior and chosen interval (H-012/H-013).
- Build bounded RAM history user interface and optional wear-limited
  persistent event summaries, with reboot/power-loss evidence (H-014 to H-016).
- Obtain real router/WAN-path evidence for Internet outages (H-017).
  PON O5.1 only indicates an optical registration state.

No additional XGS-PON stick is supported merely because these source
readers can be compiled for its CPU architecture.
