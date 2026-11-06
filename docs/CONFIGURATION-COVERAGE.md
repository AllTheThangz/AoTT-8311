# AoTT-8311 configuration coverage and functional audit baseline

**Source baseline:** security-enhanced private r8 source audited 2026-11-02. C-010 inventories four hidden/missing candidates, native references, 13 vendor UCI files and 89 offline option names. C-011 authenticated readback now covers **54 of 54 fields**, including nine redacted identity/credential overrides, ten redacted OMCI reported metadata fields, eight advanced boot/pin/host fields, and the earlier management/device/PON/VLAN settings. GPIO readback and host link speed are evidence of electrical or link state, not proof a setting functionally applied. Sensitive root password hashes are excluded from this endpoint. See [redacted OMCI reporting](C-011-OMCI-REPORTING-REDACTED.md), [advanced system](C-011-ADVANCED-SYSTEM-READBACK.md), [PON/OMCI](C-011-PON-OMCI-READONLY-READBACK.md) and [ISP/VLAN](C-011-ISP-VLAN-READONLY-EVIDENCE.md).
**r9 integration:** All seven readback groups are included in the 89-file firmware overlay. See [the current release scope](V2R9-INTEGRATED-RELEASE.md).

**Important:** This is a static source inventory, not an assertion that every setting works in the real device. Runtime evidence and platform qualification must be added field by field.

**C-011 ISP/VLAN runtime-evidence extension:** A bounded, authenticated manual readback now supports independently checking the specific built-in kernel TC flower selectors when an exact trusted native reconciliation receipt and unchanged topology are available. This does not expand the count of 27 source-covered settings or establish Internet connectivity or full hardware qualification. The currently tested production stick lacks the requisite receipt. See [the ISP/VLAN evidence contract](C-011-ISP-VLAN-READONLY-EVIDENCE.md).

## Baseline counts

| Domain | Currently exposed firmware-environment controls |
| --- | ---: |
| PON, OLT, OMCI identity and compatibility | 22 |
| ISP service and VLAN | 3 |
| Device, boot and system | 13 |
| SFP EEPROM identity | 7 |
| Management | 9 |
| **Total** | **54** |

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

### 9 management controls

ipaddr, netmask, gateway, dns_server, pingd, ping_ip, lct_mac, reverse_arp, https_redirect.

Test management changes with an independent alternate recovery route. A saved IP or VLAN without active routing and session recovery is not a complete feature.

## Explicitly uncovered or disabled candidates

| Identifier | Current evidence | Next action |
| --- | --- | --- |
| lct_vlan | Field is commented out and the controller marks it broken. Startup helper references it. | Trace UCI interface creation, VLAN tagging, management reachability, restart persistence, reverse recovery and hardware test before enabling |
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

The current source audit supports DISCOVERED and source-side GUI/validation coverage for all 54 controls, **not FULLY_QUALIFIED for any individual field**. Even previously successful manual operations do not substitute for complete per-field test receipts.

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

The separate vNext workspace includes the static source auditor under tools/audit_configurability.py and the 2026-11-02 coverage JSON snapshot. The initial source-only model has 54 fields, 13 UCI domains, and explicitly reports that hardware qualification is incomplete.

A future source update should add each backend and per-platform proof to the registry without silently increasing the count of FULLY_QUALIFIED items.

See the [acceptance and delivery plan](DELIVERY-PLAN-AND-ACCEPTANCE.md).
