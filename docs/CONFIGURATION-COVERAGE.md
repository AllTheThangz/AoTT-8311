# AoTT-8311 configuration coverage and functional audit baseline

**Historical baseline:** security-enhanced private r8 source was audited 2026-11-02 with 54 exposed GUI fields. The current V3 development schema exposes **55 controls** after repairing and re-enabling `lct_vlan`. The readback union is now 55 fields: 10 management, 11 device/SFP, 8 advanced hardware, 9 sensitive identity, 4 PON/OMCI, 10 reporting, and 3 ISP/VLAN. The original committed-r9 54-field read-only receipt remains immutable; `lct_vlan` has a separate value-free read-only baseline extension.
**Current V3 development:** all **55 Configuration-page fields** are explicitly routed and none may silently fall through to generic persistence. The route inventory is **22 live**, **6 guarded management**, **22 guarded PON/OMCI**, **4 guarded one-boot**, and **1 credential**. The Access & servers page adds 22 separately guarded SSH/uHTTPd/LuCI/remote-HTTPS settings. These are source-functional transaction paths with validation, preview, authoritative readback, runtime verification where locally observable, and rollback/recovery appropriate to each risk class. `FULLY_QUALIFIED` remains a hardware evidence state, not a source-completion label.

**Important:** This is a static source inventory, not an assertion that every setting works in the real device. Runtime evidence and platform qualification must be added field by field.

**C-011 ISP/VLAN runtime-evidence extension:** A bounded, authenticated manual readback now supports independently checking the specific built-in kernel TC flower selectors when an exact trusted native reconciliation receipt and unchanged topology are available. This does not expand the count of 27 source-covered settings or establish Internet connectivity or full hardware qualification. The currently tested production stick lacks the requisite receipt. See [the ISP/VLAN evidence contract](C-011-ISP-VLAN-READONLY-EVIDENCE.md).

## Baseline counts

| Domain | Currently exposed firmware-environment controls |
| --- | ---: |
| PON, OLT, OMCI identity and compatibility | 22 |
| ISP service and VLAN | 3 |
| Device, boot and system | 13 |
| SFP EEPROM identity | 7 |
| Management | 10 |
| **Total** | **55** |

The form uses a general source-backed schema with server-side validation, revision-aware previews, serial writes to the boot environment and saved readback. That is useful groundwork, but does not prove the running consumer applied any individual value.

### 22 PON/OLT/OMCI controls

| Setting ID | Meaning | Risk |
| --- | --- | --- |
| gpon_sn | PON serial presented to OLT | Critical connection risk |
| vendor_id | Reported PON vendor ID | Critical connection risk |
| equipment_id | ONU reported equipment model | OMCI interoperability |
| hw_ver | Reported hardware version | OMCI interoperability |
| cp_hw_ver_sync | Circuit-pack reported hardware sync | OMCI interoperability |
| sw_verA | OMCI-reported firmware image A version | Reporting, not real bank flash |
| sw_verB | OMCI-reported firmware image B version | Reporting, not real bank flash |
| fw_match_b64 | OLT software version matching expression | Firmware interoperability |
| fw_match_num | Occurrence selected from version expression | Firmware interoperability |
| override_active | Reported OMCI active bank override | Reporting, not actual boot selection |
| override_commit | Reported OMCI committed bank override | Reporting, not actual commit |
| pon_mode | Optical access mode, as supported | Critical connection risk |
| omcc_version | OMCI management protocol version | OLT compatibility |
| iop_mask | OMCI interoperability bitmask | OLT compatibility |
| reg_id_hex | PON registration credential | Secret, authentication |
| loid | Logical ONU identifier | Authentication, may be sensitive |
| lpwd | Logical ONU password | Secret, authentication |
| mib_file | User-selected OMCI MIB profile | GEM/UNI/VLAN service risk |
| pon_slot | Reported UNI slot | OMCI path risk |
| iphost_mac | OMCI IP Host ME MAC | Reported identity |
| iphost_hostname | OMCI IP Host ME hostname | Reported identity |
| iphost_domain | OMCI IP Host ME domain | Reported identity |

### 3 ISP/VLAN controls

