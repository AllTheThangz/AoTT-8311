# C-014: Management source precedence and reboot-agreement gate

**Checkpoint:** November 4, 2026, Eastern time. **Scope:** local native-runtime integration using private synthetic evidence. Not deployed, not a current physical-device readback.

## Corrected source finding

The preceding storage/boot audit inferred that the priority-26 network initializer could overwrite restored management UCI because it called address/netmask/gateway/MAC setters. Inspection of the selected PRX126 backend and execution of those actual functions show a narrower behavior: those backend setters return zero without changing UCI. The VLAN and DNS setters only log. The late initializer still brings the LCT and optional management interfaces up, so it is an activation boundary, but these management calls are not themselves the UCI writer.

The real management UCI writer is the boot-defaults block. Its getters read saved environment overrides through five current-boot cache files: address, mask, gateway, DNS and LCT MAC. Once present, those caches can hide a later saved override. The VLAN getter is uncached, so its value can change independently of the cached management fields. The startup-defaults DNS assignment also skips an empty value without deleting an existing UCI DNS entry.

The revised reference audit distinguishes these facts instead of classifying a function by its name. It checks the backend bodies and records six current integration risks: volatile `/var`, optionally discarded root overlay, defaults before the existing snapshot, cached source divergence, late interface activation, and stale UCI DNS after an empty source. `PRX126-BOOT-STORAGE-REFERENCE.json` schema 2 contains bounded source evidence and hashes.

This corrects the earlier broad claim; it does not remove the need to coordinate boot configuration sources or validate the actual installed board/backend.

## Authority decision

For this source profile, saved management environment overrides, supported defaults and a separately supplied board-MAC fallback are the values from which boot defaults regenerate management configuration. An already-staged or explicitly confirmed UCI candidate is not automatically authoritative for the next boot.

The current transaction does not persist changes to that firmware environment. It must not claim reboot-safe acceptance merely because the two UCI files and the retained journal are consistent. A confirmed VLAN change in UCI with an unchanged saved VLAN override is therefore detected as disagreement. The new code never repairs that disagreement by silently rewriting environment values, clearing caches, deleting routes or changing firmware-bank state.

A future production change must coordinate the authoritative environment, cache invalidation and effective UCI/kernel state under independently qualified recovery. Alternatively replacing that authority with a new durable configuration record would require an explicit migration and replacement of every relevant boot consumer. This checkpoint chooses neither an unreviewed migration nor a dual-writer fallback.

## Integrated native source-agreement module

`8311.management_sources` is a dependency-free Lua 5.1 interpreter with no file, shell, network, firmware-environment or service access. Its trusted adapter supplies only six explicitly scoped management fields: address, netmask, gateway, DNS, LCT MAC and VLAN. Extra environment fields, malformed records, unreadable values and unsupported interpretations are refused.

Environment absence and empty optional values are explicit evidence, not failed reads disguised as defaults. Known defaults are recognized for the address, mask and untagged VLAN. An absent MAC override requires independent factory-MAC evidence. Invalid saved input is rejected rather than quietly applying the existing shell getter's fallback behavior. DNS support is limited to the board getter's single-IPv4 contract, not arbitrary hostnames or multiple resolvers.

The module compares the saved-source projection, current cache selection and intended UCI topology. It checks direct LCT versus tagged management without accepting duplicate addressed interfaces. A stale cache is rejected even when it happens to match currently running UCI. A configured value that differs from the saved startup source is also rejected. Existing self-address gateways are preserved rather than automatically removed.

Reviewed evidence is held behind a private handle. Returned receipts contain status and counts, not configuration values, addresses or a raw boot environment. Changing visible handle fields or a receipt cannot change the stored evidence. Saved-source changes revoke the proof. A previously absent cache may be populated with the same reviewed effective value during defaults; once present, removal or modification during the sequence is rejected.

Agreement does not prove actual kernel effect, future reboot durability or Internet service. Every receipt retains those limitations and explicitly disallows production activation.

## Boot-recovery integration

`boot_recovery_gate.reconcile` now requires a workspace-bound disposable source-evidence adapter. After the existing native transaction restores an unconfirmed candidate or verifies an explicitly confirmed one, source agreement is required before a private boot handle is issued.

Every subsequent checkpoint repeats transaction-content verification and source-agreement checks. The ordered sequence includes defaults completed, system initialization completed, before network activation, network initialization completed, and before HTTPS activation. The added late checkpoint does not falsely describe the priority-26 helper as a UCI writer; it rechecks the evidence after that activation boundary.

