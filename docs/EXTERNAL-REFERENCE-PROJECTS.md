# External reference projects and upstream eligibility

This page documents five reference sources evaluated for AoTT-8311.
A link to another vendor's firmware does not establish that it is
compatible with the PRX126-SFP-PON board or legally redistributable.

## Reference matrix

| Reference | Hardware and purpose | AoTT use | Directly flashable on PRX126? |
| --- | --- | --- | --- |
| YuukiJapanTech/CA8271x | Cortina CA8271x/CA8289 reverse engineering, XGS-PON and 10G-EPON | Compare PON mode, diagnostics, serial interface and recovery design | No |
| hack-gpon/hack-gpon.github.io | Community ONT chipset/device reference and recovery wiki | Check board identity and management methods | No, documentation only |
| HikaruChang/8311-was-110-firmware-builder | Continued 8311 firmware for MaxLinear PRX126 | Best additional source for selective 8311 reliability fixes | Only after exact AoTT integration and hardware qualification |
| akhamar/orange-xgs-pon | Orange Livebox bypass guides for three distinct ONU families | Compare OLT provisioning, VLAN and host-switch considerations | No, operator-specific documentation |
| maxlinear GitHub organization | Original vendor SDK source, PON libraries, kernel drivers and binary firmware | Long-term platform research and source-based bug fixes | No verified replacement PRX126 image |

### CA8271x

YuukiJapanTech's project focuses on CA8271S (Cortina/Saturn)
and CA8289 hardware. The CIG XG-99S, FS.com CIG-derived sticks
and many Hisense devices have a different SoC and often a
different firmware format from the LL-XS1010 PRX126.

We can study hardware identification, PON diagnostics and
conservative recovery design without copying their binaries,
NAND images, credentials or hardware-specific device trees.
The project is GPL-3.0 licensed, so source reuse also requires
a deliberate licensing and attribution decision.

Project: https://github.com/YuukiJapanTech/CA8271x

### Hack GPON

This is a documentation/wiki project, hosted historically at
hack-gpon.github.io and now browsable at hack-gpon.org. Its
catalog is useful for identifying actual chipset families
behind reseller names and avoiding unsafe cross-flashing.

It is not an executable firmware image or compatible
bootloader replacement.

Project: https://github.com/hack-gpon/hack-gpon.github.io

### HikaruChang 8311 community continuation

Version 2.8.3-CN5 was released on October 14, 2026. It merges
the original 8311 v2.8.3 baseline and adds OMCI supervision,
trial connectivity rollback, quieter ping logging and
polling-loop refinements.

The AoTT-v2r1 extracted omcid SHA-256 exactly matches the
CN5 patched-output hash for the Potrontec 1.18.1 OMCI binary:

    4bed8e6a43ed693da8382d3c128cece3b3eac66664452875f291b25df04eb2d6

Therefore the particular CN5 timer-overflow binary patch is
already present. Do not repatch that binary, assume a newer
OMCI ABI, or replace the whole firmware with CN5.

AoTT's A/B state machine has its own explicitly authorized
commit and verified-bank recovery requirements. Before adding
CN5 crash supervision or trial guards, review all interactions
to prevent two independent services from issuing conflicting
reboots or boot-environment changes.

Projects:
- https://github.com/HikaruChang/8311-was-110-firmware-builder
- https://github.com/HikaruChang/8311-was-110-firmware-builder/releases/tag/2.8.3-CN5

### Orange XGS-PON guide

The Orange-specific project documents WAS-110 PRX126, CIG XG-99S
CA8271S and Leox RTL9615C as separate supported ONT options for
its operator scenario. The guide emphasizes host power budgets,
module compatibility and provider-side service provisioning.

It is not a portable firmware implementation and the Orange
VLAN/network settings must never be assumed to apply to other
Internet providers.

Project: https://github.com/akhamar/orange-xgs-pon

### MaxLinear public source and SDK

This is the most important longer-term research source.
MaxLinear publishes several distinct components:

| Repo | What it provides | Source/license note |
| --- | --- | --- |
| maxlinear/pon_lib | PON library source and CLI | BSD-2-Clause |
| maxlinear/pon_net_lib | Datapath and PON network library source | BSD-2-Clause |
| maxlinear/pon_mbox_drv | PON mailbox, Ethernet and PTP kernel drivers | Component licenses require review |
| maxlinear/gwdpa-dpm | Hardware datapath kernel module source | GPL-2.0 |
| maxlinear/feed_pon | PRX300 and LGM package build definitions | Per-package licensing |
| maxlinear/pon_firmware_binary | PON microcode/firmware images | Proprietary license |
| maxlinear/gpon_omci_onu_binary | OMCI executable binaries, not the OMCI C source | Proprietary license |
| maxlinear/mxl_prplos_profiles | New prplOS/UPDK build configurations | Current documented examples target x86 LGM/URX hardware |

The newer UPDK 9.1.100 README documents OpenWrt 23.05-based
prplOS profiles for newer x86 platforms. This is not the same
MIPS big-endian PRX126 firmware target as our Linux 4.9.308+
PTXG_CX_V0.03 stick. Its firmware, kernel, device tree and
OMCI binaries must not be dropped into our current image.

The vendor's feed_pon PRX300 package definitions are promising
for rebuilding specific sources using an appropriate toolchain.
The available OMCI package targets the newer LGM x86 platform,
however, and the existing 8311 build uses a different older
binary ABI. A source-available driver is not equivalent to a
verified full open firmware stack.

Repos:
- https://github.com/maxlinear/pon_lib
- https://github.com/maxlinear/pon_net_lib
- https://github.com/maxlinear/pon_mbox_drv
- https://github.com/maxlinear/gwdpa-dpm
- https://github.com/maxlinear/feed_pon
- https://github.com/maxlinear/pon_firmware_binary
- https://github.com/maxlinear/gpon_omci_onu_binary
- https://github.com/maxlinear/mxl_prplos_profiles

## Web-interface alternatives

LuCI is not a dependency of the optical datapath. The
device could eventually use a smaller browser UI built
from HTML/CSS and client JavaScript while retaining UCI,
ubus, authenticated HTTPS and the existing validated
configuration/flash operations.

Removing the LuCI frontend alone does not remove its
runtime modules or reduce the firmware significantly.
A true replacement needs inventory of every LuCI route,
login/auth/CSRF protections, required Lua bindings and
failsafe recovery features before packages are removed.

A new static app might save image space, but would be a
separate, higher-risk development release. It must not
replace the working production UI without feature parity,
penetration testing and rollback qualification.

## Priority

1. Keep the proven Potron/MaxLinear PRX126 hardware layer.
2. Selectively incorporate reviewed CN5 source fixes
   that do not conflict with AoTT's firmware-bank policy.
3. Build and test the compact PRX126 profile with a
   fixed inventory of absent DSL/Wi-Fi pages and Nano.
4. Audit vendor binary patch levels and source licenses.
5. Prototype a minimal authenticated management interface
   separately while leaving the current LuCI in production.
6. Investigate an SDK-based PRX126 kernel rebuild on spare
   hardware with UART/bootloader rescue available.

No external firmware image, credentials, or device dump
should be checked into the public AoTT source repository.