| Setting ID | Meaning | Risk |
| --- | --- | --- |
| fix_vlans | Automatic, disabled or privileged-hook translation | Direct service impact |
| internet_vlan | Local Internet VLAN | Can stop traffic while PON stays O5.1 |
| services_vlan | Additional services VLAN | Can impair IPTV and other services |

### 13 device/system controls

| Setting ID | Meaning | Risk |
| --- | --- | --- |
| lang | GUI language | Standard |
| bootdelay | Bootloader delay | Recovery risk |
| console_en | Serial console on shared SFP pin | Host signalling conflict |
| uart_select | Early boot UART | Host signalling conflict |
| dying_gasp_en | Power loss signalling | Serial pin conflict |
| rx_los | Host receive-loss signalling | Management/link behavior |
| root_pwhash | Advanced root hash override | Secret, auth and recovery |
| ethtool_speed | Host Ethernet override | 10G service and management risk |
| failsafe_delay | OMCI startup delay | Registration delay |
| hostname | ONU system name | Standard |
| timezone | Log and GUI time zone | History correctness |
| ntp_servers | Time synchronization | History correctness |
| persist_root | Debug persistence | Boot/recovery, high risk |

### 7 host-visible SFP EEPROM controls

sfp_vendor, sfp_oui, sfp_partno, sfp_rev, sfp_serial, sfp_date, sfp_vendordata.

These modify information presented to the host router only where the hardware driver supports it. They must be distinguished from the real physical chip identity and the serial or OMCI identity presented to the OLT.

### 10 management controls

lct_vlan, ipaddr, netmask, gateway, dns_server, pingd, ping_ip, lct_mac, reverse_arp, https_redirect.

The six lockout-sensitive tuple fields, `lct_vlan`, `ipaddr`, `netmask`, `gateway`, `dns_server`, and `lct_mac`, are isolated from the ordinary configuration writer. Their V3 source path writes a persistent pre-change recovery snapshot, applies boot-environment and UCI state under the shared environment lock, reloads network/firewall, verifies the active netifd/kernel address/route/DNS/MAC/VLAN state, and requires authenticated confirmation before clearing rollback state. This is source readiness, not hardware qualification.

## Explicitly uncovered or disabled candidates

| Identifier | Current evidence | Next action |
| --- | --- | --- |
| device_sn | Startup source reads the option, but the inspected vendor backend setter is an explicit no-op. It is absent from the GUI. | Treat as unimplemented. Only expose if a board-specific actual setter and effective readback are independently proven; do not promise identity changes from a successful no-op |
| factory_mode | Listed as an upstream-documented potential setting, not confirmed functional in current AoTT. | Confirm upstream vendor path and hardware applicability; include only if meaningful, testable and recoverable |
| tx_en_mode | Source helper and PON initialization consume optical TX-enable mode, but the GUI has no control. | Verify supported optical mode enumerations, module-specific electrical behavior, signal-pin conflicts and recovery on spare hardware before exposing |

No item above should be called fixed merely by uncommenting or adding a GUI field.

## Additional vendor UCI surface in offline image

13 named configuration domains were found:

dropbear, firewall, gpon, ieee_1588, luci, omci, optic, rpcd, serdes, sfp_eeprom, tod, ucitrack, uhttpd.

Their option names can be inventoried safely, but their mere presence does not mean every option is supported, writable by the user, or relevant to every module. Many are framework, service, vendor-private or device-calibration properties.

The complete configuration registry should enumerate qualified options across all actual backends:
- boot environment and persistent UCI;
- active netlink and Ethernet/SerDes;
- PON, OMCI, supported MIB profile and VLAN services;
- optics diagnostics and alarms;
- HTTPS certificate manager, SSH access and opt-in firewall;
- history/logging/export configuration;
- firmware A/B and recovery operations.

## Current V3 A-to-Z routing

Every Configuration-page field is assigned to exactly one server-owned path:

| Route | Fields | Source behavior |
| --- | ---: | --- |
| Live activation | 22 | Persist, activate fixed native consumer, verify configured/runtime state, rollback on mismatch |
| Guarded management | 6 | Persistent pre-change recovery, UCI/environment apply, network/firewall reload, exact runtime convergence, reconnect confirmation, timeout/boot rollback |
| Guarded PON/OMCI | 22 | Persistent environment/UCI/MIB recovery, profile-driven MIB applicability/introspection, fixed local apply/readback, confirmation and boot recovery; OLT acceptance remains separate evidence |
| Guarded one-boot | 4 | Stage candidate with persistent previous state, reboot trial, watchdog rollback, explicit postboot confirmation |
| Credential | 1 | Secret-safe root shadow activation/readback with durable environment rollback on activation failure |
| **Total** | **55** | No unrouted or generic-fallthrough fields |

