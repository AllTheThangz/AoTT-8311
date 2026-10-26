# AoTT-8311 firmware compatibility

## Verified hardware

**Directly qualified on one live device**

- OEM/Potron LL-XS1010 XGS-PON SFP+ ONU, board identity PRX126-SFP-PON.
- MaxLinear PRX126 / PRX300 revision 1.3, MIPS32r2 big-endian.
- Potron PTXG_CX_V0.03 firmware line and compatible kernel 4.9.308+.
- Winbond WN25N01GV 1-Gbit SLC SPI NAND and approximately 1 GB RAM.
- The tested dual-bank UBI partition names and component hashes.
- XGS-PON O5.1 registration and 10G host Ethernet link were confirmed
  on the tested unit. AoTT-8311-v2r1 is committed to bank A.

The current source overlay and installation contract are tied to this
board and vendor ABI. **An archive header with the string WAS-110 is not
a declaration that every WAS-110 or PRX126 device is compatible.**
The original archive validator also pins a specific kernel and bootcore
SHA-256 profile. A matching SoC alone is insufficient.

## Compatibility candidates, not directly qualified

| Device family or reseller | SoC | AoTT status |
| --- | --- | --- |
| OEM/Potron LL-XS1010, PRX126-SFP-PON with matching bootcore, kernel and UBI layout | MaxLinear PRX126 | Verified on one device |
| Azores / BFW Solutions WAS-110 and compatible 8311 community units | MaxLinear PRX126 | Candidate for separate board and image qualification, not directly verified |
| Potron X-ONU-SFPP resellers, some FiberMall and Yunvo variants | MaxLinear PRX126 on applicable revisions | Candidate only; confirm exact PCB/bootloader and image ABI |
| E.C.I. Networks EN-XGSPP-OMAC **V2** | MaxLinear PRX126 | Candidate only; version matters |
| LuLeey LL-XS1025 / other PRX126-based ONU variants | MaxLinear PRX126 on applicable revisions | Candidate only |
| FS.com XGS-SFP-ONT-MAC-I, specifically verified PRX126 variants | MaxLinear PRX126 | Candidate only; vendor firmware branch may differ |

Do not equate reseller product names with confirmed chipset or firmware
compatibility. A seller may change the internal PCB, optical module, EEPROM,
NAND or bootloader without changing the marketing name.

## Not compatible with this firmware image

| Hardware | Reason |
| --- | --- |
| FS.com XGS-ONU-25-20NI, CIG XG-99S | Different SoC and boot/flash layout |
| E.C.I. Networks EN-XGSPP-OMAC **V1** | Different Cortina chipset, not the V2 PRX126 |
| Leox LXE-010X-A, RTL9615C variants | Different Realtek SoC and runtime ABI |
| RTL9601 / RTL960x GPON sticks | Different silicon, GPON firmware and boot contract |
| CIG, Broadcom, Cortina or other vendor ONUs | No corresponding AoTT board/driver/toolchain port |
| GPON-only, EPON-only and unrelated SFP+ transceivers | Wrong optics, protocol or management platform |

A physical SFP+ fit or the ability to negotiate 10Gbps Ethernet does not
establish firmware compatibility or authorize an OLT service profile.

## Pre-install acceptance checklist for any new device

1. Identify the PCB/SoC family, chip revision, bootloader and vendor
   firmware branch without printing subscriber identifiers.
2. Verify CPU architecture, endianness, board-compatible device tree,
   PON microcode and OMCI library ABI.
3. Verify NAND page/erase geometry, logical UBI eraseblock size,
   expected named A/B volumes and actual capacity.
4. Verify kernel and bootcore SHA-256 values against a qualified build.
   Do not replace them because a product label seems similar.
5. Verify a complete, off-device recovery image for both banks, along
   with a working management or serial recovery path.
6. Assemble and test the image offline. Install only on a separately
   approved hardware test target, with WAN and PON regression checks.

These checks do not require or justify copying someone else's serial,
MAC address, PLOAM registration, LOID or provider credentials.

## Sources

- Potron X-ONU-SFPP hardware:
  https://pon.wiki/xgs-pon/ont/potron-technology/x-onu-sfpp/
- Azores/BFW WAS-110:
  https://pon.wiki/xgs-pon/ont/bfw-solutions/was-110/
- E.C.I. V2 versus V1 chipset distinction:
  https://hack-gpon.org/xgs/ont-ECIN-EN-XGSFPP-OMAC-v2/
- FS.com XGS-ONU-25-20NI:
  https://hack-gpon.org/xgs/ont-fs-XGS-ONU-25-20NI/
- PRX126 SoC:
  https://www.maxlinear.com/product/access/fiber-access/socs-for-optical-networking-units-onu/prx126
