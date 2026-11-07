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
- History collection remains inactive until the production sampler lifecycle is qualified on-device.
- A V3 status page and authenticated JSON endpoint distinguish installed,
  activated and hardware-qualified capabilities.
- Remote GUI exposure remains disabled by default.

## Deployment gates

V3 does not replace committed r9 until the exact built image passes full source
regression, reproducible build pair, image-size/headroom validation, read-only
hardware preflight, configuration persistence/recovery checks, authenticated GUI
audit, bounded history resource testing, TLS/security checks, a one-shot
inactive-bank trial, and independent postboot PON/10G/management/bank verification.

Committed r9 remains the recovery reference during initial V3 qualification.
