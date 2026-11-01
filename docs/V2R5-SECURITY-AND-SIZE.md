# v2r5 security and runtime-size evidence

## Status and constraints

The new revision is an offline development candidate. The last hardware
committed version is v2r4. This document contains no customer network
identifiers, private binary digests, device captures, passwords or keys.

## Already optimized in v2r4

The qualified v2r4 rootfs contains none of the 47 previously audited
runtime-lean removal paths. These included DSL/wireless-only widgets,
Nano, OMCI simulation/stress tools, optional MTR and serial-transfer tools,
Zstandard commands and their proven orphaned libraries.

The runtime profile protects OMCI, PON, the dual-bank controls, full MIB
selection, required cryptography, SSH/HTTPS, RARP packet capture and
vendor recovery behavior. A new binary should not be removed merely because
it is idle during one device snapshot. Duplicate SquashFS content already
benefits from image-level deduplication.

## Security component decisions

| Component | Review outcome | v2r5 plan |
| --- | --- | --- |
| uhttpd | v2r4 already contains a locally hardened MIPS build | Retain validated binary |
| rpcd and file.so | Independently rebuilt from reviewed source, byte-for-byte match with v2r4 | Retain existing binaries |
| cgi-io | New upstream source includes malformed POST-field decode safeguards | Rebuild and validate offline |
| Mbed TLS | v2r4 has Mbed TLS 3.6.7 library | Retain |
| OpenSSL libcrypto.so.1.1 | Proprietary OMCI has a direct runtime dependency; observed version string is OpenSSL 1.1.1w | Retain, track legacy-security risk |
| OpenSSL libssl.so.1.1 | Direct consumers were not observed, but late loads and vendor modes are unqualified | Retain, investigate compatible security maintenance |

OpenSSL 1.1.1 reached public end of life on September 11, 2023.
The existing vendor-provided 1.1.1w does not receive public upstream
security maintenance. Third-party/premium-support variants may differ.
Neither the old version string nor the presence of a shared library proves
a specific network-reachable vulnerability in this ONU. Do not substitute
an ABI-incompatible OpenSSL major version or remove libcrypto: OMCI uses it.
Before proposing a future library update, establish exact vendor-linked
symbols, supported late-loading modes, a reproducible compatible MIPS build,
and isolated PON registration and recovery checks.

Reference: https://openssl-corporation.org/blog/2023-09-11-eol-111.html
| Vendor kernel/bootcore | Secondary CPU startup remains unresolved | No speculative kernel changes |

The October 18, 2026 OpenWrt 25.12.6 release documents important web,
RPC, CGI and TLS fixes. Its package versions cannot be flashed directly
onto this vendor PRX126 image. Binary provenance and patch compatibility
must be checked individually.

Reference: https://openwrt.org/releases/25.12/notes-25.12.6

## Local independent binary qualification

The CGI source includes the upstream postdecode guard: return a bad-request
response when POST data cannot be decoded, and clear pointers into freed
form-data storage before returning. The reviewed source also includes
path-canonicalization checks on file download and exec paths.

Two isolated MIPS32r2 build directories are used to compare complete,
stripped executable digests. Offline QEMU tests exercise three CGI applets with malformed percent
escapes, missing or invalid form lengths, truncated input, absent credentials
and invalid content types. All 36 isolated test cases passed. Tests never
call the production ONU.

Full security coverage still requires system integration, runtime ABI checks
and specific tests of real authenticated LuCI and ubus behavior. Synthetic
test success does not establish an upstream advisory as fixed unless the
relevant code path and configuration are actually present.

## Compression and flash allocation

Rootfs A and B each have a fixed logical volume capacity of 6,221,824 bytes.
Headroom must be measured from the actual compiled, aligned SquashFS bytes,
not the 128 MiB NAND headline size or writable overlay free space.
Increasing rootfs partition geometry needs independent bootloader and
fallback qualification, not a production tweak.

Do not shrink reserved DMA/CMA RAM or try to start offline Linux CPUs to
increase apparent resource utilization. PON throughput is provisioned by
the OLT and dedicated network datapath.

## Release gate

An offline build may be called qualified only after the full manifest,
compiled binary provenance, runtime profile, reproducible filesystem,
capacity, dependency and archive checks pass. No production flash, trial
boot or commit is authorized by offline development alone.