The separate **Access & servers** surface adds 22 guarded Dropbear/uHTTPd/LuCI/remote-HTTPS controls with private recovery, service/firewall restart verification, HTTPS-only apply and timed confirmation. Remote HTTPS remains default-off and is restricted to explicit IPv4 /24-/32 allowlists.

## Coverage states

Use consistent per-board coverage codes:

| Code | Meaning |
| --- | --- |
| DISCOVERED | Native source or backend appears to contain the item, no verified effective behavior |
| DISPLAYED | UI/API shows a read value with source and units |
| EDITABLE | Validated GUI/API input plus native setter available |
| SAVED_VERIFIED | Durable readback matches the requested value |
| EFFECTIVE_VERIFIED | Running subsystem demonstrably applied the value |
| PERSISTENCE_VERIFIED | Survives relevant service restart or reboot |
| RECOVERY_VERIFIED | Interruption and rollback/recovery tested |
| FULLY_QUALIFIED | All applicable tests pass on the named platform |
| READ_ONLY | Real measured or OLT-owned property with no supported write |
| EXPERIMENTAL | Expert-only, incomplete qualification clearly disclosed |
| UNSUPPORTED | Board or vendor backend cannot implement it, with reason |

The current source audit covers all **55 Configuration-page controls** and assigns every field to a concrete mutation transaction. Source routing/validation/rollback is therefore substantially beyond DISCOVERED-only coverage, but **no individual field is promoted to FULLY_QUALIFIED solely from source tests**. Hardware evidence remains required for the named platform, especially provider-facing, reboot-dependent, link-affecting, and management-lockout controls.

## Required registry columns

For each setting and each hardware profile, store:
- Stable setting ID, display name, group and units.
- Platform family/board/revision and feature version.
- Storage backend and actual runtime consumer.
- Supported type, range, values, default, dynamic constraints and dependencies.
- Secret classification and which values must never be logged, exported or returned.
- Source page/API and user warning.
- Read, validate, preview, apply, durable readback, effective readback test IDs.
- Service-restart/reboot effect and persistence tests.
- Restore/recovery/negative/failure tests.
- Last verified date, test artifact, hardware profile and clear current status.

No raw subscriber values belong in public coverage snapshots. Registry coverage counts must be generated from the same schema used by the UI, not estimated from manually maintained documentation.

## Functional qualification examples

- **Management VLAN:** working alternate access, real VLAN interface and routes observed, service kept connected, settings persist after boot, explicit revert verified.
- **PON profile or registration identity:** separate recoverable test hardware or test OLT, genuine registration result, secret masking and provider compatibility. Do not test destructive identities on a customer's only working connection without recovery.
- **Host link override:** actual negotiated speed after apply and restart, 10G recovery, traffic forwarding and link-error counters.
- **MIB/UNI profile:** rootfs MIB path validation, OMCI state, GEM/T-CONT and VLAN rules, separate OLT profile qualification.
- **SSL import:** accepted certificate/key pair with matching SAN, restart service and verify browser chain, no key disclosure or cross-bank loss.
- **Remote access:** disabled by default, only explicitly enabled access allowed, local recovery always works, firewall not touching bridged data.
- **History:** no fake WAN-up state, duration measured from elapsed time, clean resets after reboot, bounded storage and verified export.

## Existing source audit tooling

The source auditor under `tools/audit_configurability.py` retains the historical 2026-11-02 inventory and now feeds the V3 capability/routing work. The current Configuration-page schema has 55 fields; the broader backend inventory still includes 13 vendor UCI domains and must continue to distinguish supported product controls from framework, calibration, read-only, experimental, and unsupported options.

A future source update should add each backend and per-platform proof to the registry without silently increasing the count of FULLY_QUALIFIED items.

See the [acceptance and delivery plan](DELIVERY-PLAN-AND-ACCEPTANCE.md).
