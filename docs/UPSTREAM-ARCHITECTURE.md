# AoTT-8311 upstream architecture decision

## Decision

Retain the Potron PTXG_CX_V0.03 vendor base and the community 8311
firmware changes as the PRX126 hardware layer while gradually separating
the web interface and build/release tooling.

The 8311 Basic community release v2.8.3, published September 2025, is
the currently published reference baseline evaluated for AoTT.

## What can be replaced independently

| Layer | Current implementation | Replacement strategy |
| --- | --- | --- |
| SFP+ optical hardware | PRX126, I2C/EEPROM and vendor PON transceiver | Not interchangeable with another chipset vendor |
| Boot/kernel | Vendor U-Boot and Linux 4.9.308+ | Possible long-term port, requires hardware SDK and staged recovery |
| PON datapath and OMCI | MaxLinear source-available drivers and libraries, proprietary OMCI executable and PON microcode | Retain tested PRX126 ABI; review compatible vendor sources separately |
| Network and configuration | OpenWrt netifd, UCI, ubus, firewall | Retain; remove unused packages only after dependency review |
| Web server | uhttpd with Mbed TLS | Keep and audit/backport security fixes before replacing |
| Web interface | LuCI, Lua controllers, JS and CSS | Consider smaller custom interface in a later milestone |
| Telemetry | Local status endpoints and external collector | Keep read-only on stick; collect history on external monitoring |
| Documentation and builders | Repository-only files | Must not enter firmware overlay |

LuCI is a web-application framework, not the PON hardware driver.
MaxLinear is the hardware/SDK provider, not an interchangeable UI
framework. Replacing LuCI does not replace the vendor PON stack.

## Upstream choices considered

1. **8311 Basic based on Potrontec:** best available production baseline
   for this device. Established OMCI/VLAN fixes, proper board support and
   accessible Lua/LuCI source. The live AoTT version uses this family.
2. **Azores/BFW:** historical 8311 alternative, but vendor customization
   and additional components do not offer a clear reliability or image-size
   advantage. Not selected as a new base.
3. **Vanilla modern OpenWrt:** attractive for security and updated kernel
   facilities, but currently lacks a proven fully working PRX126 PON/OMCI
   datapath build matching this module. Not a drop-in replacement.
4. **NIJIKA / Realtek firmware:** separate GPON silicon family; not
   firmware-compatible with PRX126.
5. **Cortina CA8271x firmware:** separate XGS-PON silicon family; not
   firmware-compatible with PRX126.

## MaxLinear public source availability and ABI limitations

The MaxLinear GitHub organization publishes source for several PRX300
components, including pon_lib and pon_net_lib (BSD-2-Clause),
pon_mbox_drv (driver source) and gwdpa-dpm (GPL-2.0). Its feed_pon
package recipes contain PRX300 kernel dependencies, optical mailbox
and SFP I2C drivers.

However, the later gpon_omci_onu_binary package is an executable,
not the OMCI source, and the feed's example targets newer x86 LGM
hardware. The PON microcode remains distributed as vendor binary
files under a separate license. The documented UPDK 9.1.100 prplOS
profiles build for x86 LGM/URX rather than the current MIPS PRX126
Linux 4.9 ABI.

We should study and backport appropriate fixes, not import incompatible
OMCI binaries, overwrite the PRX126 kernel with a newer x86 build, or
claim that all vendor firmware is freely redistributable.

See [External reference projects](EXTERNAL-REFERENCE-PROJECTS.md) for
source locations, component licenses and the direct-compatibility matrix.

## Recommended user-interface direction

Short term: keep LuCI, correct dark-mode accessibility defects and remove
UI modules that are provably irrelevant to PRX126 SFP+ hardware.

Medium term: prototype a lightweight local management UI on top of the
existing uhttpd and authenticated ubus/UCI support, retaining firmware
recovery and local access even if the network is down.

Long term: move historical telemetry, expensive graphical rendering,
documentation and other nonessential features to a remote dashboard.
The stick should expose minimal, authenticated status and management
endpoints. A new API needs explicit authentication, CSRF protection,
input validation, session timeout, rate limits and end-to-end tests.

Do not replace a working management plane with a new front end until
the same functions pass security, migration, offline/recovery and device
tests. Document binary/source provenance and license terms independently.

## Kernel concurrency is a separate problem

The running device reports a {2,2} VPE topology with four logical
processors present, but only CPU0 online. Kernel logs show failed
start attempts for CPU1, CPU2 and CPU3. This behavior may reflect
vendor boot coordination and PON firmware ownership; it is not
evidence that the chip is defective or that enabling SMP will improve
WAN throughput.

Do not force secondary VPEs online on the production stick. A
separate development device, kernel debug symbols, PON recovery
plan and isolated throughput tests are required.

## Source references

- https://github.com/djGrrr/8311-was-110-firmware-builder
- https://www.maxlinear.com/products/access/fiber-access/socs-for-optical-networking-units-onu
- https://openwrt.org/docs/guide-user/services/webserver/http.uhttpd
- https://openpon.org/

This file belongs in GitHub and is not part of the flash image.
