# C-014: Protected retained configuration and boot-order reconciliation

**Checkpoint:** November 4, 2026, Eastern time. **Scope:** local source integration with extracted vendor-runtime tests. No physical ONU access or installation.

## Reference audit, not a current hardware baseline

`tools/audit_prx126_boot_storage.py` reads selected boot/startup source and filesystem metadata from an explicitly supplied private extracted rootfs. It never executes an init script or reads configuration values. The reproducible result is `PRX126-BOOT-STORAGE-REFERENCE.json`, including source hashes and line references.

The original audit identified four broad integration risks. The [source-precedence correction](C-014-MANAGEMENT-SOURCE-PRECEDENCE.md) now distinguishes six more precise blockers and corrects the late-writer attribution below:

1. `/var` is a symlink to temporary storage. The existing `/var/tmp` test workspaces must not be presented as power-loss-persistent ONU recovery storage.
2. When persistent-root mode is disabled, the existing startup helper can arrange removal of `rootfs_data` at boot. A directory inside that overlay cannot be assumed to survive reboot.
3. Vendor boot at priority 10 runs UCI defaults, before the current configuration snapshot service at 17. Installing a recovery service after that snapshot would already be too late to prevent all startup regeneration.
4. Management address/mask/gateway/DNS/MAC getters use current-boot caches that can hide later saved-environment changes.
5. The priority-26 initializer brings interfaces up, but the selected backend's management setters do not rewrite UCI. It remains an activation checkpoint, not the actual management UCI writer.
6. An empty DNS source skips startup assignment without deleting an existing UCI DNS entry.

Reference priorities are boot 10, configuration snapshot 17, system initialization 18, network 20, network initialization helper 26, and HTTPS service 50. These are source declarations, not measured live ordering or proof that each service is enabled.

The current administrative gateway lists the development/cluster hosts, but does not expose the ONU as an authorized command target. No SSH hop or alternate remote execution route was substituted. Current bank selectors, live image hashes, actual mounts, free space, root persistence mode, management routes, PON/host state and router-side Internet service therefore remain unverified in this checkpoint. Historical November 2 observations are not silently promoted to fresh device evidence.

## Retained-file protection is now in the actual transaction path

`8311.recovery_storage` is called by the existing native `vlan_transaction` implementation. Before staging, the transaction checks the native filesystem capacity result. Missing/invalid capacity, read-only status, insufficient free bytes, and inadequate inode headroom are refused before configuration backup or candidate writes.

The source policy requires 1 MiB of free-byte headroom and 24 available inodes when the filesystem reports finite inode accounting. This is a conservative admission threshold for the bounded two-package transaction, not an allocation reservation or NAND wear guarantee. Concurrent unrelated writers can still consume space; existing write/sync/readback failures must remain fatal and recoverable. The checks use the vendor nixio `statvfs` interface, not guessed free-space values.

After native UCI staging succeeds, a synchronized private retained-file manifest records the exact lengths and SHA-256 values for the two previous and two candidate files. It is bound to the transaction workspace. The manifest must be written and read back successfully before the recovery journal is armed or either active fixture package is replaced.

Recovery, confirmation and terminal-state verification now require both the original journal checks and the complete retained-file manifest. Missing, unsafe, malformed, extra, cross-workspace or mismatched manifests are rejected. The implementation does not reconstruct a missing manifest and pretend that the original integrity evidence survived.

The scope remains the management `network`/`firewall` pair. This does not yet back up all 54 environment fields, ISP identity, root credentials, certificates or every vendor UCI domain. Copies remain root-only plaintext; they are not encrypted exports. SHA-256 detects accidental corruption and inconsistency, not a malicious privileged rewrite of all records.

## Proposed durable location remains an evidence-gated design

The proposed production store is a private versioned directory below `/ptconf/8311/aott-recovery/v1`, rather than the temporary or optionally discarded root overlay. It is a proposal, not a directory created on the device.

The native storage evidence screen requires an actual mount identity, supported persistent filesystem, writable state, trusted ancestor checks, root-owned mode-0700 storage, same-filesystem evidence and capacity. Unknown or temporary filesystem evidence is refused. Even a passing screen returns `production_activation_allowed=false`: mount observation alone does not prove bank compatibility, safe power-loss behavior or complete backup coverage.

