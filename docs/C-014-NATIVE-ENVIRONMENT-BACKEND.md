# C-014: Native environment-backend qualification is blocked

**Checkpoint:** November 5, 2026. **Scope:** diagnostic tooling and documentation only. The tested transaction, supervisor, source-state modules and deployable firmware overlay are unchanged.

## Superseded blocker: corrected diagnostic and real-device reads

This document preserves the earlier failed qualification. The [native-reader resolution](C-014-NATIVE-READER-RESOLUTION.md) records the subsequent findings: the existing Hermes SSH profile works, the actual stick reads normally, and the emulator failures were triggered by the diagnostic's long custom lock-directory argument. The same unpatched binary passes all four cases with a short relative lock path inside the private workspace.

A scoped native reader now preserves unset versus present-empty states, and two read-only snapshots on the actual ONU matched. Thirty-five focused tests pass, including native regular-file write/restore checks. The original failed report remains unchanged for provenance. The physical production writer, cache coordination and power-loss qualification are still open; this correction is not a live-write approval.

## This is not another successful backend milestone

The file-backed startup transaction passed its approval-bound 1,131-test regression at commit `d0d4a799ee660f2ddcebbf2ad444dba052995e0e`. That result establishes its tested file-level behavior, not compatibility with the stick's native firmware-environment tools.

The next step tested the actual extracted vendor `fw_printenv` executable rather than another successful command stub. Native reader qualification **failed**. The subsequent fourteen passing diagnostic tests check the probe's refusal behavior, operator script, and wrapper semantics; they do not turn the failed native capability into a pass. No native environment setter was invoked after the read failure.

## Actual vendor-reader failure

`tools/qualify_vendor_env_reader.py` creates its own private, regular-file synthetic environment fixtures. It supplies an explicit private configuration and private utility lock directory for every environment-read invocation. It checks the generated CRC images independently and verifies image hashes before and after reading. No `/dev/mtd`, UBI volume, actual bank, production environment configuration or live management setting is selected.

The executable reports U-Boot 2018.03 and successfully returns help/version output. Four normal-read cases, covering single and redundant images with relative and absolute file paths, fail under the extracted MIPS runtime. In the final saved probe all four terminate with signal 7 (SIGBUS). Earlier exploratory calls terminated with signal 11 (SIGSEGV). The probe records the observed signal rather than insisting on one particular failure shape.

The bounded syscall trace observes the private configuration file opening, then failure before either environment image is opened. No hardware-device open is observed in that trace. This rules out a completed image read in the traced execution; it does not identify the exact parser, binary, library or emulator defect. The cause remains unresolved. In particular, these results do **not** establish that the same executable crashes on the physical ONU.

Reader binary SHA-256: `815053e739c4150d21209c84e4f1a1cc3840da9bbace5ebea3679b32bf8ff388`.

Final qualification report SHA-256: `59fe3fdc3e5cfa3ce2df1a37482ba4734bc27c3498c990a877cc55d44f3f8167`.

`C-014-NATIVE-ENV-READER-REPORT.json` contains the redacted result, input-integrity checks, native return codes and runtime dependency fingerprints. The qualification command exits 2, and the report sets production activation to false. Raw environment data and unbounded emulator traces are not exported. Core dumps are disabled in the bounded diagnostic children.

## Wrapper representation mismatch independently confirmed

The current extracted `fwenv_get --8311` wrapper returns the same default output and exit status for a missing key and a present-but-empty value. It therefore cannot, by itself, supply the lossless unset-versus-empty evidence required by the new transaction representation.

The corresponding `fwenv_set --8311 NAME ''` wrapper passes deletion to its underlying setter. It makes two calls as part of its redundant-environment update sequence, then checks the result. A test failure injected into the second call leaves the first change visible and returns failure; the wrapper does not itself restore the preceding value. These are wrapper control-flow observations, not a new claim about the physical flash protocol.

Those five wrapper tests execute the actual vendor shell wrappers using a private relocated lock helper and synthetic print/set executables. The underlying executable stubs are identified as stubs, never as successful native firmware writes. The original wrapper and vendor files remain unchanged.

Before a production adapter is acceptable, it needs an independently qualified exact snapshot reader and a representation policy for present-empty values. It must either restore them losslessly through a qualified primitive or reject unsupported source states before any mutation. Treating empty and unset as interchangeable without explicit migration would invalidate exact recovery. The existing two-call setter sequence must also remain covered by the transaction's failure handling rather than being assumed atomic.

## Read-only comparison on the real stick

The gateway was queried and still lists only the authorized development/cluster hosts, not the ONU. No SSH hop or other cross-target execution path was substituted. A physical comparison must therefore be performed through an authorized ONU target or an operator's local ONU shell.

`tools/collect_onu_env_baseline.sh` is an operator-run read-only script. It refuses non-MIPS hosts; identifies architecture/kernel; hashes the actual reader, wrappers and runtime libraries; emits limited mount and environment-layout metadata; and performs one time-bounded read of `8311_lct_vlan`. It reports only exit status and an output classification, not the variable value or a complete environment. No credentials, serial numbers, MAC addresses or public IP values are requested.

The native reader may acquire/create its normal advisory lock file. The script does not call a setter, clear a cache, restart a service, select a bank or write firmware. A missing key or diagnostic output is not declared successful reader qualification. The script has passed syntax and wrong-host refusal tests, but it has **not** run on the physical device.

The comparison will determine whether the current stick uses the same reader and libraries and whether its scoped native read succeeds outside emulation. It does not authorize test writes on the live connection. Any write qualification remains subject to verified backups, target-scoped approval, an appropriate isolated target and an independently checked recovery path.

## Test and release accounting

The final diagnostic suite has **14 passing tests, zero failures/errors/skips**. It verifies exact output comparison, empty/unset separation, CRC-fallback refusal, crash/error classification, file type/permissions, no escalation from read failure to writes, wrapper deletion semantics, second-write failure reporting, and the operator script's scope/redaction. One development assertion initially matched the word `service` in a comment; its correction checks executable lines rather than explanatory comments. The failed development output remains retained.

Diagnostic-test receipt SHA-256: `f729b08ec713150493731f51a41a4be1c5b051791b7d1d568b6b1355423c06d7`.

Native qualification remains **0 of 4 successful read cases**, with zero native setter invocations. The previous 1,131-test runtime checkpoint remains unchanged; no new project-wide regression or deployment is claimed for this diagnostic branch. There is no reason to request another full-suite token merely to repeat an unresolved native-reader failure.

Source publication is still unresolved. These files are retained locally; no alternative source-publication route is attempted. The actual next blocker is native backend/hardware evidence, not another synthetic test count. Production environment/cache integration, durable storage, real boot/service hooks, authenticated GUI integration and physical recovery/forwarding acceptance remain open.
