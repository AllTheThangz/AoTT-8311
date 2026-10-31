# PRX126 SFP ONU resource allocation and unused capacity

All values below describe an audited LL-XS1010 / PRX126-SFP-PON system,
not every board sold under the WAS-110 family. Resource allocation and
bootloader policies may vary by hardware revision or firmware release.

## CPU: four logical processors, only one assigned to Linux

- The kernel discovers VPE topology \`{2,2}\`, with four logical CPU IDs.
- Only CPU0 is online. The other logical CPUs 1, 2 and 3 are offline.
- The captured kernel boot log detects four VPEs but reports that CPU1,
  CPU2 and CPU3 failed to start. It does not by itself establish whether
  those contexts are intentionally firmware-managed or incorrectly
  brought up. Related PRX126 vendor boot logs show similar behavior.
- Investigating the actual device-tree, bootcore SMP handshake and
  vendor kernel behavior requires a nonproduction hardware platform.
- The available Linux CPU runs at a reported 400 MHz.
- MaxLinear advertises wire-speed packet switching in dedicated silicon,
  independent of application CPU processing.

**Do not hot-enable CPUs 1 to 3.** They may be intentionally reserved by
vendor firmware or require different device-tree and bootcore scheduling.
The actual hardware and secondary-CPU roles have not been independently
qualified. This is a separate kernel/bootcore research project.

## RAM: approximately one gigabyte

Read-only \`/proc/meminfo\` from the audited module indicated:

| Measurement | Value |
| --- | ---: |
| MemTotal | 998,676 kB |
| MemAvailable | Approximately 393,500 kB at the time of capture |
| CmaTotal | 573,440 kB, approximately 560 MiB |
| CmaFree | Approximately 46,400 kB |

CMA is the kernel's contiguous memory allocation area, needed for
DMA-capable users such as the vendor network datapath. The CMA pool is
not simply a normal application heap. CMA allocation and ordinary Linux
free-memory statistics overlap in their reporting semantics.

Some free memory is desirable. Linux can use it for cache, new allocations,
and bursts. Filling all RAM would not improve PON throughput.

Never shrink the CMA pool or alter the kernel memory map without a
quantified datapath usage audit and a kernel/driver regression suite.

## SPI NAND and UBI

Physical storage is a 128 MiB Winbond SLC SPI NAND.
The \`system_sw\` MTD partition occupies 108 MiB and contains a UBI
filesystem with the following audited logical volumes.

| Named UBI volume | LEB count | Allocated capacity |
| --- | ---: | ---: |
| kernelA | 18 | 2,285,568 bytes |
| bootcoreA | 43 | 5,459,968 bytes |
| rootfsA | 49 | 6,221,824 bytes |
| kernelB | 18 | 2,285,568 bytes |
| bootcoreB | 43 | 5,459,968 bytes |
| rootfsB | 49 | 6,221,824 bytes |
| rootfs_data | 265 | 33,648,640 bytes |
| ptconf | 48 | 6,094,848 bytes |

A logical eraseblock is **126,976 bytes**. At the time of capture,
307 logical eraseblocks, approximately 37.1 MiB, were unallocated.
An additional number of eraseblocks is reserved for UBI metadata,
bad-block handling and other UBI requirements. Do not treat the entire
128 MiB device as interchangeable filesystem space.

The rootfs images occupy **fixed 49-LEB volumes**. That is why the current
6 MiB class image has roughly 40 KiB remaining even though UBI has tens of
mebibytes that have not been assigned to any volume.

The reported \`/rom\` read-only SquashFS volume showing 100% usage is
expected. In contrast, the writable \`rootfs_data\` UBIFS overlay is
almost unused, and \`ptconf\` stores persistent device configuration.

## Why the firmware does not automatically use the free NAND

- UBI assigns named, fixed-size volumes for each kernel, bootcore and
  rootfs bank. Space is not automatically shared between them.
- The A/B update flow uses each named volume's actual capacity and
  verifies the entire inactive bank before trial boot.
- The bootloader and firmware-recovery contract must understand any
  changed volume geometry.
- Resizing or recreating either rootfs bank can destroy fallback safety
  if done without an independent recovery path.

A theoretical staging scenario would add 32 LEBs to each rootfs
bank, making each rootfs **81 LEBs or 10,285,056 bytes**. That would use
64 additional LEBs and leave about 243 LEBs unallocated in the observed
UBI pool. This is a capacity calculation only, **not an approved
layout change**. Bootcore, kernel, recovery and UBI read/write
compatibility must be tested on separate hardware before any resize.

## Recommended allocation work

1. Keep the current two-bank PON production firmware running.
2. Use an optional, offline compact profile for genuinely unneeded
   components on the PRX126 SFP board.
3. Retain \`omcid\`, \`libcrypto\`, required PON drivers, WAN/VLAN/GEM
   components, SSH, HTTPS, A/B recovery, timezones and selectable MIBs.
4. Investigate increasing rootfsA/B allocation on a disposable test
   device rather than destructively changing production UBI volumes.
5. Investigate device-tree CPU assignments separately from the
   packet-switching silicon and vendor firmware, never as a toggle.

### References

- PRX126 product features:
  https://www.maxlinear.com/product/access/fiber-access/socs-for-optical-networking-units-onu/prx126
- Vendor PRX126 boot behavior:
  https://pon.wiki/xgs-pon/ont/potron-technology/x-onu-sfpp/
