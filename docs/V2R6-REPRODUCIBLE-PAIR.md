# v2r6 reproducible private-build verification

## Purpose

Two builds using the same source and pinned vendor base must yield
byte-identical SquashFS images and five-member firmware archives. A private
release receipt is useful only when the source manifest, canonical release
metadata, archive members and compatibility pins agree.

The source-only tool `tools/audit_reproducible_pair.py` checks those
relationships without contacting an ONU.

## What it verifies

- Independent private qualification receipts agree exactly.
- Neither receipt asserts live-install safety or hardware qualification.
- Canonical source manifest and release metadata match the build receipts.
- Every archive has exactly five USTAR entries in the required order:
  `upgrade.sh`, `control`, `kernel.bin`, `bootcore.bin`, `rootfs.img`.
- Every entry has a pinned SHA-256, byte count, deterministic timestamp,
  owner/group and expected permission mode.
- The original fixed vendor kernel and bootcore match their qualified
  component hashes, not a new untested hardware ABI.
- Both independent rootfs images match the archive component checksum and
  the expected SquashFS superblock.
- The rootfs still fits the existing 6,221,824-byte logical flash volume
  with a minimum of 65,536 bytes of headroom.

The tool rejects unexpected tar members, symlinks, altered member bytes,
source-manifest drift and unsafe release-state flags. It also checks that
the two rootfs, archive and qualification inputs are physically distinct
regular files, refusing identical paths and hardlinked aliases presented
as independent builds. Synthetic unit tests cover these rejection cases.

## Offline-only usage

From a complete build workstation, supply paths to two independently built
images and release directories. Substitute the operator's private build
paths as appropriate.

```sh
python3 tools/audit_reproducible_pair.py \
  --source ./ \
  --qualification-a /private/build-A/qualification.json \
  --qualification-b /private/build-B/qualification.json \
  --archive-a /private/build-A/AoTT-8311-v2r6-UNTRIALED-local-upgrade.tar \
  --archive-b /private/build-B/AoTT-8311-v2r6-UNTRIALED-local-upgrade.tar \
  --rootfs-a /private/rootfs-A.img \
  --rootfs-b /private/rootfs-B.img \
  --report /private/new-build-evidence.json
```

The report path must not already exist. Do not place private firmware
archives, recovery backups, logs or unreviewed device images into GitHub.

## Security limits

An SHA-256 checksum report is not a digitally signed attestation and does
not establish that a third party published or approved the release.
Cryptographic signing would require a separately managed signing key and
verified provenance policy.

A matching offline build cannot establish real boot success, PON
registration, authenticated web operation, WAN performance, or safe
rollback. Those require a separately authorized hardware trial and
independent off-device recovery backups.
