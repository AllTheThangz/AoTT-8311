# V3 MIB profile introspection and configuration-driven prompts

## Status

Current `dev/v3` parses the selected runtime OMCI MIB profile instead of
treating the filename as an opaque dropdown value. The capability record is
read-only and is derived from the actual `/etc/mibs/*.ini` file on the
device.

This work does **not** claim that a structurally valid profile is compatible
with a particular OLT. Provider/OLT qualification remains a separate hardware
gate.

## Shipped profile structure

The current private V3 build contains seven runtime profiles. The counts below
are produced by the same parser used by the Configuration page.

| Profile | Parsed topology | Physical UNI relationships | T-CONT ME 262 | Priority Queue ME 277 | Traffic Scheduler ME 278 | IP Host ME 134 | VEIP ME 329 | Single-slot override |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| `prx300_1U.ini` | single UNI | 1 | 16 | 136 | 16 | 1 | 0 | supported |
| `prx300_1U_telus.ini` | single UNI | 1 | 16 | 136 | 16 | 1 | 0 | supported |
| `prx300_1V.ini` | single UNI + VEIP | 1 | 16 | 136 | 16 | 0 | 1 | supported |
| `prx300_1V_32tcont.ini` | VEIP | 0 | 32 | 264 | 32 | 1 | 1 | not safely editable |
| `prx300_1V_bell.ini` | VEIP | 0 | 8 | 72 | 16 | 1 | 1 | not safely editable |
| `prx300_2U.ini` | multi-UNI | 2 | 16 | 144 | 16 | 1 | 0 | not safely editable |
| `prx300_2U_voip.ini` | multi-UNI | 2 | 16 | 144 | 16 | 2 | 0 | not safely editable |

The parser reports the structure that actually exists in the file. It does
not infer capabilities merely from names such as `1U`, `2U`, `Bell`,
`Telus`, `VoIP`, or `32tcont`.

## Configuration-page behavior

The MIB dropdown is now populated with structure-derived labels. Selecting a
profile immediately loads a sanitized capability summary showing:

- profile kind and filename/variant hint;
- physical UNI relationship count and numbers;
- T-CONT, priority queue, and traffic scheduler record counts;
- IP Host ME 134 presence;
- VEIP ME 329 presence;
- conditional-record count;
- whether the single `pon_slot` override is structurally safe.

The form then applies profile-specific rules.

### Profile-native defaults

For the MIB-owned fields that AoTT can safely identify, the parser extracts
the profile-native value for:

- vendor ID;
- reported hardware version;
- circuit-pack hardware-version source;
- equipment ID;
- native UNI slot when a safe single-UNI mapping exists.

A blank AoTT override continues to mean **use the MIB-native value**. The GUI
shows the native value as context/placeholder rather than silently copying it
into the override. This avoids turning an inherited profile default into an
unnecessary persistent override.

### UNI slot

`pon_slot` is editable only when the selected MIB contains one unambiguous
physical UNI-1 slot mapping.

For multi-UNI or topology-incompatible profiles:

- the GUI explains why the slot override is not applicable;
- a saved incompatible slot is not silently carried into a profile change;
- the page offers **Clear incompatible slot override** so the clear is visible
  in the ordinary review diff;
- the server rejects a PON transaction that still carries an incompatible
  slot;
- the guarded worker re-checks the profile before mutation;
- the MIB applicator independently refuses the slot write.

### IP-host identity

`iphost_mac`, `iphost_hostname`, and `iphost_domain` are editable only
when the selected profile contains IP Host Config Data ME 134.

If ME 134 is absent, the fields are marked non-applicable and read-only in the
GUI. Existing saved overrides are preserved rather than silently deleted.
Attempts to change those fields are rejected server-side.

### Other MIB-backed overrides

The server also verifies that the selected profile contains the required
managed entities before allowing changes to:

- vendor ID;
- hardware version;
- circuit-pack hardware-version synchronization;
- equipment ID;
- reported Software Image ME 7 fields.

The seven currently shipped profiles contain the required vendor/hardware and
Software Image structures, but the checks are capability-driven rather than
hard-coded to those filenames.

## Validation boundaries

MIB applicability is enforced at three independent layers:

1. complete Configuration-page preview;
2. guarded PON/OMCI transaction planning;
3. the fixed MIB applicator immediately before profile mutation.

The guarded PON transaction still backs up every installed MIB, UCI state, and
the private PON environment before mutation. It restarts the real `omcid`,
requires local readback and O5.1 convergence, and retains automatic rollback
until authenticated confirmation.

## What this does not prove

The capability parser proves local file structure and whether an AoTT setter
has a structurally valid target. It does not prove:

- that the OLT accepts a profile;
- GEM/data service after registration;
- provider-specific VLAN behavior;
- voice service operation;
- throughput or stability;
- compatibility of another board/stick.

Those remain per-profile hardware qualification tasks. The known-working
reference on the current BRMEMC/PRX126 deployment remains
`prx300_1U.ini` until another profile is separately trialed and accepted.

## Offline qualification checkpoint

The reproducible build source commit is `24535e5b6f4393a2a85a23510c9f59e7997356c1`.
The public equivalent implementation commit is `6d3032002f4d45b46d36130bfcc0ee8bcc5411df`;
both resolve to tree `9c3da927c5e914d7284aadd34b2d58ef990d2a1d`.

- complete source regression: **1,337 tests**, zero failures/errors;
- complete real Chromium regression: **145/145 tests**;
- real seven-profile parser fixture: **121 checks** on host Lua and the extracted vendor-MIPS runtime;
- public-source sanitization: **170 overlay files**, zero detected secrets or manifest drift;
- independent build pair: byte-identical;
- rootfs extent: **5,849,088 bytes**;
- fixed-bank headroom: **372,736 bytes**;
- rootfs SHA-256: `4a7148e6beaf69b9b445b13950eb08f1f584bfbc5cced499d94c2a8b80d626a2`;
- upgrade archive SHA-256: `742398c7c99ec3d07d18bc315d15bcd944666d61a5aa10bb81a8c6606f132af8`.

This is offline/source qualification only. No ONU configuration, firmware bank,
reboot trial, or OLT profile change was performed.
