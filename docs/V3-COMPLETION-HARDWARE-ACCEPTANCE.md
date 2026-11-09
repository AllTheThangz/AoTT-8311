# V3 completion hardware acceptance

**Date:** 2026-11-09  
**Release:** AoTT-8311-v3r1  
**Implementation tree:** `e5ac19d8938ec7cb48a9628f0e4019ae4a6d69b6`  
**Archive SHA-256:** `c1204f07b88c231251208b870de0f7dacaad303278e42be122f7139f4129ad82`  
**Rootfs SHA-256:** `3b0e20115c8e01d65feade99794e3bd90e31a98df0a6e997ce980cf968687907`  
**Trusted runtime-profile SHA-256:** `b5f97a253533e8c76c64ed01fddc1c9afb961ed7fed01b0e049da79573ea87a4`

## Final accepted state

The exact V3 completion image has completed the full guarded release lifecycle on the reference LL-XS1010 / PRX126-SFP-PON device.

Final verified bank state:

- active bank: **B**
- committed bank: **B**
- pending selector: **none**
- running trial: **false**
- bank B: complete and exact
- bank A: complete and valid r9 alternate bank
- commit reboot: **none**

The permanent commit changed only the committed-bank selector. It did not rewrite firmware and did not reboot the ONU.

## Hardware acceptance evidence

Post-commit verification passed:

- firmware identity: `AoTT-8311-v3r1`;
- exact bank-B `check-json` verification;
- PON state: **O5.1**;
- host Ethernet: **10 Gbps**;
- `omcid`: running;
- pinned-key SSH: healthy;
- HTTPS management listener: HTTP 200;
- trial-time factory `root/root` LuCI authentication: passed;
- first-login password advisory: present;
- explicit **Keep root/root** action: present;
- authenticated V3 status endpoint: HTTP 200 JSON.

Operational performance evidence captured during the accepted V3 trial:

- download: **2626 Mbps**
- upload: **2766 Mbps**
- latency: **5 ms**

This speed test was performed through the UniFi gateway and is deployment evidence, not a controlled laboratory throughput benchmark.

## Deployment qualification note

The first stage attempt failed closed after writing B because the running r9 installer compared the newer V3 rootfs against its older embedded candidate runtime pins. It left B incomplete, kept A/r9 active and committed, and changed no boot selector.

The exact V3 release profile was then supplied as volatile trusted qualification policy. A read-only candidate-scope rootfs qualification passed before corrected staging. The corrected stage re-wrote, re-read and qualified B, marked it complete, independently verified it, selected it for one-shot boot, and successfully booted V3.

The reboot command caused the controlling SSH session to outlive its 30-second client timeout, but the ONU rebooted successfully and returned on V3. Subsequent postboot checks established the accepted trial state before permanent commit.

## Recovery position

Bank A remains complete and valid with the previously committed r9 image. It is no longer the committed bank after V3 acceptance, but it remains a verified alternate bank if a future explicit switch is required.

The former enhanced-r8 B image is no longer resident on-device. Its full verified bank backup remains retained off-device.

## Scope limits

This acceptance qualifies the exact V3 completion firmware lifecycle and core runtime on the tested PRX126. It does not automatically mark every supported configuration control `FULLY_QUALIFIED`.

Still separate:

- per-control C-012 live apply/effect/restore qualification;
- C-013 reboot and power-loss persistence;
- C-014 live management-tuple mutation;
- alternative MIB/provider-profile trials;
- operator-certificate browser trust and revocation acceptance;
- external remote-firewall allow/deny packet-path proof;
- persistent-history NAND wear and power-cut qualification;
- performance and soak qualification beyond the observed gateway speed test;
- additional-stick qualification.

## Private receipts

Trial receipt digest:

`1b499882e0653144810c9b203f5c322a3849645e0223cd7288575a64bd3c43af`

Permanent-commit receipt digest:

`3dbe3fca83ff17569fa186907b7ed18330a1191de5e86c782eadbb22850050eb`
