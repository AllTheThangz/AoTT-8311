# V3 operator-owned TLS import qualification

## Source status

AoTT-8311 V3 now installs an authenticated operator-owned certificate import
path that feeds the same inactive candidate slot and guarded activation
transaction used by locally generated certificates.

This is source/offline qualification only. No production ONU certificate was
changed during this work.

## Import surface

The HTTPS-only, root-session-only multipart route accepts:

- one server leaf certificate, PEM or DER, up to 16 KiB;
- one unencrypted private key, PEM or DER, up to 16 KiB;
- an optional ordered PEM/DER issuer chain, up to 48 KiB and three CA
  certificates;
- expected DNS SANs and IPv4 SANs that must be covered by the leaf.

Staging occurs in a private volatile directory. Imported material never writes
the active persistent HTTPS pair directly.

## On-device validation

The installed Lua parser and native runtime enforce:

- strict single-object DER framing or bounded PEM decoding;
- currently valid leaf and issuer dates;
- leaf Basic Constraints CA=false;
- SAN required on the leaf;
- serverAuth when a restrictive EKU is present;
- digitalSignature when leaf KeyUsage is present;
- CA=true and keyCertSign when issuer KeyUsage is present;
- NameConstraints fail closed because the compact runtime does not implement
  complete RFC 5280 subtree processing;
- RSA public keys from 2048 through 4096 bits;
- EC public keys on P-256 or P-384 only;
- SHA-256, SHA-384, or SHA-512 RSA/ECDSA certificate signatures;
- ordered issuer/subject name linkage;
- CA path-length constraints;
- single-label DNS wildcard matching only;
- exact expected IPv4 SAN matching.

A public-style intermediate-only fullchain is accepted. A supplied self-signed
root is treated as a trust-anchor hint and is not included in the served chain.

The compact on-device parser does not implement public-key signature
verification for the issuer chain. Browser trust is therefore deliberately
left unproven until guarded activation. The older offline S-011 cryptography
model remains the stronger pre-build signature-validation reference.

## Certificate/private-key pairing

Before an import becomes a candidate, V3 starts the exact vendor
`/usr/sbin/uhttpd` on a loopback-only temporary port with the imported
certificate bundle and private key. The exact vendor `uclient-fetch` must
complete a TLS request against a fixed private probe file.

This rejects mismatched or unsupported cert/key pairs without touching the
active HTTPS listener.

## Activation and recovery

A successful import only populates the inactive TLS candidate slot. Activation
remains a separate action:

1. persistent active certificate/key backup;
2. candidate replacement;
3. uhttpd restart;
4. browser reconnect through the new certificate;
5. authenticated confirmation within 180 seconds;
6. automatic restoration of the previous pair on timeout/failure;
7. boot-time recovery of an unconfirmed activation.

Generated and imported candidates therefore use one recovery contract.

## Tests

Production-source regression covers:

- RSA PEM and DER;
- EC P-256 with CA chain;
- standard intermediate-only fullchain;
- missing issuer chain refusal;
- SAN mismatch;
- expired leaf;
- RSA-1024 refusal;
- unsupported EC curve refusal;
- exact vendor-uhttpd mismatched-key rejection;
- multipart/CSRF browser staging;
- no direct active-certificate mutation from the import module.

Browser trust, revocation behavior, external CA reachability, and the live
production HTTPS restart remain hardware/runtime acceptance items.
