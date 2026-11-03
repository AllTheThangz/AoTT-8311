# H-017: Independent router-side WAN reachability evidence

**State:** source-only offline prototype, November 2, 2026. **Not deployed.**

## Purpose

Residential ISP diagnostics must distinguish optical registration, host
Ethernet link speed, and an actual tested Internet path. A healthy XGS-PON
O5.1 state or 10G host speed alone does not establish that a customer's
router can reach the Internet.

This model accepts bounded, normalized router-side probe *reports* supplied
by a future separately authenticated adapter. It contains no probe
scheduler, network client, DNS resolver, HTTP client, connection credentials,
firmware changes, or flash database. A declaration of router provenance is
**not authentication**. Until a trusted adapter and real router path are
qualified, none of these reports prove live customer Internet connectivity.

## Observation contract

A candidate report must use the declared router_wan origin and its own
router_monotonic clock domain and boot marker. Router uptime is never
compared directly with ONU uptime, and no shared wall-clock timestamp
is invented.

The model permits up to four uniquely numbered target slots with fixed
probe kinds: DNS, HTTPS, TCP, and ICMP. Each probe reports pass, fail or
unknown, plus an optional bounded latency for a successful result. Invalid
identities, extra slots, duplicate slots, bad measurements or unauthorized
field shapes are rejected. Target hostnames, addresses, labels, credentials
and raw diagnostic output are discarded, not exported.

| Evidence | Meaning | Explicit non-claim |
| --- | --- | --- |
| PON O5.1 associated | Optical registration observed | Not Internet uptime |
| Host speed greater than zero | Nonzero negotiated host speed reported | Not customer WAN bandwidth |
| One or more WAN targets reached | At least one declared router-side test succeeded | Not proof every Internet path works |
| All submitted targets failed | Those specific tests did not succeed | Not proof of an ISP fault |
| Partial or unknown target results | Reachability evidence inconclusive | Not a confirmed outage |
| Missing router probe reports | No trustworthy reachability evidence | Not automatically disconnected |

The public result retains per-sample pass/fail/unknown counts, optional
successful-test latency minima/maxima, and explicit uncertainty flags.
The three layers remain separate even when they disagree. The output
states that router-origin authentication, simultaneous measurement,
subscriber throughput and ISP failure attribution are **not verified**.

## Historical behavior

- Default RAM-only history: 120 bounded samples and 64 bounded events.
  Hard caps are 720 and 256 respectively; each export is limited to 100.
- Record status changes between decisively observed target responses.
  Do not call a target failure a confirmed ISP outage or infer the cause.
- A transition through unknown or unavailable evidence is a change in
  observation quality, not proof of WAN recovery or disconnection.
- Repeated missing or identical probe results do not generate an event
  storm. Boot changes and intervals over an hour break continuity.
- Event windows use the router-side monotonic clock. A sampled event
  is bounded between observations, never assigned an exact outage time.
- Only the private RAM state retains a router boot identifier. No
  target name, URL, subscriber credential, device identity, IP, or MAC
  is included in exported samples or events.

## Tests and reproducibility

The model is kept outside the firmware overlay:

    prototypes/history/8311/wan_evidence.lua

Run under Lua 5.1:

    lua5.1 tests/h017_wan_evidence_fixture.lua prototypes/history

Run the test suite:

    python3 -m unittest discover -s tests -p 'test_h017_wan_evidence.py' -v

The deterministic fixture performs 1,127 assertions and passes in host
Lua 5.1 and an extracted vendor MIPS Lua under QEMU. The public repository
never contains the vendor rootfs, customer endpoints or provisioning data.

## Remaining deployment blockers

1. Design a small **opt-in** router-side probe method with user-configured
   endpoints and explicit source authentication. The ONU's local-management
   path is not automatically routed to the Internet.
2. Qualify the actual router WAN interface used for each test, DNS and TLS
   behaviors, independent destination failures, captive portals and local
   LAN/router faults. A failed probe alone cannot attribute blame to an ISP.
3. Confirm monotonic source identity, freshness, compatible clocks and
   reboot handling. Accept no unauthenticated WAN-positive claims.
4. Measure actual CPU/RAM, probe overhead, WAN packet loss, latency and
   power/thermal behavior with PON associated and not associated.
5. Join verified WAN evidence to H-011/H-012 sampled link events only
   after confirming the measurement windows, without inventing timestamps.
6. Build an accessible history UI and bounded persistent summaries with
   wear/retention testing. This offline model provides neither.

H-017 stays IN_PROGRESS. It is a proof of data semantics and false-claim
prevention, not a working ISP connectivity-history feature. No firmware
bank, boot configuration, router, ISP provisioned service or live ONU
was accessed or changed by this milestone.
