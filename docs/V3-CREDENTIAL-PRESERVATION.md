# V3 administrator credential behavior

AoTT-8311 V3 intentionally supports the public factory management credential root/root.

## Default behavior

For a fresh V3 boot with no valid persisted administrator hash, the firmware sets the root account to the documented factory credential:

- username: root
- password: root

This factory default is allowed during development, local use, firmware staging, trial boots, and normal public deployment. It is not a firmware-deployment blocker.

On the first authenticated GUI session while the factory root/root credential is still active, V3 presents a password-change prompt. The user may either open LuCI's Root password page or explicitly choose **Keep root/root**. That acknowledgement is stored on the device and prevents repeated prompting. If the password is changed instead, the prompt disappears automatically.

If a supported root password hash has already been persisted, that saved credential takes precedence over the factory default and is restored at boot.

## Upgrade behavior

Before writing an inactive firmware bank, the V3 upgrade path preserves the currently configured supported root credential and verifies the protected boot-environment readback. This applies equally to the factory root/root credential and an administrator-selected custom password.

The password and hash value are never written to logs, HTTP responses, command-line arguments, support bundles, or release metadata.

Blank, locked, malformed, or unsupported credential states may still fail preservation because they cannot be restored reliably. The factory root/root state is explicitly valid.

## Security posture

The Security page may recommend changing the factory credential when management is exposed beyond the local management interface. That recommendation is advisory only. It does not prevent firmware installation, staging, trial, or commit.

The user remains free to keep root/root for local development and residential use.
