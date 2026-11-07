# V3 TLS candidate and private-key hardening qualification

**Status:** runtime candidate generation integrated, activation gated. The production r9 HTTPS service and certificate were not changed.

AoTT-8311 V3r1 adds two TLS improvements for residential management:

1. a narrowly scoped boot-time permission hardener for the existing persistent HTTPS private key; and
2. an authenticated HTTPS-only page that generates or discards an inactive self-signed certificate/key candidate in volatile /tmp storage.

Neither feature replaces the active certificate. Candidate installation, uhttpd reload, persistent certificate rotation, and imported certificate activation remain blocked until rollback and browser-handshake qualification is complete.

## Read-only r9 finding

A read-only inspection of the committed r9 reference unit confirmed:

- uhttpd is configured to use the persistent certificate and key under /ptconf/8311/uhttpd;
- the certificate is root-owned mode 0644;
- the private key is root-owned mode 0644.

No private-key bytes were read, copied, hashed, or returned. The existing V3 health model already classifies that private-key mode as overexposed.

## V3 key hardener

V3 adds a one-shot service immediately after uhttpd startup. It accepts only the fixed qualified persistent key location and verifies:

- regular file;
- root owner and group;
- one hard link;
- current mode either already restricted or exactly the legacy 0644 condition.

For the legacy 0644 condition, it changes only the mode to 0600 and independently verifies the same device/inode and final mode. It never reads key bytes, changes UCI, changes certificate contents, restarts uhttpd, or follows a symlink. Unknown inode types or modes fail closed.

## Inactive local certificate candidate

The authenticated V3 HTTPS certificate page can generate one inactive candidate at a time.

Current runtime bounds:

- ECDSA P-256 or RSA-2048;
- 1 through 397 validity days;
- one through four total SAN identities;
- DNS SANs and canonical IPv4 SANs in the initial runtime UI;
- fixed /tmp/aott-tls-candidate root-owned 0700 staging directory;
- root-owned 0644 certificate and 0600 private key;
- DER output from the vendor /usr/sbin/px5g;
- bounded certificate/key files, at most 16 KiB each;
- SHA-256 fingerprint of the public certificate only;
- no private-key bytes or SAN values in diagnostic receipts.

The runtime generator uses argv execution, not a shell. A candidate must be discarded before another can be generated. Candidate material is volatile and disappears on reboot.

The independently maintained S-010 offline harness continues to qualify the exact vendor px5g binary, including EC/RSA generation, DNS/IPv4/IPv6 SANs, pairing, signature integrity, tamper rejection, validity bounds and private-key modes. That independent tool is not replaced by the runtime page.

IPv6 SAN generation is proven in the offline harness but is not yet exposed by the V3 runtime page. It remains a follow-up before complete S-010 feature closure.

## Qualification evidence

The focused V3 TLS and legacy security suite passes 33 tests with zero failures, including the real vendor-MIPS px5g tests on the extracted PRX126 rootfs.

The V3 runtime validation/hardening contract passes under both host Lua 5.1 and the extracted PRX126 vendor MIPS Lua runtime.

## Activation and import gates

The page intentionally exposes no install/activate route. Activation requires:

1. exact backup and readback of the active certificate, private key and uhttpd configuration;
2. candidate key/certificate validation on the target runtime;
3. isolated uhttpd candidate-load and local TLS handshake verification;
4. a second local recovery path that remains available if HTTPS activation fails;
5. timed automatic rollback unless the new HTTPS path is explicitly confirmed;
6. real browser verification against the intended management DNS/IP identity;
7. reboot and A/B-bank persistence checks.

Operator-owned certificate import remains at the S-011 validation stage until equivalent native leaf/key/chain validation, secure bounded upload, rollback, and browser trust checks are integrated.

This document authorizes no change to the production r9 HTTPS certificate or service.
