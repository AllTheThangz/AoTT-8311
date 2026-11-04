# S-014: TLS and private-key hardening, offline source evidence

**Checkpoint:** November 3, 2026. **Status:** IN_PROGRESS / source-only
validation. No live ONU certificate or access configuration changed.

## Residential objective

Management HTTPS should work with a root-only private key, while
showing correct, non-alarming health warnings for a certificate that is
missing a SAN, no longer valid, mismatched with its key, close to expiry,
or stored with overly broad permissions. A locally generated self-signed
certificate is acceptable for a home XGS-PON bridge; a browser must
still trust the certificate explicitly or show the expected warning.

## Extracted vendor TLS stack evidence

The extracted vendor MIPS rootfs includes:

- /usr/sbin/px5g, which can create DER certificates with DNS/IP SANs
- /usr/sbin/uhttpd, which accepts ASN.1 certificate and key files
  through -C and -K arguments
- /lib/libustream-ssl.so and the vendor's existing TLS libraries

A real Linux process running extracted vendor uhttpd under QEMU on
Hermes loopback successfully completed an HTTPS TLS handshake with an
independently generated **synthetic** self-signed certificate and an
EC P-256 private key at mode 0600. The test creates a private 0700
temporary directory, verifies the expected IP SAN in an isolated
client trust context, checks that the returned DER certificate matches
the candidate and closes the emulated uhttpd process. It does not
expose a public endpoint or open an ONU management session.

The extracted rootfs does **not** include the subscriber's live key
or certificate at the running /ptconf location. Therefore its current
file permissions, deployed certificate SAN, expiration, TLS service
or browser trust CANNOT be inferred from the extracted rootfs.
The earlier private observation of a permissive key remains a
historical concern, not a current verified live health finding.

## Source-only checks

Code: tools/s014_tls_hardening_offline.py

Tests: tests/test_s014_tls_hardening_offline.py

The source tool can read **only** fixed candidate filenames within
separately created root-owned 0700 temporary test directories matching
the dedicated S-014 offline test pattern. The certificate is allowed
mode 0600 or 0644; its private key is permitted mode 0400 or 0600,
both owned by root with group root and a single hard link. Other
permissions are refused, not silently rewritten.

The tool checks the path and inode metadata, rejects symlinks, checks
file bounds, and independently validates the certificate/private-key
relationship and intended SANs using the earlier S-011 offline host
validator. The certificate also needs an approved signing algorithm,
end-entity semantics, valid dates and a valid self-signature when
self-issued. A 30-day expiry warning is reported even if the
certificate is otherwise valid.

The diagnostic report is deliberately redacted: it carries fixed
status/warning codes and summary counts, not hostname, management IP,
raw certificate, private key, passphrase or imported customer
material. The strongest status based on a supplied synthetic
vendor-emulation receipt is expressly **not** a live hardware
certificate acceptance. A normal CLI check without such a receipt
retains the 'vendor_tls_load_not_verified' warning.

No chmod, UCI commit, certificate replacement, service restart,
firewall operation, network probe or firmware write is implemented
by this offline source tool.

## Run offline tests

~~~sh
AOTT_VENDOR_ROOTFS=/path/to/offline/vendor/rootfs \
  python3 -m unittest discover -s tests \
  -p 'test_s014_tls_hardening_offline.py' -v
~~~

The vendor-loopback integration tests require extracted MIPS binaries,
QEMU, root-owned disposable fixtures and Python TLS support. They skip
when those offline dependencies are unavailable; basic source
validation still runs. These tests cannot replace a check against
the real device.

## Production acceptance gates

1. Get explicit authorization for direct, recoverable PRX126 read-only
   assessment. Verify current bank, exact firmware hash and valid
   fallback independently before changing anything.
2. Read the actual uhttpd configured certificate/key paths, file modes,
   owner/group, link count, symlink/inode identity and real kernel
   process/HTTPS state without exposing private-key contents.
3. Verify the live certificate's SAN identity, expiration,
   certificate/key pairing and chain/trust result, distinguishing a
   self-signed trust warning from a broken TLS service.
4. Confirm the actual uhttpd instance (not just extracted QEMU) still
   works when its private key is root-only, including the service UID,
   reload behavior, IPv4/IPv6 management paths and reboot.
5. Design safe authorization, independent full backups, guarded
   certificate swap, a watchdog-controlled restore on failure and an
   alternate local management recovery route under S-016.
6. Repeat actual browser handshake tests and ISP/bridge forwarding
   no-regression checks following separately approved activation.
7. Keep optional remote GUI firewall (S-013) disabled unless separately
   authorized, and never imply web-service TLS hardening changes PON,
   GEM, VLAN bridging or provider-controlled service rates.

**S-014 remains IN_PROGRESS and not deployed.** No physical ONU key
permissions, certificate files, HTTPS service, firewall, ISP identity,
PON settings, A/B boot selector or firmware bank was changed.
