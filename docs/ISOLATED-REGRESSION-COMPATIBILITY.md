# Isolated regression compatibility repair

The first complete run of the installed service executed all 1,166 assigned test IDs but failed with three failures, ten error records (including subtests), and one skip. Its logs remain preserved; this follow-up does not relabel that run.

## Runtime corrections

The credential-free runtime now includes the missing host `flock` utility and a fixed site-packages entry for its immutable Python dependencies, including child interpreters. The vendor reference retains the thirteen configuration-domain shapes without retaining private configuration values. Only generic firewall policy values and the previously reviewed generic HTTPS reference are preserved. Missing vendor ABI-reference binaries and the original relative BusyBox timeout link are included. They are not run against hardware.

The same sanitized reference is mounted read-only at a fixed `/var/tmp/aott-vendor-reference` path, satisfying the existing offline-source path restrictions without broadening those source readers to arbitrary paths.

## Genuine negative metadata without test privileges

The installed sandbox deliberately cannot chown to unmapped UID/GID 65534 or create a setuid-mode file. Two tests now optionally consume administrator-prepared immutable fixtures under the fixed sandbox profile. The foreign-owner test verifies real inode owner/group/mode, checks a read-only mount, invokes the unchanged vendor-MIPS staging guard, and still requires zero native operations and the same unsafe-lock rejection. The archive test verifies a real mode-04755 inode and matching bytes/hash, then invokes the unchanged archive verifier and requires its original mode-mismatch rejection.

These are real filesystem fixtures, not mocked stat calls or skipped subtests. Missing/malformed fixtures fail. The original test setup is retained outside the isolated profile. All fixture mounts are read-only, nosuid, nodev and noexec. Test processes retain zero capabilities and no-new-privileges; systemd RestrictSUIDSGID, device/network isolation and resource limits remain unchanged.

No production overlay, Lua module, configuration implementation, firmware image, live ONU state or gateway policy changed. Only test fixture construction and local runner packaging changed. The same 1,166 test IDs must pass with zero failures/errors/skips before this revision is accepted. This document records the repair plan; it does not claim a full-suite pass before execution.
