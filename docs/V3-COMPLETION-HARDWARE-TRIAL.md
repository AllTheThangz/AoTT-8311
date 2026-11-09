# V3 completion hardware trial

**Date:** 2026-11-09  
**Release:** AoTT-8311-v3r1  
**Implementation tree:** `e5ac19d8938ec7cb48a9628f0e4019ae4a6d69b6`  
**Archive SHA-256:** `c1204f07b88c231251208b870de0f7dacaad303278e42be122f7139f4129ad82`  
**Rootfs SHA-256:** `3b0e20115c8e01d65feade99794e3bd90e31a98df0a6e997ce980cf968687907`  
**Trusted runtime-profile SHA-256:** `b5f97a253533e8c76c64ed01fddc1c9afb961ed7fed01b0e049da79573ea87a4`

## Result

The exact V3 completion image was staged into inactive bank B and one-shot trial booted on the reference LL-XS1010 / PRX126-SFP-PON device.

Final accepted pre-commit state:

- active bank: **B**
- committed bank: **A**
- running trial: **true**
- pending selector: **none**
- permanent V3 commit: **not authorized and not performed**
- bank A remains the committed r9 rollback bank

## Deployment qualification event

The first stage attempt wrote the candidate to B but the live r9 installer rejected it during mandatory post-write runtime qualification because r9's embedded candidate pin set predates the V3 completion files. The installer behaved safely:

- B remained marked incomplete;
- A/r9 remained active and committed;
- no trial selector was written;
- no reboot occurred.

The exact V3 `/lib/8311-release-profile` was then supplied in a volatile trusted qualification directory. Its SHA-256 was verified before use. A read-only candidate-scope mount/hash qualification of the already-written B rootfs passed. The corrected stage then re-wrote and re-read B under the same guarded installer while using the exact V3 pin policy, after which B was marked complete and independently verified before trial selection.

## Postboot acceptance

The one-shot trial boot returned successfully on V3r1. Verified evidence:

- firmware identity: `AoTT-8311-v3r1`;
- bank B complete and postboot `check-json B` verified;
- bank A/r9 still committed;
- PON state: **O5.1**;
- host Ethernet: **10 Gbps**;
- `omcid`: running;
- pinned-key SSH: reachable;
- HTTPS management listener: reachable;
- unauthenticated LuCI routes return the expected login-required response;
- factory `root/root` LuCI authentication succeeds;
- authenticated Overview returns HTTP 200;
- first-login password advisory is present;
- **Keep root/root** action is present;
- authenticated V3 status endpoint returns HTTP 200 JSON.

The first unauthenticated LuCI request immediately after boot exceeded an 8-second probe window. Subsequent requests completed normally in roughly four seconds and the authenticated GUI validation passed, so this was treated as first-request/cache warmup rather than a failed GUI path.

## Recovery position

The authorized V3 stage consumed the previous bank-B enhanced-r8 recovery image. That exact r8 bank was previously captured in the verified full-bank off-device backup set. The live on-device recovery bank during the V3 trial is now committed r9 in bank A.

## Scope limits

This trial proves the exact V3 completion image boots and operates on the tested PRX126 with the core management and PON path healthy. It does not by itself mark every configuration field `FULLY_QUALIFIED`. Still open include:

- bounded live C-012 setting apply/effect/restore testing;
- C-013 reboot/power-loss persistence;
- C-014 live management-tuple mutation;
- alternative MIB/provider-profile trials;
- operator-certificate browser trust/revocation acceptance;
- external remote-firewall allow/deny packet-path proof;
- persistent-history wear/power-cut qualification;
- performance/soak measurement;
- additional-stick qualification;
- permanent V3 commit.

## Private receipt

The private operator receipt is retained off-repository. Public documentation records only its digest:

`1b499882e0653144810c9b203f5c322a3849645e0223cd7288575a64bd3c43af`
