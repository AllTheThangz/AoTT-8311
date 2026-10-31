# Evaluation of newer 8311 community forks

## Candidate baselines and current result

The original djGrrr 8311 v2.8.3 community firmware was published
September 19, 2025. The Potron PTXG_CX_V0.03 foundation remains the
working PRX126 hardware and PON/OMCI base for AoTT-8311.

HikaruChang released 2.8.3-CN5 on October 14, 2026, continuing
the xiao-k233 branch and merging upstream 2.8.3. The maintainer
reports improvements in CPU usage, OMCI stability, crash recovery,
log volume and trial-boot rollback. These claims require separate
validation on AoTT and on each specific OLT.

The brudalevante 2026 fork adds shell linting, build automation and
tests that may be useful as CI references. It does not demonstrate
a new PON driver or validated more recent kernel for this board.

## Findings against AoTT-8311-v2r1

| CN5 change | AoTT v2r1 finding | Action |
| --- | --- | --- |
| OMCI signed millisecond timer overflow fix | Exact patched omcid SHA-256 matches our extracted v2r1 file | Already present in firmware, do not repatch |
| OMCI crash supervisor with bounded reboot | No standalone equivalent script in the examined AoTT rootfs | Design review before integration |
| Trial connectivity watchdog | No same-named script; AoTT already has guarded A/B trial and explicit commit logic | Reconcile contracts first |
| Reduce repetitive ping logging | v2r1 firmware logs each loop; v2r1.1 development source now logs target changes only | Source-only regression tests added; not installed on live device |
| Reduce RX_LOS process overhead | v2r1 forks a cat process per pass; v2r1.1 development source uses shell builtin read | Offline GPIO-fixture tests added; not installed on live device |
| Reduce VLAN daemon CPU load | AoTT daemon uses custom hook and detect-config logic | Do not replace wholesale; compare behavior and tests |
| Remote syslog configuration | Not yet integrated in AoTT image | Consider optional monitoring integration |
| Reported CPU load from 16.6% to 6.8% | Maintainer benchmark, not measured on our stick | Treat as hypothesis, not expected target |

The extracted AoTT v2r1 omcid has SHA-256:

    4bed8e6a43ed693da8382d3c128cece3b3eac66664452875f291b25df04eb2d6

The CN5 binary modifications script uses the same hash as its expected
patched omcid output. This is a content match, not proof that every CN5
feature or its crash supervisor was shipped with AoTT.

## Safety constraints for selective porting

- Avoid copying complete firmware images or binary patches across
  different vendor versions without exact input hash and ABI checks.
- OMCI restart and reboot policies affect real Internet availability
  and may conflict with our A/B trial and commit policy.
- Preserve PON identity, calibration, GEM/T-CONT mappings, VLAN
  behavior, and provider authentication settings.
- Measure background shell process count and CPU wakeups before and
  after any daemon modifications.
- Do not merge unreviewed binary modifications or source code whose
  redistribution rights cannot be established.
- Commit source-only changes to the PR. Do not flash or reboot the
  production ONU during this evaluation.

## Sources

- https://github.com/djGrrr/8311-was-110-firmware-builder/releases/tag/v2.8.3
- https://github.com/HikaruChang/8311-was-110-firmware-builder/releases/tag/2.8.3-CN5
- https://github.com/HikaruChang/8311-was-110-firmware-builder/blob/master/mods/binary-mods.sh
- https://github.com/brudalevante/8311-was-110-firmware

This is source repository documentation, never an on-device file.
