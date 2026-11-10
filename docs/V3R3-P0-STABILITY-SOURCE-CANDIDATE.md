# AoTT-8311 V3r3 P0 stability source candidate

Status: **source work in progress, not hardware-qualified and not installed on an ONU**.
Base: V3r2 source; proposed revision: **V3r3**.
Tracking: GitHub Issues #59 and #60.

## Change and evidence matrix

| P0 ID | Implemented in this source candidate | Remaining acceptance |
|---|---|---|
| 01 History runtime directory | Use vendor-existing `/var/run/aott-history` consistently in init, locks, publication gate and fixtures; fail closed on wrong owner/mode and symlinks | Opt-in history enable, disable, restart and hours-long collection on actual target |
| 02 Canonical release identity | V3 capability module imports generated `8311.version`; no stale hard-coded revision | Check web/API/SSH/banner on staged V3r3 firmware |
| 03 Service restart policy | Four peripheral daemons use procd `respawn 300 10 5` instead of unlimited retries | Failure injection, recovery with real procd, and log-rate/availability regression |
| 04 Cross-version rootfs qualification | Add off-device read-only embedded-profile comparison with separately reviewed profile and protected common pins | Version-aware installer source path now validates independently approved candidate profile SHA-256 against protected board/common pins; field test on independent hardware remains |
| 05 Saved/effective state | Existing source transactions identified and retained | Per-field live consumer proof with test record |
| 06 LuCI workflows | Existing browser fixtures retained; no runtime view rewrite | Full authenticated browser/device matrix including previously failing actions |
| 07 API security | Added source checks for authenticated CSRF protection across 16 write routes, plus private staged-file creation | Authenticated device browser, CSRF and concurrency/flood tests |
| 08 Boot sequencing | No changes to vendor boot/PON/init order | Cold start and failure injection evidence |
| 09 Config transaction consistency | Existing guarded writers preserved | Interrupted-save, stale revision, real consumer, multi-client tests |
| 10 Clock correctness | Soak collector records UTC host time and device monotonic uptime separately | NTP jump/outage reconstruction and device-history hardware tests |
| 11 UBI/thermal/resource safety | Read-only soak collector with thermal and available memory; no device writes | UBI health/wear sampling and bounded fault testing |
| 12 Soak reliability | Read-only private off-device JSONL collector with explicit probe gaps, reboot and transition counts | 24-hour and 7-day completed runs, reports and acceptance |
| 13 Release integrity | New source-only release identity, source tests and profile preflight | Two independent identical complete firmware builds and compatibility/negative-image checks |
| 14 Privacy/support | TLS private keys and sensitive write payloads now begin in root-only mode 0600; symlinks and changed destinations are refused | Device end-to-end security, support bundle redaction and negative fixture proof |
| 15 Resource limits | Shared write helper rejects inputs above 1 MiB; all staged writes use exclusive creation and size/mode verification | Concurrent management load, memory/CPU/timeout testing and truthful error display |

**P0 is not complete until the remaining hardware and long-duration acceptance criteria are met.** No upgrade, reboot, service restart, credential change, or production configuration change is included in this source patch.

## First fixed defects

### History runtime path

The vendor live PRX126 image provides `/var/run`, not `/run`. The optional history worker previously used `/run/aott-history`; this now uses the existing volatile path. The init code rejects a symlink, incorrect ownership/mode, or missing parent. Production-path tests are kept in sync. The history feature remains disabled by default.

### Release metadata

The V3 status source previously reported revision r1 independently of the generated release identity. It now reads `require "8311.version"` and derives the release, revision and full version. The generated V3r3 overlay release metadata is source-only and not the running V3r2 device identity.

### Bounded peripheral respawn

Previous `procd_set_param respawn 5 10 0` used 0 retries, meaning infinite restarts under OpenWrt procd. Revised peripheral scripts use a 300-second threshold, 10-second restart delay and 5 failed retries. This may reduce crash loops but can leave a daemon stopped after repeated real failures. Validate service recovery behavior on spare/independently recovered hardware before deployment. The PON core and vendor forward path are unchanged.

## P0-04: Explicitly reviewed candidate profile qualification

