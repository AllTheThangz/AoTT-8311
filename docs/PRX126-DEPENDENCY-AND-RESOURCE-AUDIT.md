# PRX126 runtime dependency and resource audit

Status: Read-only audit of the Potron PTXG_CX_V0.03 AoTT-8311-v2r1 rootfs
and one OEM LL-XS1010. No other hardware is qualified.

This documentation and the accompanying source audit tool are GitHub-only.
They are not copied into the ONU firmware rootfs.

## Offline dependency report

Run from a trusted build host:

    python3 tools/audit_rootfs_dependencies.py --rootfs /path/to/CLEAN-PRX126-rootfs --output summary

The command reads existing files and ELF metadata; it does not modify an
image, contact an ONU, or emit subscriber identifiers and credentials. It
rejects the host root filesystem and unrecognized vendor-family images.

| Measurement | Verified result |
| --- | ---: |
| MIPS32 big-endian userspace ELF objects scanned | 157 |
| Distinct direct ELF library SONAMEs | 41 |
| Unresolved library SONAMEs | 0 |
| Exact duplicate-content file groups | 65 |
| Redundant unpacked file bytes | 321,713 |
| Static MIB readme in vendor rootfs | 407 bytes |

The duplicate byte count is an unpacked value. SquashFS deduplicates
identical content and XZ compresses it. Replacing duplicate libraries with
hardlinks did not reduce the measured compressed image size.

Static linking evidence cannot detect every runtime use. Conditional
kernel modules, OMCI callbacks, late loading, scripts, LuCI imports,
recovery utilities and OLT-specific MIBs must be checked independently.

## Confirmed components to retain

- OMCI requires OpenSSL libcrypto.so.1.1, and a running omcid process was
  observed loading that library. Its removal is not authorized.
- The HTTPS stack loads libustream-ssl.so, which links Mbed TLS. Retain
  the runtime TLS engine and supporting trust/certificate functionality.
- The reverse-ARP helper calls tcpdump. The executable dynamically links
  libpcap.so.0.8, so both are retained in normal builds.
- Keep the kernel, bootcore, PON microcode, optics calibration, MIB
  profiles, VLAN/GEM support, SSH/HTTPS recovery, and A/B safety tooling.
- All supported MIB templates and timezone definitions remain usable
  configuration options. Inactivity during one boot is not proof that
  those features are unused by another provider.

OpenSSL libssl.so.1.1 has no direct ELF consumer in the extracted rootfs
and no mapped process observed during one live snapshot. Its exclusion
remains experimental until delayed library loading and additional vendor
modes are proven safe.

## Compact PRX126-only user interface

The wireless realtime LuCI route is guarded by the presence of a
wireless-device UCI configuration. The tested PRX126 SFP board has no
wireless configuration or hardware. The compact profile excludes the
standalone wireless status page and its two SVG assets in addition to
the existing DSL and Wi-Fi Overview includes, Nano, and the MIB readme.

The profile planner refuses this operation if wireless configuration is
present, if the menu dependency disappears, or if the SVG import contract
changes. Shared LuCI libraries and PON functionality remain untouched.

The three extra files are genuinely unnecessary for this specific SFP
board but their removal does not change the 4 KiB-aligned compressed image
size. The compact rootfs remains about 6.13 MB with roughly 92 KiB free.
It is offline-qualified only and has not been installed.

## RAM capacity and packet-buffer reservation

Linux reports 998,676 kB of usable memory, with CMA pool reservations
of 48 MiB and 512 MiB, totaling 573,440 kB. Boot logs associate the
larger DMA pool with the PON/network queue manager.

Around 393 MiB was MemAvailable at the sampled time. Contiguous DMA
memory and the Linux free/page-cache accounting are not entirely
separate capacity buckets. Filling the remaining memory would not
increase OLT-provisioned PON throughput and could impair recovery.

## Secondary CPU startup

The PRX126/PRX300 exposes a four-VPE topology. Linux starts only CPU0,
reports failed startup of CPU1, CPU2 and CPU3, and runs CPU0 at the
reported maximum of 400 MHz in performance mode. Whether secondary
VPEs are intentionally reserved, firmware-coordinated or broken cannot
be established without vendor kernel/device-tree and bootcore debugging.

The optical datapath has dedicated forwarding/DMA hardware. Linux SMP
startup is not equivalent to the provider's T-CONT/GEM service capacity.
Do not force-enable secondary CPUs on the production stick.

## SPI NAND, rootfs and free UBI capacity

The physical NAND is 128 MiB, including a 108 MiB system software
partition. UBI has 307 currently unallocated logical eraseblocks,
about 37.1 MiB, but the read-only rootfsA and rootfsB volumes are
each limited to 49 LEBs, or 6,221,824 bytes. The writable rootfs_data
is a separate 265-LEB volume and ptconf is a separate 48-LEB volume.

This explains why the full compressed rootfs has only 40 KiB of
available bank capacity despite significant free physical NAND.
Changing volume geometry alters the boot/recovery contract. Do not
resize production UBI volumes without a qualified spare device,
complete backups, verified bootloader support, and tested rollback.

## Documentation boundary

Static manuals, MIB-format notes, compatibility tables, build scripts,
source comments and release guides belong in GitHub. The vendor's
407-byte MIB readme is excluded from the optimized runtime image.

Runtime UI labels, necessary error/warning messages, MIB data, zoneinfo,
protocol configuration and integrity profiles are software functionality,
not disposable documentation. Removing them would degrade configurability
or eliminate essential recovery feedback.

## Further qualification

1. Retain an audited full profile as a reference.
2. Confirm that compact images pass the runtime integrity profile,
   source manifest, SquashFS validation and WAN/PON regression tests.
3. Test any additional removal across all supported MIB and networking
   modes, including delayed library loads and reverse ARP.
4. Validate other PRX126 boards independently before claiming support.
5. Investigate bootcore-managed SMP and optional UBI resizing on
   separate recoverable hardware.

No live firmware, credentials, MAC addresses, PON serials, or bank
configuration are modified or distributed by this audit.
