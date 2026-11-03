# S-011: Offline validation of operator-supplied HTTPS certificates

**Checkpoint:** November 3, 2026. **State:** source-only import preview
validated with synthetic certificates. **No active ONU change.**

## Residential objective

Let a user load a certificate and matching private key for a hostname or
management IP they control, with an optional intermediate/root CA chain.
A public CA is optional, and the eventual GUI should present clear
identity, expiry, trust, and rollback information. This source task does
not implement the production GUI, key storage, or live certificate
switch.

## Source-only implementation

Source: 'tools/s011_offline_certificate_import.py'

Tests: 'tests/test_s011_offline_certificate_import.py'

The Python cryptography library is an **offline host test dependency**,
not an ONU firmware dependency. The read-only preview takes three fixed
filenames in a separately prepared, root-owned 0700 test directory
matching '/var/tmp/aott-s011-import-test-*':

- 'certificate.pem' contains one PEM-encoded or DER X.509 leaf certificate
- 'private-key.pem' contains a matching, unencrypted PEM or DER private key
- 'chain.pem' is optional and contains a PEM chain in issuer order,
  beginning with the leaf's intermediate and optionally ending with
  the self-signed root

The directory and file names are fixed by the source prototype. It
does not write to these files, copy them to a firmware directory, or
change any certificate installed on the device. The private key must
be root-owned 0600, with a single hard link. Other input material must
be root-owned 0600/0644. File reads use bounded sizes, an OS
no-follow flag, and inode/permission checks. No source files or test
fixtures include a real certificate or key. Tests generate short-lived
synthetic keys/certificates in temporary directories.

## Validation rules

- A maximum of 16 KiB each for the leaf and private key, 48 KiB for a
  supplied chain, and up to three chain certificates.
- Strict PEM structure or single-object DER framing; appended material
  and extra certificate blocks are rejected.
- Matching certificate/private-key public keys using canonical SPKI.
- Approved EC P-256/P-384 or RSA 2048 to 4096 private keys. SHA-256,
  SHA-384, or SHA-512 certificate signatures; not SHA-1.
- Explicit SAN coverage for each configured DNS hostname or IP, with
  single-label wildcard matching only. Extra SANs are not echoed in
  diagnostic receipts.
- An end-entity leaf must not be a CA; when supplied, KeyUsage must
  include digitalSignature and ExtendedKeyUsage must include
  serverAuth. Dates must be currently valid and not about to expire.
- For each supplied issuer: valid current dates, CA constraints,
  keyCertSign where supplied, allowed key algorithms, bounded path
  length, correct issuer ordering and verified signature. Unsupported
  NameConstraints fail closed instead of being called validated.
- When present, a supplied self-signed root must verify its own
  signature. **This does not establish public or browser trust.**
- With no supplied issuer chain, an externally issued leaf can be
  checked for key pairing, syntax, SANs, expiry and algorithms, but its
  issuer signature remains **unverified**. The preview says
  'S011_OFFLINE_IMPORT_PREVIEW_PARTIAL'. A leaf with a supplied complete
  root chain receives a stronger cryptographic preview result, but
  remains unqualified for browser trust, revocation and deployment.

The preview returns a certificate fingerprint, expiry and high-level
status with SAN match counts. It does not return the provided IPs,
hostnames, raw chain PEM, private key, or cryptographic secrets.

Encrypted private keys are currently rejected: safely collecting and
decrypting an import passphrase requires a separate authenticated
local-only flow. No passphrase may be supplied through command-line
arguments or diagnostic logs.

## Example source test

From the repository root on an offline host:

~~~sh
python3 -m unittest discover -s tests \
  -p 'test_s011_offline_certificate_import.py' -v
~~~

The tests generate only synthetic certificates. They cover valid
intermediate/root chains, absent/incomplete chains, self-signed leaf,
DER and PEM, wildcard scope, mismatch, file permissions, swapped
keys, modified signatures, expiry, CA path restrictions, abnormal
files, symlinks, hard links, overlong bundles, unwanted fields, and
redacted CLI output. They do not use customer identities or keys.

## Production blockers and required follow-up

1. Determine the actual supported certificate/key formats and chain
   loading behavior of the **deployed** uhttpd build. An offline PEM/DER
   parser is not proof that its TLS implementation accepts an import.
2. Add an authenticated, local-only upload endpoint with bounded
   streaming, no leaked upload content, and an explicit authorized
   import action. Verify the user's intended management identity.
3. Implement device-native equivalent validation with proven runtime
   libraries; do not assume Python cryptography exists on the stick.
4. Implement real browser/CA trust, policy, full certificate path
   validation and revocation handling. Basic chain signatures alone
   are not enough for browser trust, especially for NameConstraints,
   unsupported algorithms and untrusted roots.
5. Protect existing certificate, key and config with independently
   verified backups and a guarded rollback timer. No restart can
   strand the user without local recovery.
6. Test an authorized HTTPS handshake in the user-selected browser
   via the intended local management IP/hostname, including IPv4/IPv6
   where configured, and confirm cert/key/chain and SAN readback.
7. Qualify reboot/A-B survival, private-key permissions on real storage,
   startup recovery, and noninterference with XGS-PON forwarding.

**Not deployed:** no LuCI route, new daemon, uhttpd restart, certificate
rotation, key migration, ISP configuration change, firmware staging,
trial boot, or bank commit. The existing S-010 generator likewise
remains source-validated only.
