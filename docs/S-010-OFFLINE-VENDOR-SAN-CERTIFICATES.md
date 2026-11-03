# S-010: Offline qualification of SAN-bearing local HTTPS certificates

**Checkpoint:** November 3, 2026. **Status:** source and extracted-vendor
MIPS emulation validated only. **Not installed in the firmware.**

## Residential requirement

The ONU needs a straightforward option to generate its own HTTPS
certificate for a local management IP/hostname, or eventually load a
certificate/key pair owned by the operator. Local self-signed trust is
acceptable. No enterprise certificate authority, DNS automation, cloud
dependency, or mandatory public domain is required.

This source test addresses the **generator and certificate validation**
portion of S-010. It does **not** implement a LuCI button, saved
configuration, uhttpd service reload, backup, rollback or production
certificate rotation.

## Verified native implementation route

The extracted security-enhanced r8 vendor rootfs contains
\`/usr/sbin/px5g\` (MIPS32, dynamically linked) and uhttpd.
The rootfs does not contain an executable at \`/usr/bin/openssl\`, even
though the existing uhttpd init script checks for it. The init script
prefers px5g and generates a default self-signed certificate **without
supplying SAN extensions**.

Native px5g **does** support repeatable \`-addext\` arguments.
Using this exact extracted binary through QEMU, the source harness
generated DER certificate/private-key pairs with:

- A hostname DNS SAN, an IPv4 SAN and an IPv6 SAN in one certificate.
- ECDSA P-256 with SHA-256, or RSA-2048 with SHA-256.
- User-selected validity bounded to 1 through 397 days.
- A non-CA self-signed leaf certificate and a matching DER private key.
- Private-key mode 0600 in a root-owned 0700 disposable directory.

The tool independently decodes DER X.509 and validates **all** expected
SANs, private/public key equality, signature integrity, current
validity, basic constraints, and the approved key algorithm.
Certificates without SAN, mismatched keys, altered signatures,
unapproved extensions of validity, incorrect identities and weak
private-key permissions are rejected. The vendor-native generator
requires one \`-addext subjectAltName=...\` argument **per SAN**.

No full OpenSSL command-line executable was added to the shipping rootfs.
The Python \`cryptography\` library is used **only on the offline Hermes
test host** to independently verify vendor-generated material. It is
not a proposed dependency for the ONU.

## Guarded source tool and offline tests

Code: \`tools/s010_offline_vendor_tls.py\`

Tests: \`tests/test_s010_offline_vendor_tls.py\`

The tool accepts an extracted vendor rootfs and an existing private
test directory named \`/var/tmp/aott-s010-cert-test-*\`. It requires
root ownership, a directory mode of 0700 and no directory symlinks.
It executes the vendor px5g binary through \`qemu-mips-static\`, without
a shell, network listener or service restart, and writes only new
\`candidate.crt.der\` and \`candidate.key.der\` files there. Existing
candidate names cannot be overwritten. The candidate certificate
may be mode 0644 because it is public; the key **must** be 0600.
No generated key contents appear in receipts or source files.

Example for a **separately created disposable test directory**:

\`\`\`sh
AOTT_VENDOR_ROOTFS=/path/to/extracted/vendor/rootfs \
  python3 -m unittest discover -s tests \
  -p 'test_s010_offline_vendor_tls.py' -v
\`\`\`

The tests create and remove their own root-owned disposable test
directories under \`/var/tmp\`. In CI without the offline rootfs/QEMU or
root privileges, vendor-only integration tests skip; pure source
validation remains enabled. This is **not** a test on the real ONU.

## Production release gates

1. Confirm exact supported px5g variant, ABI and rootfs dependencies on
   each actual stick profile. A source/vendor QEMU result is not a
   blanket cross-vendor compatibility claim.
2. Implement authenticated local-only UI selection of approved IP/DNS
   SANs without exposing cookies, keys or untrusted shell strings.
3. Implement key generation to a separate root-owned runtime staging
   directory with strict symlink/inode checks, entropy and bounds.
4. Verify SANs, signature, certificate/key pairing, validity, key
   permissions and uhttpd ability to **load DER** on the live device
   before activating any candidate. DER support in other tools is not
   proof of the particular uhttpd's successful TLS handshake.
5. Back up existing certificate, key, and exact config; execute an
   explicitly authorized, guarded switch with a timed rollback.
6. Verify HTTPS from the actual intended local hostname/IP in a real
   browser, and establish a second local management recovery path.
7. Confirm reboot and A/B-bank persistence, security status, TLS
   compatibility and recovery after interrupted writes.
8. Independently implement and qualify S-011 imported operator-owned
   certificate/key/chain handling. Import is **not** delivered by S-010.

**No live PRX126 management certificate, uhttpd config, firmware image,
flash device, A/B selector, ISP registration, PON traffic or router
network settings were modified.** The source evidence does not
authorize a production certificate change.
