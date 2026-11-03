# H-025: Direct-hardware qualification gate and safe resource evidence

**Date:** 2026-11-03. **State:** offline source and extracted MIPS ABI
preflight complete. **Direct PRX126 hardware admission: BLOCKED.**

## Why this milestone exists

AoTT-8311 needs real measurements before the H-021/H-024 history collector
can start on a residential XGS-PON stick. Test data from an emulated MIPS
runtime cannot prove performance, ISP reachability, stable O5.1
registration, or a safe forwarding path.

The current administration gateway permits Hermes and the five
Proxmox hosts only. It **does not** list the PRX126/ONU as a directly
authorized target. This work did not route through Hermes to contact
the stick, read active registration credentials, change device settings,
or start a real collector.

H-025 adds a strictly source-only one-shot resource capture model,
a local binary ABI preflight, and a fail-closed numeric evidence screen.

## Deliverables

### 1. One-shot resource snapshot, source-only

    prototypes/history/8311/h025_resource_probe.lua

The input is an injected read-only provider using the existing H-011
native source parser. The module accepts **offline_synthetic** only.
It cannot be used to access a live target until a separate,
directly authorized read-only provider and acceptance procedure exist.

The PON status and host Ethernet sample use only H-011's fixed,
time-bounded native argv. No raw command output or byte counters
are exported.

Additional fixed read-only kernel sources:

| Source | Output | Interpretation |
| --- | --- | --- |
| /proc/stat before and after native observation | CPU busy fraction over observed jiffy interval | Whole-system activity during the short read window, not collector-only CPU time |
| /proc/meminfo | MemTotal, MemAvailable (KiB) | Current memory headroom, not sustained pressure |
| /proc/self/status | VmRSS (KiB) | Calling process resident memory, not total system memory |
| /proc/loadavg | First load average | Background scheduling pressure indicator, not CPU percentage |
| /sys/class/thermal/thermal_zone0/temp | Thermal zone 0 millidegrees Celsius | Generic OS thermal zone, not proven PON optics temperature |
| H-011 read_once | PON state, host speed, host counter status, observation time | PON O5.1 and host link do not establish Internet connectivity or customer WAN throughput |

Every read is individually bounded. Missing, invalid or unsupported
sources return **unavailable**, not zero or a healthy state. A reboot
during the H-011 snapshot fails admission rather than blending samples.

Outputs exclude boot UUIDs, ONT serial numbers, MACs, LOIDs, raw counters,
native command buffers, destination IPs, URLs, passwords and other
subscriber identities. The snapshot explicitly states
hardware_qualified=false and approved_for_service_start=false.

### 2. Extracted reference ABI preflight

    tools/h025_reference_abi.py

Offline use:

    python3 tools/h025_reference_abi.py --vendor-rootfs /path/to/extracted/rootfs

This inspects only file metadata and ELF architecture. It does not
execute the PON, ethtool or other device commands.

On the available extracted vendor firmware, the source preflight
confirmed five mandatory **MIPS32 big-endian** components: pon,
ethtool, Lua, nixio.so, and BusyBox. It also confirmed that timeout
points to the fixed BusyBox applet. These findings prove basic
package/ABI consistency **only**, not an actual working driver, firmware
bank, kernel filesystem or hardware deployment.

The output always sets hardware_qualified=false and
production_activation_approved=false.

### 3. Conservative reported-evidence screening

    tools/h025_screen_evidence.py

The input is a local JSON file containing sanitized source snapshots
assigned to three named, *unattested* workload phases: idle, load and
recovery. The evaluator never accepts a device hostname, network URL,
SSH credential, target ID, activation token or remote command.

Input constraints:

- Source must be exactly offline_synthetic_unattested.
- At least 5 idle, 10 load and 3 recovery snapshots, at most 120 of
  each, with a 600 KB overall input size limit.
- Strict schema, no extra fields, no private identity fields, no
  claimed hardware authorization, no duplicate JSON keys or nonfinite
  numeric values.
