# C-012: Offline validation and stored-value readback tests

**State:** source-level verification only, November 2, 2026.
**Firmware:** unchanged. **Hardware qualification:** not performed.

## Implemented

The test fixture loads the **actual** 54-field LuCI configuration schema and
the real 8311.config Lua module with fake vendor dependencies. It tests
positive and negative input for each discovered GUI field, then exercises
the real preview, setter-selection and readback logic using an in-memory boot
environment. It does not duplicate the field definitions in a separate test
schema.

The fixture currently exercises:

- All 54 existing GUI fields with a positive synthetic input, a rejected
  control-character input, a setting-type-specific invalid input, and a complete-form preview.
- All 54 positive simulated writes, including base U-Boot versus prefixed
  environment namespace selection and durable readback comparison.
- Redaction of all five fields treated as sensitive by the Lua configuration
  layer, including the stored PON identity. No real secrets are used.
- Stale form revisions, unexpected fields, duplicate/array inputs and
  failed or missing readback.
- A setter failing after mutation, the second setter failing in a
  multi-field operation, or a setter falsely reporting success while storing
  a different value. These must report uncertain or partial persistence,
  never claim an atomic successful transaction.
- Review differences that distinguish a stored override from proven runtime
  effect. These source checks do **not** establish the runtime effect.

A Python test runner executes the isolated Lua 5.1 fixture. An offline vendor
MIPS rootfs may be supplied through AOTT_VENDOR_ROOTFS for a second pass
under QEMU. Both modes pass in the local offline vendor rootfs fixture.
Without that rootfs, the MIPS test is skipped, not reported as
hardware-qualified.

## Reproduce

Run from the source repository root:

    python3 -m unittest discover -s tests -p 'test_c012_config_contract.py' -v

Or run the Lua fixture directly:

    lua5.1 tests/c012_config_contract_fixture.lua overlay/usr/lib/lua/8311/config.lua overlay/usr/lib/lua/luci/controller/8311.lua

The fixture uses mocked native setters, fwenv_read_all, UCI and the vendor
MIB gate. It does not contact any ONU or require a writable device.

## Evidence still required

This is the **first C-012 source test tranche**, not completion of C-012.
Per-field positive and negative actual native setter qualification, effective
consumer confirmation, service persistence, reboot and A/B behavior, alternate
management recovery and full GUI browser save-and-readback remain open.

Do not mark any of the 54 settings FULLY_QUALIFIED based on these tests.
No live firmware installation, settings change, flash write or bank transition
is associated with this work.
