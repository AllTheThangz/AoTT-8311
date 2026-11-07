# C-014: Journal-coordinated native environment writes

## Scope of this checkpoint

The existing native UCI/startup-state transaction now coordinates an explicitly scoped native environment transport as well. The first supported mutation is the management VLAN override, `8311_lct_vlan`. Other environment keys, credentials, ISP identity and bank selectors cannot be selected through this adapter.

The executable native transport is confined to disposable, generated redundant regular-file images. It invokes the actual extracted vendor `fw_printenv`/`fw_setenv` binary, not a success stub. No live device, production firmware environment, real cache path or boot service is selected. The deployable firmware overlay remains unchanged.

This closes a specific test/integration gap: native writes and restoration now participate in the same pending/confirmed/rolling-back decision as the existing UCI and startup records. It does not establish physical NAND durability or install a production writer.

## Explicit scope and fail-closed admission

A private workspace contains a fixed native-fixture marker. Preview requires its native six-key snapshot to match the reviewed saved-source record. A native request explicitly selects `uci_startup_and_native_fixture`. Missing marker/backend evidence or a changed scope cannot silently fall back to the earlier UCI-only or file-backed-source transaction.

The version-three journal records that native participation is required. Versions one and two remain separately supported with their existing meaning. The recovery worker and supervisor reconstruct the same disposable native transport in a new process, rather than depending on the failed apply caller's memory.

Before backup/staging, the guard confirms that only the VLAN override changes and that both old and new states can be represented by the native utility. An absent override can be restored by deletion. A present-but-empty VLAN override that would have to be restored is refused before any active modification, because the native setter maps an empty argument to deletion. Untouched empty values in other fields remain unchanged; they are not normalized or deleted.

## Native operations under the existing recovery decision

The previous and candidate UCI/startup records and their integrity manifest are retained before the journal is marked pending. Only after the independent worker acknowledges that pending transaction may the native transport run. Each of the two native setter calls is preceded by recovery-readiness and current-state checks and followed by an independent scoped native readback.

The second call is not assumed atomic with the first. A crash after call one, a nonzero return after a write, or a failed second call leaves the same journal recoverable. Rollback writes its decision first, restores the native override through two checked calls, and then restores all four file-backed artifacts. It deliberately completes both restoration calls after an interrupted recovery, even if the currently selected environment copy already appears to have the old value. This is conservative redundant-copy handling, not proof of physical power-loss safety.

Final apply readback also requires the native candidate after UCI activation and health probing; matching the previous journal endpoint is not an applied state. Confirmation checks the actual native candidate in addition to the retained-file hashes and existing health/readiness conditions. Terminal rollback and confirmation checks continue to validate the native state; they do not report success from the journal label alone.

An observed native snapshot that matches neither the retained previous nor candidate state is refused before blind restoration. The guard reads exactly six management keys, not a whole environment export. Preservation of unrelated entries is verified in the generated-image tests. The protocol assumes trusted cooperating code; it is not atomic compare-and-swap against an arbitrary concurrent privileged writer. A production environment/cache lease and hardware recovery policy still need qualification.

## Testing and evidence accounting

The new test module defines 24 cases: five command-scope/representation tests and nineteen integrated native transaction cases. They cover successful apply/confirm and boot agreement, unset restoration, unsupported present-empty refusal, no-op behavior, crashes during apply and restoration, failed/false-success commands, unknown changes, missing backend/marker evidence, expired confirmation, worker loss between native calls and automatic supervisor recovery.

The complete registered test inventory must retain the existing 1,166 cases plus all 24 new cases, totaling 1,190. This document is written before the full run and does not claim that count has passed. The approval-free installed sandbox service remains the execution path; no per-run operator token is required.

The actual cache representation remains file-backed. Production cache invalidation/repopulation, integration with the physical firmware-environment lock, durable device storage, authenticated GUI enablement, reboot acceptance and physical forwarding/power-loss qualification remain open. No firmware build, staging, reboot or permanent bank operation is authorized by this local checkpoint.
