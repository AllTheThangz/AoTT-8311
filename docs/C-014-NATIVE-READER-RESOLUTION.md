# C-014: Native reader failure resolved; scoped live reads verified

**Checkpoint:** November 5, 2026. **Scope:** corrected local qualification, a read-only native snapshot module, and native setter tests on generated files. No live environment or cache writes, service changes, firmware staging or bank changes.

## The earlier read failure was triggered by the diagnostic lock argument

The earlier qualifier supplied an absolute private directory using `fw_printenv -l`. Upstream U-Boot v2018.03, `tools/env/fw_env_main.c`, allocates that pathname using `sizeof(env_opts.lockname)` rather than its string length, then formats the directory and lock filename into the allocation. The relevant upstream blob is `d93a915fd142827e2259cd78b260565e4c4e76e6`. A long override can overflow that allocation before normal environment processing.

The behavioral comparison changed only the lock-directory argument from the long absolute path to the short relative name `locks`, with the working directory still inside the same private test workspace. The identical vendor binary and libraries then passed all four normal-read cases: single and redundant regular-file images, each using relative and absolute image paths. The trace now reaches the environment images successfully. No binary patch, library replacement, relaxed CRC check, timeout change or hardware-device access was needed.

The evidence ties the failure to the long custom lock argument and is consistent with the upstream allocation defect. It does not establish a defect in the physical device's normal default-lock operation. The failed reports are retained at the original diagnostic checkpoint, not overwritten or relabeled successful.

The corrected qualifier accepts only the fixed short `locks` argument in its private working directory. A long override is rejected before invoking the utility. Live reads do not override the utility's lock path at all. A test-launcher correction also accounts for LuCI changing child working directories to `/`; the local fixture restores its private working directory before invoking the short-path test. This correction affects fixture launching, not production lock behavior.

## Actual ONU access and baseline correction

The available Hermes `aott-onu` SSH profile was already a valid access path. The earlier assumption that the absence of a direct ONU MCP target meant no usable access was incorrect. The operator was not required to perform the check manually.

The earlier live baseline read matched all five reader/wrapper/library fingerprints against the extracted copies and successfully read an existing key. The missing VLAN override returned an ordinary undefined-key result, not a crash. That read-only baseline remains preserved separately from the emulation failure.

In this checkpoint, the new Lua module was sent through the established strict-host-verification SSH connection and executed from standard input, without installing a file on the stick. It performed two scoped snapshots of six management keys using the actual native reader. The snapshots matched exactly. Three keys were present and three were unset; none of the six was present-empty. Only classifications were exported, not addresses, MACs, setting values or a complete environment.

Live scoped report SHA-256: `9870c61831e77aa50ceb1977adf55227b3606b4d1c6f45079007d432a1bebb52`.

The reader binary hash was checked before and after. Native setter invocations on the ONU: **zero**. The native utility may acquire/update its ordinary advisory lock file; this is not a configuration, cache or firmware write. Repeated agreement does not guarantee that another writer cannot act afterward.

## Lossless scoped snapshot module

`prototypes/configuration/8311/native_management_reader.lua` invokes exactly one bounded `fw_printenv` process for six fixed names: address, mask, gateway, DNS, LCT MAC and VLAN. It does not use the convenience wrapper that substitutes defaults, does not use value-only output, and has no caller-supplied key, config path, command or setter mode.

The named output distinguishes `NAME=` from an exact undefined-key diagnostic. This preserves a present-empty value separately from an unset key. All six results must be present exactly once, the return status must agree with missing-key count, output is bounded, and unexpected messages are rejected. Bad-CRC/default-environment warnings, partial results, duplicate names, embedded control characters, extra keys, oversized values, timeouts and process failures cannot masquerade as an accepted snapshot.

Snapshot values remain private behind a handle. An internal accessor supplies copies for later transaction integration. The public diagnostic summary contains only state classifications and counts; changing a returned table cannot alter the stored snapshot. Reader success never grants write permission and does not qualify cache state, live UCI effects or reboot behavior.

The real vendor Lua/native-reader tests prove correct unset and present-empty parsing against generated redundant images, not just mocked stdout. The live stick happened not to contain present-empty values in this six-key scope, so present-empty behavior was not manufactured on the physical device for testing.

## Native file-based write evidence and remaining write limitation

Six additional cases invoke the actual vendor setter with explicit private regular-file configurations and short private locks. They verify nonempty apply/restore, restoration of an initially absent key by deletion, unchanged unrelated entries, read-and-restore after the first redundant update, refusal of a missing second image without modifying the first, and test-harness rejection of out-of-scope keys/config changes before execution.

These are actual native writes to disposable generated images, not writes to MTD, UBI or the live ONU. They test utility behavior on regular files, not NAND erase/program interruption or physical redundant-environment power-loss guarantees.

The actual setter, not only its shell wrapper, deletes a key when supplied an empty value. It cannot be treated as a lossless writer for an original present-empty state. A production write adapter must therefore either have a separately qualified lossless restoration primitive or refuse affected present-empty states before mutation. Absence must remain an explicit deletion operation, not an accidental consequence of an empty string.

The six live management keys currently have no present-empty entries, but that observation is not permission to change them or a guarantee for other users and future configurations. No production writer or physical environment/cache transaction has been installed by this change.

## Verification accounting

The final focused run passed **35 distinct tests, zero failures, errors or skips**:

- 16 diagnostic/wrapper/qualification tests, including the short-path guard and actual four-case reader qualification.
- 13 scoped-reader tests, including actual vendor Lua and reader execution.
- Six actual native setter tests on private regular files.

Final focused receipt SHA-256: `46fa2b0cd7f1d70267df128a066f136d2ad85baa399394a35305d7bcd10d9ec4`.

Corrected native-reader report SHA-256: `1da61cfb71fcdadb934a2dafdf301071af2c70f74c8484e124fcaa892dc7b147`.

The existing disclosure scanner initially flagged a literal synthetic MAC in a test. The test now uses the repository's existing designated synthetic fixture; scanner rules were not changed. The complete focused suite was rerun afterward. New module source hashes match the code exercised on the live stick.

The last full approved runtime result remains 1,131 tests at `d0d4a799ee660f2ddcebbf2ad444dba052995e0e`. That result does not automatically certify this changed diagnostic/reader tree. The prepared combined regression must discover and execute the exact new inventory before another full-pass claim.

## Release boundaries

The live read path is available and verified; there is no outstanding operator request to repeat the earlier baseline. The earlier source-publication safety blocker remains separate, and no alternate upload route is used. The deployable firmware overlay and manifest are unchanged at 83 entries. The new reader exists in local source and was tested in memory, not installed as a production service or GUI endpoint.

Next work is the guarded physical write/restore adapter, coordinated cache handling, durable recovery-store qualification and controlled hardware acceptance. Those changes still require their appropriate target approval, current backups and explicit trial/commit boundaries. This checkpoint does not modify live management values, ISP provisioning, credentials, certificates, services or firmware banks.
