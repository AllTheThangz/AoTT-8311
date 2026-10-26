# Offline build and qualification boundaries

This repository is a sanitized **source-only overlay**, not a firmware
installation package or redistributable vendor firmware.

1. Acquire a legally authorized clean factory/base firmware corresponding
   to LL-XS1010 / PRX126-SFP-PON, kernel 4.9.308+, and the exact vendor PON
   and OMCI ABI. Never export a subscriber's live /etc/config or flash.
2. Run the repository source audit and unit tests:

       python3 tools/verify_release.py .
       python3 -m unittest discover -s tests -v

3. Stage the reviewed text overlay **offline in a new empty directory**:

       python3 tools/install_overlay.py --destination /tmp/aott-source-stage

   This command does not merge into or modify the factory base. Any later
   merge must be manually reviewed to protect unrelated vendor files.
4. Only in a separate clean offline build workspace, merge the staged source
   into a verified factory rootfs and generate device-specific configuration.
   Use a unique root password, authorized PON identity and accepted ISP
   provisioning. Never save credentials in this Git checkout.
5. Generate a cryptographic hash manifest for all final image components;
   check platform/build IDs and kernel/OMCI compatibility. Verify 1 MiB XZ
   SquashFS geometry and the UBI volume's true capacity.
6. Independently extract the full rootfs and validate file bytes,
   ownership, modes, symlinks, device nodes and dependencies.
7. Before any firmware flash, have an independently approved target-side
   action, verified full-volume A/B backups stored off-device, and one-shot
   boot fallback. Confirm PON, 10G, SSH/HTTPS, WAN throughput and logs.
8. Commit only after a complete, explicitly authorized trial acceptance.

This repository cannot reproduce the historical v2r1 full firmware
bit-for-bit without external original vendor binaries and source materials.
It intentionally includes neither vendor flash components nor user/ISP
provisioning data.

The source overlay helper never writes to a running device, runs UCI,
updates the boot environment, or performs an installation.
