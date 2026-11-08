# AoTT-8311 V3r1 RC3 qualification

**Pinned source:** `release/v3r1-rc3`  
**Source commit:** `00c6d096a4051a20de80e0fcfe7dc39f257f56ef`  
**Release identity:** `AoTT-8311-v3r1`

RC3 adds the V3 first-authenticated-GUI-login password advisory while retaining the public residential-device credential policy.

## Credential and first-login behavior

- Public V3 defaults to `root/root` when no valid saved administrator credential exists.
- Factory `root/root` is valid for development and deployment and does not block staging, trial, commit, or normal operation.
- A supported custom password, when present, is preserved across upgrades and restored at boot.
- While factory `root/root` is active, the first authenticated root GUI session presents a modal with:
  - **Change password now**, which opens LuCI's existing Root password page.
  - **Keep root/root**, which stores a root-owned private acknowledgement under the existing persistent AoTT configuration area.
- Acknowledgement is device-side rather than browser-local.
- The prompt is suppressed on the password page itself.
- If the password changes, the prompt stops automatically.
- If the user neither changes nor acknowledges, the prompt returns on later authenticated pages.

## Source and runtime qualification

The exact RC3 tree passed:

- **1,224** complete source/regression tests with zero failures or errors.
- **41** deployment-sensitive vendor-MIPS tests with zero failures.
- **134** real Chromium/Playwright tests with zero failures.
- Source identity and disclosure verification with **126 overlay files**.
- Exact remote-tree verification after GitHub publication.

The vendor-MIPS qualification includes local history, management preflight, TLS runtime and activation, credential handling, and the first-login prompt state/acknowledgement model.

## Reproducible firmware pair

Two independent private RC3 builds are byte-identical.

- Rootfs bytes: **5,779,456**
- Fixed rootfs bank capacity: **6,221,824**
- Rootfs headroom: **442,368 bytes**
- Runtime integrity pins: **221**
- New candidate pins relative to the enhanced-r8 base: **76**
- Rootfs SHA-256: `42825f13e32fb38d24c668befced9ef87823af1c156fcb46698a9fdd9a200bde`
- Upgrade archive bytes: **13,506,560**
- Upgrade archive SHA-256: `dcc2378edc21408517fd17302135e00716c89468cf40a29d05f1c40b808f31a8`

The independent audit status is `PRIVATE_INDEPENDENT_RELEASE_PAIR_REPRODUCIBLE`. Hardware boot qualification remains pending.

## Reference-unit read-only pre-stage state

The unchanged PRX126 reference unit currently verifies:

- running firmware: committed AoTT-8311-v2r9;
- active bank A;
- committed bank A;
- no pending one-shot activation;
- bank A valid and complete;
- bank B valid and complete enhanced-r8 recovery;
- PON state O5.1;
- host Ethernet 10 Gbps;
- HTTPS responding normally;
- pinned public-key SSH recovery working;
- factory `root/root` credential recognized as valid under RC3 policy;
- fresh full-bank backups remain valid because both live bank component receipts still match the backed-up state exactly.

The RC3 read-only pre-stage checker therefore returns `can_stage: true`, while separately retaining:

- `stage_authorized: false`
- `trial_authorized: false`
- `commit_authorized: false`

No RC3 bank write, boot-selector change, reboot, trial, or commit occurred during this qualification.

## Next hardware gate

The first mutating step is an explicitly authorized **stage-only** installation into inactive bank B. That action must preserve committed r9 in bank A, must not set a one-shot boot selector, must not reboot, and must not commit RC3.

After stage-only verification succeeds, one-shot trial and permanent commit remain separately authorized operations.
