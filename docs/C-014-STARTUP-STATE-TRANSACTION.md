# C-014: Coordinated UCI and startup-state transaction

**Checkpoint:** November 5, 2026. **State:** tested local source; no physical ONU writes, firmware build or installation.

## What is now connected

The existing native `vlan_transaction` implementation can coordinate four active artifacts in one reviewed transaction: network UCI, firewall UCI, a scoped saved-management-settings record, and a scoped cache-state record. It uses the existing locking, candidate UCI staging, retained backups, recovery-worker admission, explicit confirmation, independent rollback and supervisor. It is not a second disconnected recovery simulator.

The startup records are **private canonical files inside disposable test workspaces**. They represent six management overrides and five cache states. They are not the real firmware environment or files under the stick's actual cache paths. No environment-writing utility, raw flash operation, service restart or production cache deletion is invoked. This checkpoint establishes the coordination and recovery contract, not the physical storage adapter.

## Scoped planning and representation

`8311.startup_state` encodes only address, netmask, gateway, DNS, LCT MAC, VLAN and explicit factory-MAC fallback evidence. Unrelated firmware variables, extra fields, ambiguous records, noncanonical values and oversized input are refused. Unset overrides, present empty values and absent caches remain distinct. The text representation uses bounded hexadecimal value encoding to avoid record delimiters; it is not encryption.

The source planner reuses the previous management-source agreement checks. It accepts only a consistent starting profile. Unchanged saved values retain their exact original representation; the requested VLAN transition changes the saved VLAN record to the matching target. A changed management profile invalidates the five managed cache entries in the candidate record. No-op requests retain the original saved/cache bytes rather than rewriting their representation.

The underlying UCI planner still supports the qualified management-VLAN transition. This does not implement GUI changes for arbitrary address, gateway, DNS, ISP identity, credentials or all 54 settings.

## Explicit consent, preview and journal scope

A source-aware preview binds all four active artifacts, not just the two UCI files. The request must explicitly select `uci_and_startup_sources`; omission or a narrower scope is refused before staging. A partial source pair cannot silently fall back to UCI-only operation. The original version-one UCI-only journal remains supported for existing source tests and makes no claim about startup-source persistence.

The version-two journal contains before/after hashes for all four artifacts. Its version-two retained manifest covers eight previous/candidate files and exact lengths. Every retained source pair must also agree semantically with its corresponding retained UCI profile. All backup/candidate checks occur before recovery changes any active artifact. Missing source files, changed journal scope or unknown active data cause refusal rather than a downgraded restore.

There is no automatic migration of a pending journal, and a source-aware journal cannot be reinterpreted as version one merely because its active source records disappeared.

## Apply, rollback and confirmation ordering

Previous UCI and startup records are retained before candidate execution. Candidate startup records are planned from the same before/after UCI projection and checked for source agreement. The complete retained manifest and pending recovery journal are synchronized before activation.

The source-aware apply order is saved settings, cache state, network, then firewall. Independent recovery-worker evidence is rechecked before each replacement. This is **not an atomic four-file rename**; an interrupted intermediate combination remains under the same pending recovery decision. The worker or supervisor restores the complete previous set through the native recovery implementation.

Rollback records its decision before writing, verifies all retained inputs, restores the prior UCI and startup records, checks the complete result and then marks recovery complete. It can resume after interruption, without access to the original caller's source adapter or process memory. Explicit confirmation requires all four active hashes to match, fresh worker acknowledgement, the existing transaction-bound health checks, and an unexpired deadline.

Unknown changes are not overwritten simply because they occur in the cache record. The current record model is deliberately immutable outside the coordinated transaction. A future production adapter must separately qualify real getter-driven cache repopulation and cache invalidation, rather than weakening this check to accept arbitrary external writes.

## Boot agreement now uses the transaction result

In source-aware native tests, the boot adapter reads the actual transaction-managed saved/cache records. A confirmed tagged candidate now passes the existing boot source-agreement gate without manually modifying the older independent evidence JSON. An unconfirmed candidate restores the original startup records and UCI together before that gate succeeds. Tagged-to-untagged transitions in a fresh workspace are also tested.

This demonstrates cross-component consistency. It is not proof that the current physical boot scripts will consume these files: no production reader, environment writer or boot hook has been installed. Physical firmware environment persistence, cache paths, A/B behavior and source precedence still require an authorized device baseline and separately qualified adapter.

## Verified affected tests

The final affected suites passed **140 distinct tests, zero failures, zero errors and zero skips**:

- 32 new canonical-record and native coordinated-transaction tests.
- All 44 legacy transaction tests with the version-one behavior retained.
- 64 existing source-precedence, storage/boot and startup-characterization tests.

The new tests exercise saved-setting/cache replacement failures, interruption before UCI activation and during rollback, partial scratch writes, exact unset/absence restoration, unknown writers, unsafe files, scope omission/downgrade, malformed records, terminal confirmation, no-op behavior, inverse transition and the independent supervisor restoring all four artifacts after the apply caller is killed. The source copies are checked unchanged after native tests.

Each selected run records every test ID, source hashes and the saved-log hash. The consolidated record verifies all 140 IDs exactly once. Earlier smoke runs are not added to the distinct total.

Consolidated affected-receipt SHA-256: `c11dc2f8102f221d9af12deb610419429482031870c4ff5bfde9e3597c65b2c2`.

```sh
AOTT_VENDOR_ROOTFS=/path/to/private/vendor/rootfs \
  python3 -m unittest discover -s tests -p 'test_c014_startup_state_transaction.py' -v
```

## Full regression and remaining release gates

The previous exact-source combined run passed 1,099 tests for parent commit `07f9727a5abda651fef766be6a026067340d9544`. That success does not cover this new runtime revision. A fresh approval-bound full regression is required. The planned two-worker partition distributes the slower supervisor/admission/startup-state modules separately from the remaining configuration cases; the controller still requires every discovered ID exactly once and rejects failures, errors, skips or incomplete groups. No timeout or test assertion is weakened.

Source publication remains blocked and no alternate upload path is used. The authorized gateway still has no ONU target; no development-host SSH hop or substitute device execution is attempted. The deployable overlay and manifest remain unchanged at 83 entries.

Actual firmware-environment writes, cache-file installation, durable storage/bank qualification, real service/health hooks, authenticated GUI integration and physical recovery/forwarding tests remain open. Scoped records contain only synthetic data in these tests; their root-only plaintext storage is not an encrypted production backup. No live settings, credentials, ISP provisioning, route, HTTPS service, firmware image or bank selector was accessed or changed.

## Completed runtime regression and native-backend stop

This startup-state revision subsequently passed its approved **1,131-test** full regression with zero failures, errors or skips. Its saved log SHA-256 is `0aa155e86b098aa29f39805cdd35455b3cba9a7fd4aa5447f4d93ab1b070125a`. That remains a file-backed/native-UCI test result, not a native firmware-environment qualification.

The next [actual environment-reader qualification](C-014-NATIVE-ENVIRONMENT-BACKEND.md) failed in the extracted runtime, and wrapper tests expose unset/empty representation loss. Runtime source is unchanged while those backend requirements are unresolved. No additional passing synthetic suite is presented as resolution of that failure.
