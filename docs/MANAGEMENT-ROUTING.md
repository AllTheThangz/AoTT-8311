# Management routing compatibility (v2r3 offline candidate)

## Regression and scope

The uncommitted v2r2 build removed the saved management gateway when it
equaled the ONU's local address. The change was intended to avoid a
self-referential next hop, but broke return-path connectivity on a
PRX126-SFP-PON installation that relied on the inherited setting.
Optical forwarding continued even though routed management became
unreachable. No other target or WAN routing changes are authorized here.

The bootloader may supply a gateway through the kernel IP argument.
That value cannot be assumed to be a live router, and overriding the
persisted management configuration with it is unsafe. Do not infer a
valid gateway from an address that merely belongs to the local subnet.

## Behavior

- **Saved legacy self-address gateway:** Preserve it exactly on startup and
  show it in LuCI. Do not clear it when unrelated settings are saved.
  This compatibility behavior is not a recommendation for new deployments.
- **Explicitly empty saved gateway:** Leave the management interface without
  a default route.
- **Explicit, valid subnet router:** Preserve the configured next hop.
- **New self-address gateway:** Reject it through the LuCI configuration
  planner. A gateway equal to the ONU IP is not a new supported setting.
- **Changing the management IP with an existing legacy gateway:** Refuse
  until the administrator explicitly clears or replaces the gateway.
  This prevents accidentally carrying a stale self-address route forward.
- **Clearing a legacy gateway:** Allow an explicit change, but note that
  routed SSH and HTTPS may stop working after the next boot.

This preserves historical routing for compatible in-place upgrades while
allowing deliberate migration to conventional networking.

## Offline regression tests

Run the source test suite. The shell and Lua tests cover the saved legacy
route, untagged and tagged management interfaces, explicit blank gateway,
an actual router gateway, unrelated configuration saves, and management-IP
changes.

    python3 -m unittest discover -s tests -v
    python3 tools/verify_release.py .

These tests do not prove real hardware boot, optical registration, or the
ability to reach LuCI from a remote subnet.

## Hardware acceptance (do not automatically commit)

1. Keep the current committed firmware and verified off-device A/B backups.
2. Stage the new image on the **inactive bank only**, with a one-shot trial.
3. Check that the saved management IP, default route, return path, and
   firewall bindings are preserved after boot.
4. Verify SSH, authenticated LuCI login, WAN1 (not only WAN2), 10G Ethernet,
   optical O5.1, and uninterrupted PON provisioning.
5. Independently confirm the active and committed banks before any commit.

If management disappears, power-cycle the stick only after flash writes
are verified complete. A detached rollback with a bounded bank check is
safer than a reboot command attached to a fragile SSH session.