A missing source file, an adapter exception, a source/cache conflict or a source revision change cannot be presented as successful boot reconciliation. A failed source check may follow a successful UCI rollback: the previous files are restored, but startup is still unqualified because another authority disagrees. The gate does not hide or automatically overwrite that conflict.

These are source-level checks, not installed init hooks. They do not themselves stop the current live service manager, and no production reader or writer was registered by this change.

## Tests against actual source behavior

The new suite has **31 distinct tests**. Six cases execute extracted repository getter/setter bodies under the real vendor MIPS BusyBox shell. Only fixed environment reads, cache paths, board-MAC fallback, logging and interface activation are replaced with isolated fixture behavior. The cache paths point exclusively inside private temporary test directories; the full startup library, firmware environment and live network are never sourced or accessed.

Those tests reproduce stale address/gateway/DNS/MAC caches, uncached VLAN behavior, and the late initializer calling interface bring-up without management UCI writes. Separate startup-defaults cases execute the actual repository block against the existing stateful synthetic UCI adapter, showing address regeneration and stale DNS retention. These adapter-based characterization results are not mislabeled physical UCI activation.

Other cases exercise portable Lua policy, malformed or extra evidence, known defaults, factory fallback, private handles, matching cache population, source changes, and native vendor-Lua/UCI boot integration. A confirmed candidate is rejected when its saved VLAN source remains untagged. Successful confirmation preservation is tested only with a separately supplied matching synthetic saved source, not an invented environment write by the transaction.

## Verified affected-suite result

**64 distinct tests passed, zero failures, zero errors and zero skips:**

- 31 new management-source precedence tests.
- 25 existing storage/boot/reference-audit tests updated for the stricter evidence requirement.
- Eight existing startup/VLAN characterization tests.

The storage/boot fixtures use a valid synthetic IPv4 resolver for this board-specific startup contract. The generic transaction fixture continues using a hostname to test representation preservation; that generic behavior is not proof that this board's DNS getter accepts hostnames.

Every expected affected-test ID is present exactly once in the saved receipts. Code hashes were recorded before and verified unchanged after execution. The final focused-receipt SHA-256 is `7ec254271180a8c78ebb4e9b7f10e59b4c8c76aa290972a0dd258ed37fa1cee7`. The reference-audit SHA-256 is `046035fda7b4c13707f0df81ec9fff7c8c211fc87786b75dcc0b8bc04a16d4d1`.

```sh
AOTT_VENDOR_ROOTFS=/path/to/private/vendor/rootfs \
  python3 -m unittest discover -s tests -p 'test_c014_source_precedence.py' -v
```

The final affected suite was rerun after synthetic test addresses were aligned with the repository's existing public-fixture palette. No disclosure-scanner rule was changed. Both source/disclosure scans pass across 360 files with 83 unchanged overlay entries. The final test-log SHA-256 is `43ec20ea1e06dd154e1b6a26f6a67e5bd21a47229b493a3b666d6a10ef6ee598`.

## Remaining gates

The parent storage/boot commit `753c65862d06566cab9421cce716b3dc80bf7dc8` passed its approval-bound full 1,068-test regression. That result is not claimed for this changed source tree; a new exact-source combined regression is required.

The authorized command targets were rechecked. The ONU is still not listed, so no cross-host SSH or alternate device path was used. Current image/bank identity, mounts, environment persistence, management recovery and physical forwarding remain unverified. Source publication remains blocked separately, without an alternate upload attempt.

The deployable overlay and manifest remain unchanged at 83 entries. No live device setting, stored credential, certificate, service, route, ISP identity, firmware image or bank selector was changed. The missing production environment/cache transaction and actual boot-service integration are not declared completed by this source-agreement gate.

## Subsequently verified parent and coordinated-record follow-up

This source-precedence parent (`07f9727a5abda651fef766be6a026067340d9544`) subsequently completed its approved full regression: **1,099 distinct tests**, zero failures, errors or skips, exit code 0, no timeout. The combined log SHA-256 is `979d57c284f9da6c097ddce0ccbbf188ea408e9329a199e0ff6a6c6ba770baf2`.

The [startup-state transaction follow-up](C-014-STARTUP-STATE-TRANSACTION.md) now coordinates private saved-setting/cache records with the same native UCI transaction, rollback and supervisor. It passes 140 affected tests, including 32 new cases. It does not yet implement physical firmware environment writes or real cache-path operations, and it requires a new full regression for the changed runtime source.
