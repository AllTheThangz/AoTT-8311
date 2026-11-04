# H-026: Deterministic correction of the concurrent-reader test contract

**Checkpoint:** November 4, 2026. **Scope:** tests and documentation only. No history implementation, production overlay, device configuration or firmware changes.

## Previously observed failure

The C-014 characterization run recorded an intermittent failure in `test_multiple_readers_across_republish_get_valid_snapshots`: the vendor-MIPS fixture rejected `exact_sanitized_content`. Subsequent clean runs did not explain or fix that observation.

Inspection identified that the fixture performed two distinct operations: a direct IPC snapshot read, then an HTTP handler call that opened and read the snapshot again. It incorrectly required the second body to equal the first body even while another process was allowed to atomically publish a new generation between them.

## Deterministic baseline reproduction

Starting from main commit `bbc1daa27d8763daa6200dd233e113b27910a40c`, a private copy of the original fixture was paused immediately after its first valid read. An independent vendor-MIPS publisher installed the next valid generation. Resuming the fixture then reliably produced the original `exact_sanitized_content` assertion failure, exit code 1. Both underlying publications used the unchanged real source modules and actual filesystem operations under QEMU.

Original fixture SHA-256: `21333474b4d0fe65e8bcadf22b3c3da3a27238545facd32fa36d320cfc12876b`.

This reproduces the recorded symptom as a test-oracle error. It does not prove that every possible concurrency or security defect in the history system has been resolved.

## Correct concurrency contract

A successful HTTP response must equal the single fully validated IPC read used to produce that response. It need not equal an independently captured earlier generation. The concurrent fixture now counts its reads, compares the response to that captured body, verifies canonical complete projection data and privacy flags, and accepts only the known synthetic three- or four-sample generation.

The underlying reader is intentionally unchanged. When atomic replacement intersects one read's inode checks, it must still fail closed. The concurrent test accepts only the existing `snapshot_inode_changed` and `snapshot_readback_unverified` refusals, with HTTP 503 and the fixed generic error body. Missing snapshots, malformed content, unsafe permissions and arbitrary unavailable errors do not count as successful race handling.

Stable reads still require success. A reader that refuses all requests cannot pass these tests. Existing strict ownership, mode, single-link, symlink, size, canonical JSON, publication-lock and collector-lock checks are not relaxed.

## New deterministic tests

`tests/h026_reader_interleaving_fixture.lua` pauses the extracted vendor-MIPS reader at an explicit stdin/stdout barrier. The parent republishes only after receiving that signal, then releases the reader. No timing sleeps are used to induce these sequences.

The new cases establish:

- Separate complete reads across publication may legitimately return different valid generations.
- Replacement between initial stat and open is refused with the exact inode-change reason.
- Replacement before final stat is refused with the exact readback reason.
- The HTTP path returns only the generic 503 for either mid-read replacement, never mixed or partial data.
- A subsequent quiescent read succeeds without weakening checks or adding an automatic retry.
- The concurrent fixture rejects missing, corrupt and incorrectly permissioned files rather than accepting every 503.
- Repeated independent readers and publishers produce valid whole responses or the narrowly allowed race refusal.

The new monkey-patching and process synchronization exist only inside the test fixture. They do not add runtime hooks or a deployment path.

## Local validation

- H-026 source and native-MIPS tests: **23 passed, zero skips**.
- Adjacent H-027 lifecycle/publication-admission tests: **19 passed, zero skips**.
- Additional repeatability run: **30 test executions passed**, consisting of five repetitions of six scenarios. This includes 25 forced barrier sequences, 40 publication cycles and 320 concurrent reader requests.

The repeatability executions repeat tests; they are not additional distinct tests and are not added to the 42-test affected-suite count. The previously recorded 880-test full regression belongs to the preceding C-014 commit, not this changed test tree. A full native combined run is not claimed for this checkpoint.

```sh
AOTT_VENDOR_ROOTFS=/path/to/private/vendor/rootfs \
  python3 -m unittest discover -s tests -p 'test_h026_*.py' -v
AOTT_VENDOR_ROOTFS=/path/to/private/vendor/rootfs \
  python3 -m unittest discover -s tests -p 'test_h027_*.py' -v
```

Vendor-specific tests require the existing private MIPS rootfs, QEMU and root-owned disposable fixture directories. The public repository does not redistribute vendor binaries or production data.

## Deployment boundary

The history system remains source-only and hardware-unqualified. Actual collection overhead, on-device storage behavior, session integration, recovery and physical service stability still require their existing acceptance gates. This correction closes the reproduced false-failure cause; it is not a hardware reliability certification.

No ONU, ISP, management route, credential, HTTPS service, firmware bank or boot selector was accessed or changed. The 83-file firmware overlay and manifest remain byte-identical to the parent commit.
