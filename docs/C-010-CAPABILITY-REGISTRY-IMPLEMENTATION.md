# C-010: Source-derived configuration capability registry

**Checkpoint:** November 2, 2026. **Implementation state:** Source-level registry and tests. Not deployed to the ONU, not proof that individual settings work on hardware.

## What was implemented

A deterministic Python registry builder in `tools/build_capability_registry.py` reads the **existing LuCI configuration schema** through `tools/audit_configurability.py`. The historical checkpoint contained 54 settings; current V3 source contains **55** after the guarded management-VLAN repair. The registry remains source-derived rather than a second manually maintained field list.

Each field record contains:
- Stable identifier, GUI group and schema type from the actual controller.
- Source filename/line number for the GUI field declaration.
- Expected boot-environment backend key, distinguishing two unprefixed bootloader keys from the `8311_` namespace.
- Existing shared server-side read, validation, preview and persisted-write/readback source paths.
- Whether the field represents a secret, an identity, or a potentially service-disruptive operation.
- File/line references to native helper definitions, literal firmware-environment reads and startup/backend consumers where static evidence exists.
- **Explicit false flags** for hardware-confirmed effect, persistence, recovery, and other-board support.

The builder never contacts the real ONU, runs SSH, reads live environment values, stores credentials, displays subscriber serials, or changes firmware. Source references are not hardware qualification receipts.

## Static coverage results

| Inventory | Count | Interpretation |
| --- | ---: | --- |
| GUI firmware-environment fields | 55 | All recognized by schema; current source readiness is tracked separately from hardware qualification |
| PON/OMCI | 22 | Source-only GUI definitions |
| ISP/VLAN | 3 | Source-only GUI definitions |
| System | 13 | Source-only GUI definitions |
| Host-visible SFP | 7 | Source-only GUI definitions |
| Management | 10 | Includes guarded `lct_vlan` control |
| Fields with identified native code references | 49 | Presence only; hardware qualification remains separate |
| Fields without matching native code references in scanned overlay | 6 | Need an independent backend/consumer trace; may be implemented in vendor code or bootloader |
| Known missing environment candidates | 3 | `device_sn`, `tx_en_mode`, and `factory_mode` remain unexposed |
| Legacy environment fallback aliases | 2 | Not standalone controls |
| Vendor UCI configuration domains | 13 | Offline file names and section types only |
| Vendor UCI option names | 89 | Names only, no confirmed setters or live values |
| Full A-to-Z hardware acceptance receipts from this audit | **0** | Intentionally not inferred from source |

The six GUI settings lacking matching native references in the scanned source are: `fw_match_b64`, `fw_match_num`, `override_commit`, `bootdelay`, `uart_select`, and `failsafe_delay`. Some legitimately depend on vendor or bootloader code outside the source overlay. Their lack of static references is a **research task**, not a claim that they do nothing.

### Newly surfaced and previously known omissions

| Identifier | Source evidence | Required work |
| --- | --- | --- |
| `lct_vlan` | Now exposed in V3 behind the guarded management transaction, exact runtime VLAN-ID verification, timed confirmation, and automatic rollback | C-014 hardware apply/reconnect/reboot/recovery qualification remains required before FULLY_QUALIFIED |
| `device_sn` | PON startup helper reads it but GUI lacks a control | C-015: verify vendor semantics, authorization/identity risks and hardware effect |
| `tx_en_mode` | PON startup reads the value, sets the optical control through UCI; not in GUI | C-015: optical and pin safety, supported enumerations, module-specific effects before any UI |
| `factory_mode` | Upstream-documented candidate, no confirmed current AoTT backend evidence | C-015: confirm whether this exists on a specific board and should be exposed at all |

`reg_id` is a legacy fallback for `reg_id_hex`. `sw_ver` is a generic software-image fallback read for A/B. They are classified as compatibility aliases, not new settings. Neither is counted as an independent missing GUI field.

## Trust and safety boundaries

- No source or simulated test makes a control **FULLY_QUALIFIED**.
- Current GUI saving the boot environment does not prove OMCI, PON, Ethernet, management routes or the bootloader applied the setting.
- Privileged configuration is not automatically unlocked by finding a helper name.
- Some exposed UCI keys may be status, framework state, OLT-owned properties, optical calibration, secrets, or settings for hardware absent on this module. They remain read-only discovery candidates.
- Hardware board identity is only a baseline label; native compatibility with another XGS-PON stick is unverified.
- A correct GUI control needs a native getter/setter, validated values and dependencies, effective readback, reboot/cross-bank persistence, failure recovery and an actual qualification receipt.

## Reproduce on source only

Run on an extracted source workspace containing the existing `overlay` tree:

```sh
python3 -B tools/build_capability_registry.py \
  --source-root . 
```

For full offline vendor UCI names, supply a separately obtained, locally extracted, non-live vendor rootfs and a **new** output filename inside `docs/`. The tool deliberately refuses to overwrite an existing registry artifact:

```sh
python3 -B tools/build_capability_registry.py \
  --source-root "$PWD" \
  --vendor-rootfs "/path/to/OFFLINE-VENDOR-ROOTFS" \
  --output "$PWD/docs/CAPABILITY-REGISTRY-NEW-SNAPSHOT.json"
```

No vendor image is bundled with the public source repository. The privately generated dated registry includes only source identifiers and source locations, not live customer values.

The dedicated `tests/test_capability_registry.py` validates parser/schema identity, real source locations, native reference classification, safe backend keys, missing candidates, legacy aliases, offline UCI option names, deterministic output, unsupported claims and refusal to overwrite previous receipts. It works without an external vendor firmware image; vendor-specific UCI assertions run when an offline rootfs is supplied.

## C-010 completion criteria and next work

**Done at current source-evidence level:** the 55-field V3 GUI inventory and vendor key discovery are reproducible; `lct_vlan` is no longer a hidden broken candidate; unknown/default/legacy behavior is not falsely certified; data types, key namespaces and consumer references have an automatically tested artifact.

**Not yet done:** A single runtime-consumable, hardware-qualified capability adapter with per-field effective/readback and persistence semantics. This is C-011 and C-012, not an excuse to mark C-010 as fully hardware validated.

The next implementation steps:
1. **C-011:** attach native backend getter and effective-state verification per field, beginning with management and connection-safe read-only settings.
2. **C-012:** generate per-field positive/negative/effect/persistence test plans with no hardcoded spoofed success.
3. **C-014:** investigate broken management VLAN without changing the production device.
4. **C-015:** trace `device_sn`, `tx_en_mode` and `factory_mode` on independent hardware, focusing on recovery.
5. **H-011:** integrate the previously proven 64-bit history model with a bounded, nonpersistent sampler.

The running enhanced-r8 trial and original-r8 fallback are not modified by this C-010 source work.
