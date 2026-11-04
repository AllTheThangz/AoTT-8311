# C-014: Management VLAN startup characterization

**Checkpoint:** November 4, 2026. **Status:** IN_PROGRESS. Source behavior reproduced; repair and hardware acceptance remain open.

## Scope and evidence

The actual management-network block in `overlay/etc/uci-defaults/zzz-8311` is executed under a POSIX shell with a stateful synthetic UCI adapter. The test does not reconstruct the network algorithm in Python: it extracts and runs the repository's shell block, intercepting its UCI commands. Synthetic addresses and MAC values exist only in disposable test fixtures. Neither the real UCI service nor an ONU, firewall, network interface or boot environment is accessed.

The test is `tests/test_c014_management_vlan_path.py`. Its eight cases characterize existing behavior, including unsafe cases. A passing characterization test means the behavior was reproduced, not that the behavior is correct or the feature is ready.

## Verified source findings

1. On a fresh untagged fixture, management addressing stays on `network.lct`.
2. On a fresh tagged fixture, the script creates the `lct_vlan` 802.1Q device, names it `mgmt`, creates a static `network.mgmt` interface and removes addressing from the parent LCT interface.
3. Replaying tagged then untagged setup against retained UCI state leaves the old VLAN device, the `mgmt` interface and its firewall membership present while restoring the same management address to `lct`. This is a repeat-run/persistent-state transition gap. It is not proof that an ordinary physical reboot retains that UCI state.
4. Injecting failure into the VLAN-ID write still permits later commands to move management addressing, and a later successful command can make the block exit successfully. There is no checked multi-command transaction or independent rollback in this block.
5. Firewall assignment targets `firewall.@zone[0]` by position. Reordering synthetic zones attaches `mgmt` to the first zone even when that zone is named `wan`. This does not establish the live device's zone order or actual Internet exposure.
6. `set_8311_lct_vlan()` in `overlay/lib/8311.sh` only logs a message. The real source configuration work occurs in the UCI-defaults block, so the setter's successful exit is not evidence of runtime VLAN application.
7. The getter converts malformed/out-of-range overrides to zero. That fallback is not an explicit operator instruction to migrate management back to an untagged path.
8. The `lct_vlan` GUI control remains commented out. This change does not expose it or add a writer.

## Important uncertainty

The vendor boot script runs UCI defaults, while separate startup helpers and the persistent-root option affect the configuration lifecycle. Offline source inspection cannot establish whether the running PRX126 starts each boot from clean network UCI, inherits retained state, or requires board-specific switch/host handling. These findings are therefore not a confirmed explanation for the historically disabled control, and not permission to patch the only working management path.

## Repair and acceptance requirements

A repair must validate the requested VLAN without silently converting invalid input into a topology change, identify the management zone by verified association rather than array position, check every mutation, handle repeated/tagged-to-untagged transitions, preserve unrelated settings, and retain a recoverable previous configuration. Cleanup must remove only configuration proven to belong to this feature, not arbitrary operator-created interfaces.

Before runtime activation, verify the actual LCT parent, netifd/device representation, boot ordering, persistence mode, firewall membership and host-side VLAN path. A separately tested alternate management route and an independent rollback mechanism are required before moving the active address. Success must include real SSH/HTTPS reachability and unchanged subscriber forwarding, not just UCI values or a zero exit status.

## Reproduce

```sh
python3 -m unittest discover -s tests -p 'test_c014_management_vlan_path.py' -v
```

The eight characterization tests pass. Source disclosure and manifest verification pass with 83 unchanged overlay entries. These are source-only results. No live configuration, ISP identity, service, boot selector or firmware bank was modified.

## Validation receipt

The complete corrected host/vendor-MIPS/Chromium run passed **856 tests, zero skips and zero failures**. The browser tests are included in that total. The first combined attempt used a browser virtual environment without the host cryptography dependency; that receipt is retained separately. It also observed one existing H-026 concurrent-reader assertion failure. The isolated H-026 suite then passed, and the corrected complete suite passed without changing H-026 code. This observation does not establish that the intermittent H-026 failure is fixed; it remains a reliability follow-up.

No product or overlay code changes are included in this characterization tranche. Manifest verification still covers the same 83 overlay files.
