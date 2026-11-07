# C-014: Native-UCI staged management-VLAN transition candidate

**Checkpoint:** November 4, 2026. **State:** offline candidate, not a live VLAN repair. The installed startup scripts and hidden GUI control are unchanged.

## What this implements

`tools/c014_vlan_candidate.py` plans a narrowly scoped management-network transition from bounded UCI exports. It has no filesystem, network, command-execution or device adapter. `tests/test_c014_native_uci_candidate.py` provides the only executable adapter: the extracted vendor MIPS `uci` utility under QEMU, pointed at disposable synthetic configuration copies on Hermes.

Unlike the earlier characterization fixture, these candidate tests execute the real vendor UCI parser, list/scalar updates, package commits and exports. Python is an offline development dependency, not proposed ONU firmware runtime. No synthetic success is labeled hardware qualification.

## Transition rules

- Accept only an explicit integer: zero for untagged management or 1 through 4094 for a tagged candidate. Invalid input is refused, never silently converted to untagged configuration. Existing VLAN 4095 requires separate qualification and is refused here.
- Check the complete source revision, expected LCT parent, static IPv4 profile, and the unique requested management zone. Zone selection uses its actual name and LCT membership, not array position. Membership in multiple zones is refused.
- Preserve the exact saved IPv4 address, netmask, gateway and DNS representation. In particular, do not silently remove a legacy self-address gateway. DNS/gateway absence stays absent. IPv6 and unknown LCT options are explicitly unqualified rather than silently moved.
- Create only the named `mgmt` interface and `lct_vlan` device, each with a versioned ownership marker. A pre-existing unmarked, partially marked, mismatched or externally referenced interface is not automatically adopted or deleted. The marker is a development ownership convention, not an authentication boundary against privileged modification.
- On a return to untagged management, restore addressing to LCT and remove only those verified candidate-owned objects and their management-zone membership. Unrelated interfaces, rules, zone policies, and the existing LAN membership are preserved. Both scalar and list membership forms are retained.
- Repeating an unchanged requested state produces no mutation plan. Changing one tagged VLAN to another changes only the owned VLAN-ID option.
- Check every native mutation and each package commit. Reject a stale candidate or any readback mismatch. There is no service restart, network reload, watchdog or live promotion method.

## Critical native UCI finding

The first version of the test adapter used `-P` for every command. On this extracted vendor UCI, `-P` selects a private delta save directory **and disables file commits**. Thus `commit` can return zero while a delta-aware export shows new values but the underlying configuration file still contains the old values. A copied candidate correctly failed the revision check, exposing the test-adapter mistake before publication.

The corrected adapter stages mutations with `-P`, invokes the commit process with `-p` to read the private changes without suppressing the commit, and immediately checks a new process using an empty delta directory. Only after cold readback matches does the adapter discard its own temporary delta copy. A regression test explicitly preserves the zero-exit/nonpersisted behavior of `-P` as a negative case.

The vendor utility also searches its default delta location. Test packages have unpredictable per-test names rather than actual `network` or `firewall` names, and the adapter refuses any matching default-directory entry before and after a command. All configuration and explicit delta writes remain in the disposable fixture; no actual host or device package is referenced.

The upstream behavior is documented in OpenWrt's `uci/cli.c`: the `case 'P'` branch sets `CLI_FLAG_NOCOMMIT`. The separate `-t` save-directory option was added in the April 12, 2021 OpenWrt development patch; it is not listed by this older extracted vendor utility. The tests use the observed vendor behavior, not assumptions about a newer CLI.

## What failure recovery means here

The source configuration files are retained byte-for-byte and never targeted by mutations. A failed step may leave a **partial candidate**, which must be discarded. This is not an atomic two-package transaction on a running router. Even successfully committed candidate files are not copied into live configuration and do not prove that netifd, the switch, the host router or the firewall would preserve management access.

Round-trip tests demonstrate configuration semantics, including untagged-to-tagged-to-untagged and tagged-to-tagged paths. They are not cold-boot, power-loss, live reachability or ISP-forwarding tests. The earlier C-013 journal and S-016 protected backups are not silently promoted into a working on-device recovery system.

## Verification

The focused suite contains 24 tests. Native tests include failures at every mutation and both package commits in both transition directions, stale revision refusal, post-commit mismatch refusal, copied-candidate round trips, default-route/DNS preservation, scalar/list zone membership and refusal of unowned interfaces. Every native test checks that its retained source configuration bytes are unchanged.

```sh
AOTT_VENDOR_ROOTFS=/path/to/private/extracted/vendor/rootfs \
  python3 -m unittest discover -s tests -p 'test_c014_native_uci_candidate.py' -v
```

Native tests skip when the private vendor executable and QEMU are unavailable; pure source tests still run. Firmware binaries, actual subscriber configuration and production keys are not included in the repository.

## Native-language follow-up

The [Lua-native transition core](C-014-NATIVE-LUA-TRANSITION.md) now implements bounded export parsing, private reviewed plans and checked execution in the vendor's Lua 5.1 runtime. Its test fixture calls the real vendor UCI executable and independently checks persisted candidate files. This removes Python from the candidate planning/execution path, but does not install a production staging adapter, enable the hidden control or supply live rollback.

## Still needed before a usable VLAN control

Verify the physical device's actual persistence mode, LCT parent, host-side VLAN path, zone mapping and native startup ordering. Resolve any legacy/unmarked management configuration through an explicit migration, not automatic deletion. Build and qualify a native on-device adapter, independent rollback, alternate management access and safe activation/confirmation sequence. Only after physical SSH/HTTPS and subscriber-forwarding acceptance should the GUI control be enabled.

No live ONU, ISP identity, current management route, HTTPS service, firmware bank or boot selector was read or changed by this work.

## Completed validation checkpoint

After independently issued target approval, the pinned combined host/vendor-MIPS/Chromium regression passed **880 tests, zero skips and zero failures**. The 24 focused candidate tests and browser tests are included in that total. The runner verified every tracked file and executable mode against the pinned commit both before and after the tests. Its receipt and log hash were independently reread and matched after process completion.

- Tested source commit: `f6304ba7ee4c4583bf554602f3ffe5dbde88e42b`
- Tested source tree: `2cb18f44b6b5d47e10c90c692a6af71cff014cbe`
- Full regression log SHA-256: `a2b87918836015bc994bd78418789b6441bd0e6e0ee07500639c8c18c9c079e2`
- Process exit code: 0; timeout: false.

Publication changes only this validation receipt after the pinned run; the candidate implementation, tests, firmware overlay and all other tracked source remain byte-identical to the tested commit. Source disclosure and manifest scans pass with 83 unchanged overlay entries. No deployment, service reload, live VLAN transition or firmware-bank action was authorized or performed.

The earlier H-026 intermittent concurrent-reader observation remains documented in the characterization checkpoint. This clean regression does not establish that the intermittent issue is fixed.
