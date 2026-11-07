# V3 TLS candidate and private-key hardening qualification

**Status:** runtime candidate generation and guarded self-signed activation integrated; operator-owned certificate import remains gated. The production r9 HTTPS service and certificate were not changed.

AoTT-8311 V3r1 adds three TLS improvements for residential management:

1. a narrowly scoped boot-time permission hardener for the existing persistent HTTPS private key;
2. an authenticated HTTPS-only page that generates or discards a self-signed certificate/key candidate in volatile /tmp storage; and
3. guarded activation of that generated candidate through persistent backup, uhttpd restart, a 180-second browser-confirmation window, automatic rollback, and boot-time recovery of an unconfirmed transaction.

Operator-owned certificate import remains blocked until its validated leaf/key/chain material can enter this same bounded rollback transaction.

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

## Guarded self-signed activation

Activation operates only on the fixed persistent uhttpd paths under /ptconf/8311/uhttpd and never changes the configured UCI certificate/key paths.

Before replacement, V3 requires a unique deployment-ready root credential and a running Dropbear recovery service. It copies the current persistent certificate and key into root-only rollback files, syncs those files, records a persistent pending-activation marker, atomically replaces the active key and certificate, and restarts uhttpd.

The detached activation worker waits up to 180 seconds for explicit confirmation. The administrator must reconnect through HTTPS after the restart and confirm the certificate presented by that new HTTPS session. If confirmation is absent, malformed, or the restart fails, V3 restores the previous pair and restarts uhttpd. If the device reboots while activation is pending, early sysinit restores the previous pair before the normal uhttpd startup.

Confirmation is tied to the persistent pending transaction and its exact job ID. It may be submitted from a newly authenticated root LuCI session because certificate replacement can invalidate the browser's original session connection. No anonymous confirmation route exists.

## Qualification evidence

The focused V3 TLS activation, candidate, and legacy hardening suite passes 41 tests with zero failures against the extracted PRX126 vendor runtime. It includes:

- confirmed activation;
- timeout rollback;
- uhttpd restart-failure rollback;
- refusal when the second recovery path is unavailable;
- simulated process death followed by boot recovery;
- HTTPS-only root-authenticated activation and confirmation routes;
- pending-marker and job-ID confirmation binding; and
- the existing real vendor-MIPS uhttpd loopback TLS handshake using a 0600 key.

The V3 runtime validation/hardening contract passes under both host Lua 5.1 and the extracted PRX126 vendor MIPS Lua runtime.

## Remaining import gate

Operator-owned certificate import remains at the S-011 validation stage until equivalent native leaf/key/chain validation, secure bounded upload, and browser-trust checks are connected to the same guarded activation transaction.

IPv6 SAN generation is also still absent from the runtime candidate UI even though the offline vendor harness proves it.

This document authorizes no change to the production r9 HTTPS certificate or service.