- Missing/unknown numeric fields cannot be interpreted as a
  passing zero and are reported explicitly as insufficient evidence.
- A missing PON/counter reading, non-associated PON state or host
  down reading remains an observation issue, not a proven ISP fault.

The first-pass *hypothetical screening values*, intentionally
conservative but **not hardware-qualified**, are:

| Candidate screen | Source value |
| --- | --- |
| Minimum MemAvailable | 16 MiB |
| Maximum calling process VmRSS | 8 MiB |
| Maximum whole-system busy fraction during native read | 85% |
| Maximum thermal zone 0 | 85 C |
| Maximum H-011 native observation window | 11 seconds |
| PON and host channels | Each source report must be observed in the screening set |
| PON association | Reported state 51, without assuming WAN reachability |

These numbers are not approved safety thresholds for every PRX126 or
other XGS-PON stick. They are initial diagnostics to flag clear
evidence gaps and resource pressure. Final budgets must be derived
from actual on-stick measurements under representative residential
throughput and thermal conditions.

A report that falls inside every hypothetical limit returns only
reported_values_in_hypothetical_range. It **never** sets
hardware_qualified=true or production_activation_approved=true.
Even fully supplied numeric observations cannot independently
authenticate their provenance, a direct gateway approval, or actual
service uptime.

For an offline input file:

    python3 tools/h025_screen_evidence.py --input /path/to/sanitized-evidence.json

This tool reads the local input and prints an explicitly unapproved
JSON summary. It does not change the input file or execute native
commands.

## Repeatable source qualification

    lua5.1 tests/h025_resource_probe_fixture.lua prototypes/history overlay/usr/lib/lua
    python3 -m unittest discover -s tests -p 'test_h025_hardware_admission.py' -v

The Lua fixture runs unchanged on host Lua 5.1 and the extracted
vendor MIPS interpreter in QEMU. It exercises PON/host status,
exact read limits, CPU/memory/RSS/load/temperature parsing, failed
reads, unsupported sensor paths, malformed boot identity, sensitive
extra native text redaction and the synthetic-only admission guard.

The Python tests use a sanitized snapshot produced by that actual
Lua fixture. They verify source-only screen behavior, missing
measurements, malformed provenance, injected extra/private fields,
hypothetical limit failures, duplicate keys, nonfinite numbers,
input-size limits and the non-overridable production activation block.
Reference ELF tests also fail on incompatible/corrupt synthetic ELF
files.

## What is still required for H-025 hardware acceptance

1. Add PRX126 as an **independently authorized direct target** with a
   confirmed management-recovery route and separate operator consent
   for any future hardware write.
2. Qualify native PON and ethtool read-only commands, output sizes,
   source identity, Rx/Tx direction and monotonic boot boundaries on
   that exact board. Do not publish raw registration values.
3. Collect multiple approved **idle, sustained transfer and recovery**
   sessions with actual CPU/RAM, PON status, thermal, throughput/drop
   and latency measurements; measure native-process wall time.
4. Verify the real kernel's parent-directory lock behavior, shutdown,
   procd lifecycle, bounded retry and no PON forwarding degradation.
5. Establish approved device-specific memory and temperature
   budgets, rather than borrowing QEMU's 4 GiB virtual-space limit
   or hypothetical thresholds from this source screen.
6. Confirm A/B recovery independently. Do not activate an automatic
   collector, modify the active trial or commit a firmware bank here.
7. Only after those gates pass, separately authorize a real bounded
   provider and authenticated history/configuration endpoints.
   H-015 UBIFS persistence and H-017 router WAN evidence are separate
   qualification tasks.

The [H-026 source-only history handoff](H-026-LOCAL-HISTORY-READONLY-API.md)
now demonstrates a separately authenticated, bounded read-only GUI
contract with no per-page PON poll. Its local file and browser tests
are not permission to enable H-024 on a live module.

**H-025 stays IN_PROGRESS and hardware-blocked.** The active r8 trial
bank, committed fallback, public firmware overlay and ISP provisioning
were not changed.
