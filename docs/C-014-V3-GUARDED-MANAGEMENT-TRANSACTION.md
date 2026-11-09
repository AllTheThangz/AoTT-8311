# C-014 V3 guarded management transaction

**Status:** production-scoped source implementation complete enough for bounded hardware qualification; no live management mutation has been performed.

## Scope

The V3 development tree now treats the six lockout-sensitive management controls as one guarded tuple:

- `lct_vlan`
- `ipaddr`
- `netmask`
- `gateway`
- `dns_server`
- `lct_mac`

These fields are intentionally isolated from the ordinary configuration writer. They use the same schema validation and review UI, but applying them launches a dedicated timed transaction.

## A-to-Z source path

1. Read the native environment and UCI state.
2. Validate and preview the complete tuple.
3. Refuse mixed management + unrelated changes in one save.
4. Write a root-only persistent rollback snapshot before mutation.
5. Acquire the shared environment lock used by firmware/config writers.
6. Write and read back the exact six boot-environment fields.
7. Apply the native network/firewall UCI transition and read it back semantically.
8. Reload network and firewall through fixed native service entrypoints.
9. Verify the active runtime from independent sources:
   - management interface selection from netifd;
   - IPv4 address/prefix from netifd;
   - default route from netifd;
   - active DNS list from netifd;
   - interface MAC from sysfs;
   - exact 802.1Q VLAN ID from `ip -d link` for tagged management.
10. Wait up to 300 seconds for a new authenticated root HTTPS session to confirm the new path.
11. Clear rollback state only after confirmation.
12. On reload failure, convergence failure, confirmation failure, or timeout, restore UCI and boot-environment state, reload, and verify the restored runtime.
13. If the device reboots with an unconfirmed transaction, restore the pre-change state before normal startup configuration continues.

Management values are stored only in root-private transaction/recovery files. They are not placed in process argv or public receipts.

## GUI behavior

The normal Configuration page remains the single management-settings entrypoint.

A reviewed management-only diff is sent to the guarded transaction instead of the normal `/save` apply path. The browser shows the proposed reconnect address and warns that the previous configuration will be restored automatically unless the new path is confirmed before the deadline.

After reconnecting to the proposed management IP, the Management network & recovery page exposes an authenticated confirmation button. Failed confirmation leaves the rollback warning visible and does not instruct the user to start another transaction.

## Source evidence

Current automated coverage includes:

- complete six-field private tuple planning;
- environment snapshot/apply/restore;
- root-only persistent recovery-store behavior;
- native UCI application and semantic restore readback;
- exact runtime convergence checks including DNS and VLAN ID;
- transaction success, timeout rollback, convergence rollback, pre-mutation failure and rollback-failure cases;
- shared environment-lock worker path;
- boot-time pending recovery ordering;
- host and extracted vendor-MIPS Lua fixtures;
- real Chromium routing from Configuration review to the guarded transaction;
- real Chromium confirmation success/failure behavior.

The current V3 capability registry therefore exposes 55 controls, with 10 in the management group. `lct_vlan` is no longer classified as a hidden broken candidate.

## Hardware qualification still required

This source work does not make the management tuple FULLY_QUALIFIED.

A separately authorized hardware qualification must still demonstrate:

- apply to a reversible alternate management tuple;
- reconnect through the changed path;
- independent runtime convergence;
- explicit confirmation;
- restoration to the original tuple;
- timeout rollback;
- reload-failure rollback where safely injectable;
- reboot persistence after a confirmed change;
- reboot recovery from a deliberately unconfirmed pending transaction;
- continued PON O5.1 and 10 Gbps host-link health throughout applicable tests.

The unchanged r9 reference unit was only read during this development cycle. Its current untagged `lct_vlan` state is recorded without addresses/MAC/DNS values in [C-014-MANAGEMENT-VLAN-READONLY-BASELINE.json](C-014-MANAGEMENT-VLAN-READONLY-BASELINE.json).
