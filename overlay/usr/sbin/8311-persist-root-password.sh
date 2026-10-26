#!/bin/sh
# AoTT-8311-v1 r5: persist an existing administrator hash without disclosing it.
# Requires that the hash is already configured; never generates credentials.
set -eu
umask 077

ROOT_PWHASH=$(awk -F: '$1 == "root" { print $2; exit }' /etc/shadow) || {
    echo "Unable to read the local administrator password status." >&2
    exit 1
}
trap 'unset ROOT_PWHASH' EXIT

if [ -z "$ROOT_PWHASH" ]; then
    echo "Administrator password is not configured. Nothing was saved." >&2
    exit 1
fi
if ! /usr/libexec/8311-root-hash-valid "$ROOT_PWHASH" >/dev/null 2>&1; then
    echo "Unsupported password-hash format; boot settings were not changed." >&2
    exit 1
fi

# Preserve the established fwenv_set contract; suppress all potential
# stdout/stderr from utilities handling hashes and verify readback in memory.
if ! fwenv_set -8 root_pwhash "$ROOT_PWHASH" >/dev/null 2>&1; then
    echo "Password-hash persistence failed; confirm boot-environment integrity." >&2
    exit 1
fi
READBACK=$(fwenv_get --8311 root_pwhash 2>/dev/null) || {
    echo "Password-hash persistence readback failed." >&2
    exit 1
}
if [ "$READBACK" != "$ROOT_PWHASH" ]; then
    unset READBACK
    echo "Saved password hash does not match; verify boot environment." >&2
    exit 1
fi
unset READBACK
printf '%s\n' "Administrator password hash persisted and verified (value withheld)."
