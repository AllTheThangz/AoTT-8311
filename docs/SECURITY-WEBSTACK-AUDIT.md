# Vendor web stack security review

This document records a read-only inventory of the web-service components in
the AoTT-8311-v2r1 extracted firmware. It is not a CVE exploit test and does
not claim that an OpenWrt upstream release can be flashed on this ONU.

## Inventory and build compatibility

| Component | Extracted artifact | SHA-256 |
| --- | --- | --- |
| uhttpd | MIPS32r2 big-endian PIE, 63,684 bytes | 23a2430ff1ab8a88741254730dd35bb7342829fe27817c9a663f4e14cd9587ce |
| rpcd | MIPS executable, 63,396 bytes | 776494a0e03e03a09fc21cdd3aa4cd161b57398e7127c644869653e7892a9708 |
| cgi-io | MIPS executable, 23,244 bytes | 7fdb9b6c93a74109f00fa1f532b479b761267bd21ab57522190a0e429fa54a69 |
| uhttpd_ubus.so | vendor-compatible module, 14,820 bytes | ccdf10f225db5aa5a181060a9a3b980aaf45fb4424d1f918554d43e9260df02a |
| uhttpd_lua.so | vendor-compatible module, 10,132 bytes | 2891e6dcc4250e74832e0aa6cd602a22a0a9898423c397af773a4e78b0a75238 |
| libmbedtls.so.3.6.7 | Mbed TLS shared library, 317,496 bytes | 5fdf119610cf396ccbe3fe1c736bda8026ec14f5a0df7cd1c05e1a0483b0c2a0 |

All bytes were read from the offline image tree, not downloaded from the
public GitHub repository or scraped from a running system. Compiler flags,
uhttpd upstream revision and binary provenance remain unverified.

## Security advisories under review

OpenWrt 25.12.6 was published on October 18, 2026. It includes fixes for
unauthenticated uhttpd issues, including HTTP header exhaustion,
POST /ubus/call/ type confusion, URL-path leaks, request smuggling, client
reference exhaustion, and Lua/ucode realm enforcement. That release also
addresses rpcd privilege escalation and malformed cgi-io POST handling.

Source: https://openwrt.org/releases/25.12/notes-25.12.6

**Applicability is unknown** until the shipped vendor code and its
patch-level can be independently matched against the advisories. File
timestamps and the presence of Mbed TLS 3.6.7 are not proof that all
web-service fixes are included.

Do not run malformed-request denial of service, memory exhaustion, or
privilege-escalation probes against a production ONU to infer patch status.
Favor source/patch review, reproducible vendor builds, isolated QEMU or
hardware development instances, and versioned component attestations.

## Mitigation priorities

1. Restrict SSH, uhttpd and ubus to a trusted management network using a
   tested firewall and recovery path, rather than relying on a login page.
2. Require a unique root password, verify saved and running credentials,
   and use pinned-key SSH for recovery.
3. Keep HTTP-to-HTTPS redirection and a securely scoped HTTPS listener.
4. Audit Lua controller permission checks, UBUS auth/session behavior and
   file-upload routes before shipping additional web operations.
5. Pin the source revision and binary SHA for each server component.
6. Port security fixes against the vendor-compatible ABI in an offline
   build. Run protocol-specific tests on a nonproduction target.
7. Requalify the exact firmware image, partition sizes, WAN behavior, and
   both banks before live deployment.

## Outstanding acceptance criteria

- Establish uhttpd/rpcd/cgi-io source provenance and patch-level.
- Decide for each upstream advisory: affected, not affected, or unresolved
  with a reason supported by tested source or binary behavior.
- Validate management ACLs and the HTTPS/SSH recovery route.
- Verify all CI checks, then qualify the resulting image on a separate
  staging environment prior to release.

The source branch does not contain patched vendor binaries and has not
changed any live management listener or service setting.