The extracted reference's directory modes and mount possibilities are not sufficient to grant this gate. Live verification, explicit provisioning and a protected production adapter remain required.

## Early boot reconciliation and later-writer detection

`8311.boot_recovery_gate` invokes the existing transaction recovery implementation, rather than another standalone restoration model. On a synthetic restart it restores an unconfirmed transaction, preserves an explicitly confirmed transaction, and refuses corrupted or incomplete recovery material. Partial preparation without an armed journal is quarantined rather than guessed into a valid recovery state.

After reconciliation, a private handle enforces ordered checkpoints for defaults, system initialization, network admission and HTTPS admission. The same transaction identity, terminal phase, workspace identity, boot identity and retained content are revalidated. A later native UCI write that changes the restored configuration revokes the gate instead of being silently accepted or blindly overwritten.

These checkpoints do not execute services and do not install real init hooks. They are not proof that network exposure is prevented on the existing boot sequence. The priority-26 management writer must still be reconciled with the priority-20 network service and the authoritative environment settings. The audit explicitly blocks merely assigning a new init-script priority and declaring boot recovery complete.

## Verification and the test-race correction

The final affected verification comprises **126 distinct passing tests**, zero failures, errors or skips:

- 25 new storage, reference-audit and boot-reconciliation tests.
- All 44 existing native transaction tests with the new retained-file checks enabled.
- 26 admission tests and 31 supervisor tests, including a new process-observation regression.

The first supervision compatibility command had an interrupted transport response and left two completed records. One passed; the other exposed a `TypeError` in an existing test that read process identity twice in one condition. The worker could exit between those reads. Both logs are retained. The corrected helper takes one observation per iteration and recognizes process-incarnation changes. A deterministic unit case reproduces the old error and verifies the correction. The runtime supervisor was not changed by this test fix, and the corrected supervisor suite passed separately.

Receipts identify every expected distinct test ID and its saved-log hash. Source hashes were captured and verified after each run. Repeated or duplicate transport executions are not added to the count.

Consolidated focused-receipt SHA-256: `0d009ecd4a8b6a8a0880bcd7da94aca9a655b666ce31d2e1608e961a0cf985a4`.

The parent's full 1,042-test result belongs to `0c15e114392b49c622765518469bd5514ec5358d`. It is not a full-regression claim for this changed tree. A new pinned combined regression is required.

## Full-regression execution plan

The previous serial full run took 538.413 seconds before these additional cases. The next approval-bound runner is planned to use two disjoint local test workers: the C-014 family, and all remaining tests including browser tests. Every discovered test ID must belong to exactly one worker; success requires both workers to finish with zero failures, errors or skips and unchanged tracked source. This changes test scheduling, not test assertions, the target, the firmware, or the approval requirement.

The fixture families use isolated private workspace names, and the C-014 native paths do not operate on real host configuration packages. Parallel scheduling is still subject to the managed-process timeout and finite child cleanup. No result is claimed before that exact runner has been approved and completed.

## Release and live-device boundaries

The source and documentation are retained locally. The earlier source-publication block remains unresolved; no alternate source-upload route is used. The deployable overlay and manifest remain unchanged at 83 entries.

No persistent directory, production service, certificate, credential, management interface, ISP setting, firmware image or bank selector was changed. No firmware was built, staged, trial-booted or committed. Authenticated GUI integration, actual service/health hooks, complete supported-setting backup coverage, production boot installation and physical-device acceptance remain open.

## Completed parent regression and stricter source agreement

The storage/boot parent commit `753c65862d06566cab9421cce716b3dc80bf7dc8` subsequently passed its approved **1,068-distinct-test** full regression, with zero failures, errors or skips. All discovered tests executed exactly once across the two disjoint groups. The combined log SHA-256 is `38b40053ee3cdd52ba3b1cddfa3404d977c0311f7b68d69704acdd129ae1d724`.

The newer [management-source agreement gate](C-014-MANAGEMENT-SOURCE-PRECEDENCE.md) requires the saved overrides, caches and recovered UCI profile to agree. A UCI-only confirmation does not authorize a contradictory next-boot source. The new source tree has 64 affected tests passing and requires its own full regression; no production environment or cache writer was added.
