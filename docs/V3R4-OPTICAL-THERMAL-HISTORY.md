# V3r4 optional optical and thermal history

**Status:** development source only. The reference PRX126 remains committed to V3r3. No V3r4 flash, bank stage, reboot, recovery operation, or live sampler activation was performed.

## User-facing controls

Local History gains an independent **Optical and temperature history** switch (disabled by default) and a configurable **60 / 120 / 300 second** interval. This reuses the existing single opt-in, RAM-only History worker. The configuration is guarded by the same UCI transaction, exact persisted-value readback, worker-lock verification, and truthful rollback reporting added earlier in V3r4. No additional daemon or auto-enabled service is introduced.

A new History panel offers latest RX/TX power, optic temperature and CPU temperature, lowest retained RX power, highest retained optic temperature, measured/attempted sample counts, two trend charts and a recent-optical-observation table. The bounded JSON and CSV exports include only validated numerical measurements, with units and independently observed source context. Optical history is volatile across reboots and cannot establish ISP Internet connectivity.

## Native PRX126 sources

The existing vendor optics page already reads SFF-8472 DDM measurements from `/sys/class/pon_mbox/pon_mbox0/device/eeprom51`. V3r4 reads a **maximum of 106 bytes** from this fixed read-only sysfs node and decodes only byte positions 97-106:

- Module temperature: signed 16-bit 8.8 fixed-point °C
- Module voltage: unsigned 16-bit / 10,000 V
- TX laser bias: unsigned 16-bit / 500 mA
- TX and RX power: unsigned 16-bit values in 0.1 µW, converted to dBm with `10 * log10(raw / 10000)`

It also reads the existing two kernel thermal sensors, bounded to 80 bytes per path. All seven output fields have conservative physically plausible bounds. The raw mailbox block is never returned, persisted, logged or made available to the browser. Only a fixed numeric allowlist is propagated. Invalid/missing sensors remain **unavailable**, never zero, and raw provisioning, device ID, authentication or MAC information is not read from alternate locations or copied to any exported result.

### Scheduler and resource control

PON, host Ethernet, and optics can now be sampled on independently due intervals. An optical-only tick performs the fixed sysfs reads and no extra native command process. Both host rate baselines and PON state comparisons survive intervening optical-only ticks without false status changes. All channels share the existing monotonic-uptime and boot-identity stability envelope; the collector drops cross-boot history from the public projection. One existing worker, bounded RAM rings, no periodic NAND writes, no external collector or WAN probing.

The browser requires strict source envelopes: a history projection cannot claim optical observations while carrying zero valid optical data, nor claim optical history unavailable when it actually provides optical numbers. Individual measurements also require an `observed` channel status and numeric ranges; unknown fields and private content are discarded. Graphs do not interpolate through an explicitly unavailable optical tick or a sampling gap over 10 minutes. The historical table and exports use ONU uptime, not a fabricated wall-clock timeline.

## Validation

- A read-only hardware spot-check confirmed the reference PRX126 exposes the fixed EEPROM DDM bytes and both thermal sensors. This does not validate the new firmware implementation on hardware.
- Source fixture tests decode actual-format DDM values; verify physical bounds, zero optical power as unavailable, malformed/truncated input, optical-only no-subprocess operation, CPU-only fallback, private data exclusion, uninterrupted host-rate baselines, reboot epoch isolation, and JSON-shape consistency.
- Host Lua 5.1 and offline vendor-MIPS Lua/QEMU execute the same fault-injection fixtures, with no device access.
- Real Chromium tests render the shipped History template and scripts against Lua-generated JSON, exercising live optical totals, two trend charts, CSV columns, missing samples, forged source claims and XSS/private-data exclusion.

**Known limits:** All results remain source-tested, not `hardware_qualified`. Optical sensors are board-specific; an incompatible stick should show Unavailable rather than a fabricated reading. Independent router-side IP/WAN reachability, long-term flash history and remote alert delivery remain roadmap items requiring separate safety and board-resource qualification. The user explicitly deferred another V3r4 deployment test pending additional substantial development; the accepted V3r3 24-hour observation and waived seven-day soak do not qualify V3r4 hardware.
