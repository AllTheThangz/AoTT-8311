# AoTT-8311 v2r6 hardware acceptance

Status: **Privately hardware-qualified, running and committed** on one
Potron LL-XS1010 / PRX126-SFP-PON device. The public repository remains
source-only. This acceptance does not cover other ONU hardware, other OLT
configurations, or long-term uptime.

## Completed qualification

The release underwent reproducible private image and archive builds,
source disclosure checks, target MIPS32r2 shell and Lua syntax tests,
284 source regression tests, 41 real Chromium tests, 29 original
installer-safety checks, and 135 selected runtime integrity records.
Its compressed rootfs occupies 5,689,344 bytes of a 6,221,824-byte
volume, retaining 532,480 bytes (520 KiB) of flash headroom.

Two banks were independently captured at full UBI volume capacity and
verified twice, then retained privately off-device. At capture time,
bank A contained v2r4 and bank B contained committed v2r5.

The privately approved hardware sequence was:

1. Stage the exact reviewed v2r6 image into inactive bank A with no
   reboot, trial selection, or commit.
2. Verify both complete bank receipts, the full bank contents, running
   v2r5 in bank B, PON registration and management/WAN reachability.
3. Select a one-shot boot of bank A with bank B still committed and
   request exactly one reboot under separate approval.
4. Confirm that v2r6 booted from bank A as an uncommitted trial and
   that both banks, credentials, PON and WAN survived the reboot.
5. Under a further distinct approval, execute one native state-guarded
   commit of the running bank A. No flash or reboot was performed in
   the commit phase.
6. Independently confirm that bank A is active and committed, no trial
   or pending selector remains, and bank B is a complete valid v2r5
   alternative.

## Latest post-commit read-only checks

| Check | Result |
| --- | --- |
| Firmware | AoTT-8311-v2r6 |
| Active / committed | A / A |
| Pending / running trial | None / false |
| Alternative firmware | v2r5 in valid bank B |
| PON registration | O5.1 |
| Host Ethernet negotiation | 10 Gbps |
| HTTPS management and pinned WAN egress | Passed |
| Both original full-bank off-device backups | Intact |
| Kernel panic, OOM and UBI error scan | No matching messages |
| Kernel and OMCI runtime components | Original reviewed vendor ABI retained |

A subsequent read-only device sample showed roughly 386 MiB of
available Linux memory, no Ethernet rx/tx errors or drops on the
sampled host interface, and an unchanged boot identifier since the
trial boot. These are point-in-time observations, not guarantees of
service continuity or measured WAN throughput.

## Concurrency and installation safeguards

The native v2r6 bank-control operation now checks the shared
five-minute, boot-ID-bound SHA-256 bank-state fingerprint under
firmware and environment locks. The hardware commit exercised this
guarded native command and passed post-commit readbacks.

The installed v2r6 archive also contains a guarded web-install job
path that checks the expected active/target bank pair and fingerprint
before a write. Initial staging from v2r5 used that release's
independently reviewed compatible installer, not an already running
v2r6 web installer. The complete v2r6 web-install write path has
not been separately trialed on production hardware.

## Source, archive and privacy boundaries

The source release metadata and private build archives were frozen
when v2r6 was an untried offline candidate. Historical fields such as
`offline-candidate` and `UNTRIALED_OFFLINE_ONLY` document build-time
state, not the current privately verified hardware deployment. Do not
silently rewrite a deployed archive or source manifest merely to alter
its historical labels.

The GitHub source overlay excludes the actual private firmware image,
vendor firmware binaries, subscriber registration, device MAC/serial
values, credentials, site-specific addresses and raw device backups.
Public release and license decisions remain separate from successful
private hardware testing.

## Remaining limits

Long-term stability and high-load performance have not been
established by a single successful trial and post-commit period.
Additional chipset and kernel experiments require independently
recoverable hardware. Further firmware revisions require their own
offline qualification, private backups, staged trial, and distinct
commit approvals.
