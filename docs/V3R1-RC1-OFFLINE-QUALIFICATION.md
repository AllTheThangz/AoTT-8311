# AoTT-8311 V3r1 RC1 offline qualification

**Candidate source:** `f3e3bbf3029a21ea9c6d8e3ec24cda10e92a1966`  
**Pinned source branch:** `release/v3r1-rc1`  
**Release identity:** `AoTT-8311-v3r1`  
**Hardware profile:** `potron-prx126-aott-v1`

This record covers the integrated V3r1 release candidate before any live firmware installation. No firmware bank, boot selector, trial state, or committed selector was changed while producing this qualification.

## Source and browser qualification

The exact candidate source passed:

- release identity verification;
- source disclosure and manifest verification with 125 overlay entries;
- 1,217 source/regression tests with zero failures or errors;
- 131 real Chromium/Playwright browser tests with zero failures;
- vendor-MIPS targeted qualification for the new V3 runtime paths.

Environment-dependent tests that were not part of the generic source run were executed separately against the private extracted PRX126 vendor runtime.

## Vendor-MIPS V3 qualification

The following V3-specific suites passed under the extracted target runtime:

| Area | Result |
| --- | ---: |
| Local history runtime and production dual-lock snapshot path | 8 / 8 |
| Management VLAN preflight | 5 / 5 |
| TLS candidate generation and key hardening | 7 / 7 |
| Guarded TLS activation and rollback | 9 / 9 |
| Root-credential deployment guard and persistence ordering | 6 / 6 |

The history service remains opt-in, RAM-first and without automatic respawn. Management VLAN remains preview-only; there is no production apply route. TLS activation remains guarded by HTTPS/root authentication, persistent pending state and rollback. Operator-owned certificate import remains outside this candidate activation path.

## Reproducible private build pair

Two independent offline builds from the exact candidate source produced byte-identical SquashFS images and upgrade archives.

- Rootfs image extent: **5,779,456 bytes**
- Fixed rootfs volume: **6,221,824 bytes**
- Flash headroom: **442,368 bytes**
- Mandatory minimum headroom: **65,536 bytes**
- Preferred headroom: **524,288 bytes**, not met
- Runtime integrity records: **220**
- New candidate runtime pins relative to the pinned enhanced-r8 base: **75**
- Rootfs SHA-256: `6537266a945c2432926756e6c38dfdf80fda6a50d5190c37b8477944ead9eb4d`
- Upgrade archive bytes: **13,506,560**
- Upgrade archive SHA-256: `ecf718e55ea9e1e44899fafda4ac94d771eeec0d1076158c44346d5c7f7cce32`

The independent pair audit status is `PRIVATE_INDEPENDENT_RELEASE_PAIR_REPRODUCIBLE`. The image remains **not hardware-qualified** and **not safe for live installation** until an authorized inactive-bank trial completes.

## Reference-unit pre-stage state

A read-only check of the reference PRX126 confirmed:

- committed r9 remains active in bank A;
- no one-shot trial is pending;
- enhanced r8 remains complete and valid in bank B;
- both banks have complete kernel, bootcore and rootfs receipts;
- no V3 image has been written to either bank.

The V3 credential deployment gate also confirmed that the reference r9 unit still uses the known factory root credential. Therefore the first r9-to-V3 stage is blocked until the administrator explicitly changes it to a unique password, verifies SSH/HTTPS access, persists the resulting hash with the existing r9 helper, and verifies durable credential status.

A generic instruction to continue does not authorize changing the password, writing a firmware bank, changing boot selectors, rebooting, trialing, or committing firmware.

## Remaining hardware gate

After credential readiness is separately established, V3r1 RC1 still requires independent authorization for each stage:

1. refresh and verify off-device full-bank recovery backups;
2. perform stage-only installation into the inactive bank;
3. verify target-bank image hashes and receipts without reboot;
4. separately authorize a one-shot trial;
5. verify PON O5.1, 10 Gbps host link, HTTPS/SSH, local History behavior, management preflight and TLS recovery behavior;
6. separately authorize permanent commit only after post-trial acceptance.

The current committed r9 bank remains the recovery baseline until those gates are complete.
