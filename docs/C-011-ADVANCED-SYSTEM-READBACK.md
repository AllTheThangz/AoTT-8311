# C-011: Advanced device, boot and host link evidence

**Checkpoint:** 2026-11-02. **State:** source-only, not installed on the live
ONU. This milestone follows the management, system/SFP, noncredential
PON/OMCI and ISP VLAN C-011 readbacks.

## Scope

Eight additional advanced, noncredential controls are now covered:

| Existing GUI setting | Saved source | Additional independent observation | Limitation |
| --- | --- | --- | --- |
| `bootdelay` | Unprefixed bootloader environment, integer 0 to 3 | None | A running Linux session cannot verify bootloader timing |
| `uart_select` | Unprefixed bootloader environment, on/off | None | Early UART behavior requires a separately recoverable boot test |
| `console_en` | Prefixed environment, 0/1 | GPIO510 output level | Pin output is not proof the serial console is transmitting |
| `dying_gasp_en` | Prefixed environment, 0/1 | Inverse `optic.common.dg_dis` UCI configuration and GPIO508 output | Neither proves the OLT received a power-loss signal |
| `rx_los` | Prefixed environment, 0/1 | GPIO505 output level and RX_LOS process presence | Alarm pin level and daemon presence do not prove feature application |
| `ethtool_speed` | Prefixed environment, bounded options string | Host `eth0_0` negotiated speed from sysfs | Link speed is not proof that the requested override caused it |
| `failsafe_delay` | Prefixed environment, 0 to 300 seconds | None | The actual OMCI start delay must be timed independently |
| `persist_root` | Prefixed environment, 0/1 | None | Root boot behavior, data preservation and recovery are not proven |

This increases C-011 source-level readback support from **27 to 35 of 54**
existing GUI controls. **19 more remain**. It does not mean the eight
settings are hardware-qualified, and does not qualify the already
covered settings as fully functional.

## Privacy and user experience

The root login password hash is **deliberately excluded** from this
endpoint, including its raw text and any full boot environment dump.
It remains an independently managed sensitive setting, and future
configuration proof must not expose the digest or credentials.
PON identity and subscriber registration data are never read.

The two unprefixed bootloader fields have a distinct getter contract.
Other fields use the normal `8311_` namespace. No browser-supplied
field name can reach a native command.

The authenticated administrator configuration page now provides
a manual **Check advanced hardware settings** button, with:
- Saved override and configured UCI value where separately available.
- GPIO-only pin indications, explicitly marked as such.
- Independently read negotiated host Ethernet speed as a separate
  diagnostic, not an applied speed override.
- RX_LOS daemon presence as a diagnostic, not confirmation of alarm
  signaling.
- Unknown readings when files or commands are unavailable.

It uses plain-text DOM rendering. No periodic browser or on-device
polling loop, custom shell command, network setter, VLAN rule mutation,
firmware-bank action, restart or new privileged background service is
added.

## Files

- `overlay/usr/lib/lua/8311/effective_hardware_state.lua`:
  pure Lua 5.1, side-effect-free normalization and evidence model.
- `overlay/usr/lib/lua/8311/effective_hardware_probe.lua`:
  fixed-key, bounded environment/UCI, sysfs GPIO, link speed and
  process-presence readers. No mutable operations.
- Admin-only GET route
  `/cgi-bin/luci/admin/8311/effective_hardware`, with
  `Cache-Control: no-store, private`.
- Manual LuCI configuration section and a small JavaScript table
  that rejects unsupported claims of fully verified effects.
- Synthetic host/vendor-MIPS fixtures, unit tests and real Chromium
  manual-GET/error/XSS tests.

## Hardware source evidence

The tested PRX126 provides a read-only Ethernet link-speed file,
GPIO status/direction files for pins 508, 510 and 505, and the
`optic.common.dg_dis` UCI option. That establishes the availability
of those read sources, **not** the real-world signaling outcome or
the effectiveness of a stored override.

Do not run a real toggle test on the sole production module without
an independently tested alternate management and recovery path.
The advanced console, pin and persistent-root options could
interrupt serial rescue or host connectivity.

## What remains

- C-011: 19 additional GUI settings, including the sensitive
  root credential override, IP-host and PON/OMCI reported identity,
  firmware image versions and other advanced flags. Readback must
  be credential-safe and hardware-specific.
- C-012: full validated apply, native consumer readback,
  persistence after reboot and recovery tests per setting.
- C-014: management VLAN remains hidden and unqualified.
- H-011: bounded monotonic traffic and optical/ISP connectivity
  history with flash-wear and power-loss safeguards.
- X-010: independent adapters and board qualification for other
  XGS-PON modules.

**Publishing source does not install firmware or alter the running
enhanced-r8 trial.** Original r8 in bank A remains the committed
fallback until a separately authorized permanent commit.
