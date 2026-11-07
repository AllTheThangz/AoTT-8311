# V3 management VLAN preflight qualification

**Status:** read/preview integrated, production write gated. No management setting, recovery file, firmware bank, boot selector, or service was changed on the production reference unit.

AoTT-8311 V3r1 now includes a read-only management VLAN preflight path. It combines the existing C-014 native management reader, recovery-storage admission contract, and validated UCI VLAN transition planner behind an authenticated administrator page. The page can show whether the recovery prerequisites are present and can generate a redacted change count for VLAN 0 through 4094. It contains no production apply route.

## Runtime boundary

The installed V3 preflight:

- reads exactly six saved management environment keys through one locked fw_printenv snapshot;
- returns only present/unset/present-empty classifications and counts, never values;
- reads fixed network and firewall UCI exports;
- parses them through the existing bounded C-014 native Lua parser;
- validates the current topology by asking the transition planner to reproduce it with zero operations;
- previews a requested management VLAN using the existing ownership, address, trusted-zone, and foreign-reference checks;
- returns only current/requested VLAN and operation counts, never IP, DNS, MAC, route, or UCI values;
- verifies /ptconf mount class, write state, ancestor ownership, statvfs capacity, and the fixed recovery-store path;
- performs no mkdir, UCI commit, environment setter, network reload, reboot, firmware write, or bank change.

The existing C-014 executor remains restricted to offline_synthetic. The controller exposes management_vlan_preview but no management_vlan_apply route.

## Read-only PRX126 storage evidence

The committed r9 reference unit was inspected without writing to it.

Observed recovery-storage facts:

- /ptconf is ubifs;
- mount flags include rw,sync;
- approximately 3.18 MiB was available at the observation;
- inode accounting reports unavailable rather than a finite count;
- /ptconf and /ptconf/8311 are root-owned and not group/other writable;
- /ptconf/8311/aott-recovery/v1 does not exist yet.

This satisfies the storage-class and byte-capacity prerequisites for continued development, but not provisioning, power-loss durability, or cross-bank qualification. The production preflight correctly reports provisioning required until the fixed 0700 recovery directory is explicitly created during an authorized V3 hardware qualification.

## Read-only live topology evidence

The live r9 unit's network and firewall exports were captured privately on the administrator host, parsed by the V3 transition planner, reduced to redacted results, and deleted.

Results:

- current management topology: VLAN 0, untagged;
- replaying the current topology: zero operations;
- synthetic request to VLAN 123: 23 redacted operations;
- network operations: 20;
- firewall operations: 3;
- configuration values exposed in the receipt: none.

The synthetic VLAN 123 preview was never sent to the ONU and does not authorize that VLAN for deployment. It only proves the planner accepts the actual current UCI structure and can construct a bounded transition from it.

## Read-only native source evidence

The same reference unit's six saved management keys were queried in one locked native environment read and reduced immediately to state classifications:

- present values: 3;
- unset values: 3;
- present-empty values: 0.

No values were emitted or retained in the qualification receipt. The absence of present-empty values means the known wrapper limitation for reconstructing an explicitly empty native value is not active on this reference unit at the observation time.

## Remaining production-write gates

Management VLAN apply remains blocked until all of these are complete:

1. Provision the fixed /ptconf/8311/aott-recovery/v1 directory with root ownership and mode 0700 during an explicitly authorized V3 hardware qualification.
2. Add the production transaction adapter without weakening the existing offline executor or source-precedence checks.
3. Prove synchronized retained-file/journal write and exact readback on the real UBIFS store.
4. Prove automatic recovery after an intentionally unconfirmed V3 management change.
5. Prove the recovery state survives reboot and a controlled power interruption without corrupting either firmware bank or management access.
6. Prove native environment, current-boot caches, and UCI topology agree before and after the transaction.
7. Expose an authenticated apply/confirm workflow only after those checks pass.

The complete source suite at this checkpoint passes 1,194 tests with zero failures or errors; environment-dependent browser/private-runtime cases are skipped unless their dependencies are supplied. The management preflight itself passes under both host Lua 5.1 and the extracted PRX126 vendor MIPS Lua/nixio runtime.

This document authorizes no production configuration mutation.
