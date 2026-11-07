# V3 administrator credential preservation

AoTT-8311 V3 treats administrator credential persistence as a firmware-deployment gate.

## V3 behavior

On V3 and later, an installation refuses to begin bank mutation unless the running root account:

- has a supported password hash;
- does not match the known factory root password;
- can be persisted into the protected 8311 boot-environment namespace; and
- passes immediate hash readback verification.

The check returns status only. Password and hash material are never written to logs, HTTP responses, command-line arguments, support bundles, or release metadata.

Credential persistence occurs after the administrator has confirmed the installation and after the final bank-state precondition check, but before the target bank is marked incomplete or any image volume is written.

## First transition from r9

The currently installed r9 image predates the installer-side gate. Therefore the first r9-to-V3 transition must be treated separately:

1. Change the live r9 root password from the known factory root value to a unique administrator password.
2. Verify both intended SSH and HTTPS management access.
3. Run the existing root-password persistence helper locally on r9.
4. Verify the Security page reports a configured durable password hash without displaying it.
5. Only then perform a separately authorized V3 inactive-bank stage.

If these checks are not complete, the V3 stage is blocked. A generic instruction to continue does not authorize changing the password, staging firmware, changing a boot selector, rebooting, trialing, or committing a bank.

## Recovery

The V3 boot path validates a saved hash before applying it to /etc/shadow and performs live readback without logging the value. If no valid saved hash exists, it does not invent or generate a shared credential.

The current committed r9 bank remains the recovery baseline until an independently verified V3 trial and separate permanent commit.
