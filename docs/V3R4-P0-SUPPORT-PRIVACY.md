# AoTT-8311 V3r4: support bundle privacy hardening

Status: **development-only candidate; not installed or hardware-qualified**. Base: the source of verified **AoTT-8311 V3r3**. V3r3 remains the running/committed firmware on the reference PRX126 ONU.

## Why this change

The previously shipped default `8311-support.sh` sanitized firmware environment values and discarded known credential-bearing log lines but could still include subscriber IP and MAC addresses in otherwise benign logs and traffic-filter captures. A large single-line diagnostic also risked excessive CPU usage during replacement.

## Source changes

- New BusyBox AWK redactor at `/usr/libexec/8311-support-redact.awk`, invoked **on every successful default-mode text diagnostic**, after command-specific redaction. Masks common IPv4, IPv6 (including scoped/CIDR notation), colon/hyphen/Cisco-form MAC, and uppercase four-letter vendor plus eight-hex-character PON serial formats.
- Drops potentially credential-bearing lines across sources, not only syslog. Firmware environment values remain redacted before generic processing. `uname -srm` omits the host node name while retaining kernel and architecture diagnostics.
- Redaction is **fail closed**. A missing privacy script, a line longer than 64 KiB, command failure during filtering, or an output-size violation cannot publish raw capture bytes as a completed bundle. The per-file sanitized output budget is 4 MiB and overall sanitized diagnostic budget is 24 MiB. Full raw captures retain the existing bounded archive gate.
- `--full` intentionally retains privileged raw output, including vendor OMCI data and environment values. It is not suitable for public sharing without a separate review.
- Pattern-based sanitization cannot ensure anonymity for unusual encodings or hostname/topology information. The support bundle README explicitly cautions reviewers.

## Verification

`tests/test_p0_support_bundle_privacy.py` exercises full in-memory BusyBox and host AWK masking; default archive creation with synthetic vendor `logread`, `fw_printenv`, and `tc` outputs; explicit full-mode bypass; missing filter; sensitive traffic-filter lines; and pathological oversized input. Test identifiers are assembled at runtime to satisfy the source disclosure gate. No tests run on the physical ONU.

## Release and acceptance

Version, release metadata, SSH banner and theme resource-cache tag have been updated to **V3r4**. Verify source/disclosure/host and browser tests, independently reproducible offline images, the preserved platform profile and the 6,221,824-byte rootfs volume headroom. This development increment does **not** change optical identity, OMCI forwarding, VLAN, interface settings, admin credentials, kernel, bootcore or live firmware. Hardware behavior must be tested separately before any approved V3r4 installation.

The actual V3r3 24-hour passive stability trial completed successfully with 1,441/1,441 one-minute samples, and the maintainer has explicitly waived a seven-day soak. The existing V3r3 hardware evidence remains valid for V3r3, **not** for new V3r4 code.