The V3r3 installer source now supports an optional `--expect-candidate-profile-sha` argument to a guarded, exact-bank installation. It rejects malformed hashes and rejects use without `--expect-active`, `--expect-target` and a fresh `--expect-state-guard`. After mounting the newly written inactive-bank rootfs read-only, it checks that the embedded profile has the separately approved exact SHA-256, retains all protected board/target/variant/kernel/bootcore/common records from the trusted running profile, keeps previously required candidate file paths, and verifies the actual filesystem bytes before completing the bank receipt. Without the new flag the original running-profile requirement remains strict.

**Compatibility caveat:** this capability is source-only in V3r3. It does not exist in the already running V3r2 installer, so it cannot silently authorize a V3r2-to-V3r3 upgrade. Any such future stage requires an independently reviewed compatible deployment method and separate device-write approval. The optional flag is not sufficient as a trust source by itself: the operator must obtain the reviewed hash from an independent build/review, not merely copy a claim from a downloaded firmware archive.

Source-only negative tests cover wrong reviewed hash, protected-board mismatch, duplicate and removed records, symlink and corrupted file contents. A real board installation and uninterrupted service observation remain outstanding.

## P0-07 / P0-14 / P0-15: Private atomic configuration writes

Shared `8311.webutil.write` no longer uses a create-write-then-chmod path that could expose newly created TLS private keys or other sensitive files at a more permissive umask. Instead, every file is staged under a random same-directory name using exclusive creation at mode 0600, then checked for root ownership, link count, exact length and mode. The requested final mode (0600, 0644 or 0755) is applied only to the fully written staging file; a subsequent atomic rename replaces the target. Existing destinations must be regular root-owned single-link files and must not change identity during staging. Failed replacement leaves the original data in place, and failure paths clean up the temporary file. The helper rejects oversized (>1 MiB), malformed, non-absolute and parent-traversing paths.

Vendor-MIPS regression fixture `tests/p0_webutil_write_fixture.lua` validates private creation, key/certificate/hook modes, complete replacement, failure injection, symlink refusal, unchanged original on failure and the 1 MiB input limit. `tests/test_p0_webutil_atomic_write.py` checks shared source invariants and authentication/CSRF guard presence on 16 mutating routes. These tests do not authorize writes or expose actual device secrets.

## Local-only tools

### Cross-version runtime-profile preflight

`tools/p0_candidate_profile_preflight.py` compares the installed profile with the separately reviewed candidate profile and the exact profile embedded in a staged SquashFS image. It rejects changes to protected common/board pins, tampered embedded profile and malformed records. It reports candidate runtime pin drift before a hardware stage, but does **not** replace device-side authorization or hardware qualification.

Example, paths deliberately generic:

```sh
python3 tools/p0_candidate_profile_preflight.py \
  --installed-profile /path/to/installed-profile \
  --reviewed-profile /path/to/reviewed-candidate-profile \
  --candidate-squashfs /path/to/reviewed-candidate.squashfs
```

### Read-only soak sampling

`tools/p0_soak_readonly.py` uses fixed bounded SSH reads and never executes device mutations. Host-side JSONL files are private and contain only uptime, optical O-state, Ethernet carrier/speed/errors/drops, temperatures and memory availability. Samples marked unavailable are not counted as confirmed outages. It does **not** claim subscriber Internet health or provide continuous event coverage.

```sh
python3 tools/p0_soak_readonly.py --target root@your-onu \
  --output /path/to/new-private-soak.jsonl --interval-seconds 60 --samples 1441
```

A 7-day 60-second series would use `--samples 10081`. Running either duration is separate work, and the capture tool's output must not be called a completed soak merely because a command was prepared.

## Source and device acceptance

Required: `python3 tools/verify_release.py .`, source and Lua/QEMU suites, source privacy gate, runnable Chromium UI scenarios, two independent reproducible rootfs/archive builds, multi-day hardware soak, per-feature hardware qualification, and explicitly authorized deployment. Release image must stay inside the fixed 6,221,824-byte rootfs bank with room for future fixes.

## Scope and risk disclosure

This V3r3 source changes the optional history runtime directory, four peripheral daemon retry policies, and status metadata. None changes PON registration data, VLAN/GEM/OMCI forwarding, optical calibration, link speed, credentials, firewall, routing, boot selection or production settings. Future stage/trial/commit must have separate authorization.
