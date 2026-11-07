# AoTT-8311 V3 deployment foundation

AoTT-8311 v3 is promoted from the privately hardware-qualified v2r9 release candidate.

The V3 branch keeps the proven r9 PON/OMCI, 10G host link, management routing,
A/B recovery and bank geometry as its compatibility baseline. The major-version
change integrates the previously isolated configuration, history, certificate,
security and compatibility work into one deployment line.

## First integration cut

- Product identity is AoTT-8311-v3 r1.
- The r9 A/B recovery and guarded firmware lifecycle remain unchanged.
- The tested bounded history model, sampler, aggregation/export, preference and
  authenticated handoff primitives are included in the firmware overlay.
- An opt-in local-history lifecycle is integrated: a single low-priority foreground worker, disabled by default, samples PON and host Ethernet independently into bounded RAM and publishes only through verified owner/publication locks. Persistent history remains disabled pending durability qualification.
- A V3 status page and authenticated JSON endpoint distinguish installed,
  activated and hardware-qualified capabilities.
- Remote GUI exposure remains disabled by default.

## Deployment gates

V3 does not replace committed r9 until the current administrator password has been changed from the known factory default and its hash persistence has been verified on r9. The V3 installer adds an automatic credential-preservation gate for subsequent upgrades. See [credential preservation](V3-CREDENTIAL-PRESERVATION.md).

V3 does not replace committed r9 until the exact built image passes full source
regression, reproducible build pair, image-size/headroom validation, read-only
hardware preflight, configuration persistence/recovery checks, authenticated GUI
audit, bounded history resource testing, TLS/security checks, a one-shot
inactive-bank trial, and independent postboot PON/10G/management/bank verification.

Committed r9 remains the recovery reference during initial V3 qualification. See [V3 local history runtime qualification](V3-HISTORY-RUNTIME-QUALIFICATION.md) for the opt-in worker design and resource reference, [V3 management preflight qualification](V3-MANAGEMENT-PREFLIGHT-QUALIFICATION.md) for read-only /ptconf, native-source, and live UCI topology evidence, and [V3 TLS candidate qualification](V3-TLS-CANDIDATE-QUALIFICATION.md) for private-key hardening, local candidate generation, guarded self-signed activation, and the remaining operator-import boundary.
