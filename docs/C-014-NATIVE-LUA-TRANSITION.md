# C-014: Lua-native management-VLAN planning and checked execution

**Checkpoint:** November 4, 2026. **State:** source candidate, not installed or hardware-qualified. The existing startup scripts and hidden management-VLAN control are unchanged.

## Why this step exists

The preceding C-014 candidate executes vendor UCI against disposable configuration copies, but its planner and execution coordinator use host Python. The new `prototypes/configuration/8311/vlan_transition.lua` implements those responsibilities in portable Lua 5.1, the interpreter already present in the extracted vendor image. Python remains a host-side test runner and comparison reference; the new transition core does not require Python on the ONU.

Inspection of the extracted `luci/model/uci.lua` found an important integration constraint: its cursor uses ubus, and its `set_confdir` and `set_savedir` functions return false. It cannot safely be assumed to redirect to private candidate configuration. The tests therefore use the existing vendor UCI executable with explicit private config/delta directories. No additional Lua UCI binding, crypto library or runtime package is introduced.

## Implemented source behavior

The Lua core parses bounded native UCI exports, validates their types, quoting and uniqueness, and produces the same transition state and ordered operations as the preceding Python reference for the supported profiles. It retains the existing constraints: explicit VLAN selection, exact LCT parent, zone name plus membership, preserved addressing/routes/DNS, ownership-scoped cleanup, no automatic adoption of legacy interfaces, and refusal of ambiguous or unsupported network layouts.

Reviewed plans are private handles. The before-state, proposed state and command list are retained inside the module, not taken back from a caller-modifiable request. A test-only projection returns copies; modifying a handle's visible fields or the copied projection does not change the executed operations. Immediately before execution, the fresh candidate snapshot must equal the reviewed state.

The execution coordinator checks every mutation and package commit, then compares a newly parsed persisted snapshot to the intended state. A semantic no-op performs zero mutations and zero commits. Invalid handles, non-fixture mode, stale state, failed commands and mismatched persisted values are refused. An unexpected adapter exception becomes a fixed error code; exception text or metatable behavior is not reflected to a caller.

The module itself performs no filesystem, shell, ubus, service, network or device access. It is not registered in LuCI and is not included in the firmware overlay. Its private plans and test projections contain configuration data and must never be used as public GUI or diagnostic output.

## Real vendor execution, not a mocked UCI result

`tests/c014_native_lua_fixture.lua` runs under the extracted vendor MIPS Lua binary. It uses the existing `8311.webutil.capture` process API, launches the actual extracted vendor UCI utility under QEMU, and supplies only synthetic, unpredictably named packages in private test directories.

The fixture checks private directory identity and modes, regular single-link candidate files, empty cold-read delta storage and absence of matching default-delta entries. Native calls have explicit time and output limits. Mutations use the private staged delta; commits use the previously verified `-p` behavior; each commit is checked by a separate no-delta reader before the fixture clears its own staged copy. No real `network` or `firewall` package is addressed, and no network reload occurs.

The native source path is Lua planning -> Lua execution checks -> existing process capture -> vendor UCI -> independent persisted-file export -> Lua validation. Python only creates disposable fixtures, starts the process, checks its outcome and confirms that the retained source files are unchanged.

## Tests

`tests/test_c014_native_lua_transition.py` adds 23 tests, including:

- Host-Lua plan/operation equivalence with the Python reference across tagged, untagged, unchanged, missing-route and scalar/list membership cases.
- Bounded export parsing, quote/backslash preservation, duplicate rejection, malformed inputs, invalid typed snapshots, sparse lists and metatables.
- Actual MIPS-Lua-to-UCI plan generation and complete tagged/untagged round trips.
- Failure at every forward and inverse mutation and both package commits, with first-failure stop behavior.
- Stale-plan rejection, forged-handle refusal, copied-plan tamper resistance and no-op write avoidance.
- Persisted-readback mismatch rejection and redacted adapter errors.
- Preservation of literal quotes, backslashes and shell metacharacters as data, not commands.
- Unsafe candidate-file rejection before native commands and unchanged retained source bytes after every native test.

```sh
AOTT_VENDOR_ROOTFS=/path/to/private/vendor/rootfs \
  python3 -m unittest discover -s tests -p 'test_c014_*.py' -v
```

The native tests require the extracted private vendor runtime, QEMU and root-owned disposable directories. The portable Lua tests do not require vendor binaries. Vendor binaries and real subscriber data remain outside this repository.

## Boundaries still open

This is a native-language core plus a disposable test adapter, not an installed production adapter. The test adapter is not a hardened on-device filesystem service and does not implement a transaction lock, encrypted backup, independent rollback watchdog, atomic two-package promotion, power-loss recovery or management-session confirmation. A failed operation can leave a partial candidate that must be discarded; no such candidate is promoted to the live configuration.

Actual LCT/host VLAN behavior, persistence across boot, physical management recovery and unchanged subscriber forwarding remain unverified. IPv6 and unknown management options remain explicitly unsupported rather than silently relocated. Legacy or unmarked management interfaces require a separately reviewed migration.

The next integration gate is a protected native staging/promotion transaction with independent recovery, followed by separately authorized hardware qualification. This change does not enable the hidden VLAN control, move an address, restart HTTPS/networking, build or install firmware, or select a firmware bank.

## Locked-staging follow-up

The [native staging-workspace guard](C-014-LOCKED-STAGING-WORKSPACE.md) now composes this core with single-owner kernel locking and synchronized pending/validated state in a single-use disposable workspace. Competing processes and interrupted candidates are refused without a live promotion path. This remains local source, not an installed recovery service.

## Validation checkpoint

The final affected C-014 suite passed **55 tests, zero skips and zero failures**: the eight startup-characterization tests, 24 preceding native-UCI candidate tests, and 23 new portable/native-Lua tests. Failure-injection subcases are included in those tests, not added as separate test counts. Source hashes were recorded before and verified unchanged after the focused run.

Focused run log SHA-256: `cf2754931c68449337e57a0ebf726aaf67c548c9971da3cb323091fdeb7d1155`.

The subsequently approved full combined regression of local commit `2439d2632825ef09c6cc7c82fea2b4d5bb91bf75` passed **911 tests, zero skips and zero failures**, exit code 0, without timeout. Its log SHA-256 is `a01750f4b0b45027d3a25aefe9bd3e789e9b063606e41763ce92360c252c485e`. The pinned source and saved receipt were independently verified after completion. This result belongs to that Lua-core checkpoint, not later locked-staging changes. Publication remains pending; no code was installed, and the firmware overlay and manifest remain unchanged at 83 entries.
