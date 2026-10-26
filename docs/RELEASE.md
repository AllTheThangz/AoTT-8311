# AoTT-8311-v2r1 source release

Product: AoTT-8311
Version: v2
Revision: r1
Composite release: AoTT-8311-v2r1

The working device firmware has been tested separately. This GitHub staging
package deliberately differs from the executable firmware rootfs: it
contains curated text-source files and omits all proprietary binaries and
subscriber-specific data, certificates, credentials, registration IDs and
recoverable flash backups.

The current source overlay includes management pages, readable dark/light
UI, firmware-bank controls, optoelectronic telemetry and security readback
modules. It retains original upstream credits in the source.

This repository is not certified to build or flash a standalone ONU
firmware image, and it does not contain a publisher-authenticated signed
upgrade image. Source-only validation is distinct from hardware qualification.

No production infrastructure path, user hostname, router identity, private
network gateway or access token is required to review these files.
