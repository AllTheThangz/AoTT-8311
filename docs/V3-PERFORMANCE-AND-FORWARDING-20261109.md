# V3 performance and stability: forwarding and low-overhead telemetry

Status: SOURCE CANDIDATE ONLY, not flashed or deployed. No changes have
been made to vendor kernel, bootcore, PON/OMCI, VLAN/GEM mappings, bridge,
Ethernet negotiation, management passwords, firewall, routes, flash,
watchdog, or boot selectors.

## Live read-only baseline, 2026-11-09

- Firmware running on the LL-XS1010 / PRX126-SFP-PON: AoTT-8311-v3r1.
- Ethernet driver: lantiq_eth_drv_xrx500, negotiated 10 Gbps full duplex.
- sw256 hardware-associated bridge joins host Ethernet eth0_0 and gem2177.
- Vendor datapath components observed as loaded: mod_pon_eth,
  dp_eth_reinsert, gwdpa_dpm, qos_tc, ltq_eth_drv_xrx500.
- Ethernet RX/TX errors and drops did not increase during the tested
  passive interval. This is NOT a sustained throughput or line-rate test.
- CPU0 at 400 MHz and performance governor; secondary VPEs remain
  offline and are tracked separately.
- Passive sample of approximately 11.86 seconds: CPU busy 34.7%;
  Ethernet MAC traffic from router 5.751 Mbps, to router 0.688 Mbps;
  thermal zones 51.09 / 49.68 degrees C. No active load generated.
- Driver/module presence does NOT prove all packets use hardware offload.

A read-only, operator-invoked sampler is provided as
tools/bench_prx126_datapath_readonly.py. Run it from the administration
machine with the authorized SSH destination as an argument. It uses a
bounded fixed set of read-only commands and only prints anonymized
counter/CPU/thermal observations. It does not install anything on the ONU.

## Lower CPU use in the Live Health source candidate

Previously each Live Health poll ran bounded ethtool and two GEM pontop
subprocesses. The PON optical-status command was not bounded on the
interactive health path.

Candidate source:
- The existing full GET health_data route remains backward compatible.
- An authenticated GET-only health_data?detail=basic mode collects current
  optical/thermal, PLOAM and Ethernet MAC readings but skips both GEM
  diagnostic subprocesses. Invalid detail or non-GET requests fail before
  collecting. No database, daemon, flash history or credential is added.
- First load, manual refresh, and periodic full refresh at five-minute
  cadence collect GEM details. Other visible automatic refreshes are
  basic; hidden-page polling is already paused.
- GEM table is not silently marked freshly observed on basic snapshots.
- If GEM status fails, GEM counters are not called without a port map.
- PLOAM now uses the existing bounded 3-second/1024-byte vendor command.

At 30-second browser polling while continuously visible, the old rate
was 120 full page polls/h x 2 GEM commands = 240 GEM processes/h. With
a five-minute GEM cadence, the candidate invokes approximately 24 GEM
processes/h, a 90 percent reduction. Manual full refreshes and other
legacy clients increase the total. This is a *command-count estimate*,
not a measured CPU speed improvement.

## Required non-disruptive qualification

1. Preserve vendor PON, GEM/OMCI, data-path and QoS drivers and the
   current bridge. No speculative MTU, link, overclock, CPU-owner,
   DMA/CMA, routing, firewall or flash changes.
2. Reproduce source fixtures, source-privacy/manifest gates and complete
   UI regression. Produce a separate reproducible clean offline image;
   this source-only commit is NOT a firmware upgrade.
3. On an independently recoverable test module, compare hardware MAC
   counters and CPU load under the same controlled bidirectional
   traffic before and after. Observe PON O5.1, GEM provisioning,
   management SSH/HTTPS, throughput, latency, temperature and errors.
4. Before any stage/trial, verify full-bank backups and a known-good
   alternate bank. Independently prove LOCAL internet-independent
   automatic trial rollback, including loss of router/Internet/SSH/HTTPS,
   missed boot-health deadline, power loss, and corrupted network config.
   If bootcore fails, physical console/boot-ROM recovery is separately
   required; an A/B selector alone is not sufficient.
5. Every change with connectivity risk requires an exact parameter
   disclosure in advance, especially temporary or permanent passwords.
   A separate explicit stage/trial/commit authorization is mandatory.

## Evidence and limitations

Completed: live driver/bridge/module audit, 10 Gbps link check, passive
time-series counter sampling, synthetic Lua tests of low-overhead
polling, source manifest and privacy verification.

Outstanding: a controlled end-to-end 2.5 Gbps WAN workload, proof of
all-packet offload and real under-load CPU savings, real browser testing,
bootable image reproducibility and hardware independent rollback.
No new firmware was deployed or activated.

Related: docs/RESOURCE-ALLOCATION.md,
docs/PRX126-DEPENDENCY-AND-RESOURCE-AUDIT.md,
docs/V2R8-STAGE-READINESS.md,
docs/C-014-V3-GUARDED-MANAGEMENT-TRANSACTION.md.
