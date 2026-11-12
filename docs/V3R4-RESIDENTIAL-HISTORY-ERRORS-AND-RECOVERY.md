# V3r4: Residential History integrity counters and safe settings transactions

**Development-only source increment.** The reference PRX126 remains on successfully committed V3r3. No firmware installation, bank operation or connectivity-affecting change is authorized. A fresh V3r4 device test is deferred until the revision has more accumulated functionality.

## Additional RAM-only host Ethernet diagnostics

The optional single foreground History worker already samples host-interface byte counters, PON association, host-link speed and transition events. V3r4 now also samples four **actual PRX126 ethtool -S eth0_0** counter names on the same existing command invocation:

| Source counter | Historical observation |
| --- | --- |
| `RxFCSErrorPkts` | RX FCS error packets per validated interval |
| `RxOverflowError` | RX FIFO/overflow indications per validated interval |
| `RxDroppedPkts` | RX discarded packets per validated interval |
| `TxDroppedPkts` | TX discarded packets per validated interval |

All source readings are read-only, bounded at the existing 16-KiB ethtool output limit, and parsed as **decimal uint64 strings**, not inexact Lua doubles. An out-of-range, duplicate or malformed named counter invalidates the native report. No new daemon, timer, native command or polling-frequency increase is introduced.

The selective history sampler computes error/drop increments only when a valid host-rate interval exists and the same source/boot epoch continues. Regression, reset/wrap, missing data, unrepresentable delta and intervals over the configured limits are omitted, **never mapped to zero**. Increments are capped at one billion per interval to reject anomalous or corrupt data. No raw counters, boot UUIDs, MAC addresses, IP addresses, subscriber credentials or native command logs enter the public history export.

The History page adds a section displaying the **sum of retained, comparable interval increments**, four labeled counters, per-counter coverage and three error/drop columns in the recent-samples table. These are not lifetime totals, ISP network counters, or proof of Internet availability. Bounded JSON and CSV exports now include only validated interval deltas. If no measurement is available, the GUI says **Unavailable** instead of `0`.

## History settings write and rollback correctness

The RAM-only History configuration writer now:

- skips redundant UCI commits and init-service calls on a genuinely unchanged, verified configuration;
- catches exceptions from UCI commit and service operations after a possible partial save;
- verifies **exact explicit UCI field values**, not just the default-substituted values used for displaying a missing key;
- confirms actual worker state through the existing single-writer lock, distinguishing `enabled=1` from a proven running worker;
- if a write, service transition or readback fails, attempts to restore the prior UCI settings and service state;
- only states **previous settings restored and verified** when exact UCI readback *and* independent worker-state readback both succeed. Otherwise it reports rollback **unverified**, without inventing a clean result.

This is source-level correctness and simulated exception handling, not a physical NAND power-cut test. The existing `/tmp/8311-history-config.lock` retains serial writes. No persistent packet history, alerts, remote notification or unbounded flash log is enabled.

## Validation and limitations

New fault-injection fixtures use memory-only UCI, worker state and native ethtool reports. They test readback mismatches, missing keys hidden by defaults, native setter and service exceptions, successful and unsuccessful rollback, duplicate/out-of-range uint64 values, missing counters, epoch resets, and strict projection validation. Browser tests run the real installed History template/JavaScript against a synthetic Lua-generated data set, verifying sums, CSV structure, source privacy, malformed data rejection and no unexpected requests or writes.

This change does not add optical power/temperature history or a qualified router-side WAN probe. The History UI continues to label optical history **Not collected** and WAN status **Not verified**. Long-term NAND retention remains disabled pending wear/power-loss testing. The opt-in RAM-only collector is not enabled by default.

The existing V3r3 24-hour observation was accepted, and the maintainer waived a seven-day soak. The new V3r4 functionality needs feature-specific hardware proof before deployment; it is not hardware-qualified merely because a source fixture passes.
