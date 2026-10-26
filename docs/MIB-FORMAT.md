# OMCI MIB template format

The upstream vendor firmware included a short text readme alongside MIB
files in \`/etc/mibs\`. A static readme is not required by the runtime
template selector and belongs in project documentation instead.

Each logical record describes an OMCI managed entity:

\`\`\`text
<class ID> <instance ID> <attribute 1> ... <attribute 16>
\`\`\`

The vendor parser supports a backslash escape for literal spaces
(\`\s\`), a zero-byte escape (\`\0\`), and single or double quotation
for multiword attribute values. Numeric values use decimal by default,
\`0x\` for hexadecimal, and \`0\` for octal.

These conventions describe data files and are not an instruction to
write a live OMCI or OLT configuration.

## Runtime profiles

The PRX126 firmware includes multiple selectable \`.ini\` variants
such as \`prx300_1U.ini\`, \`prx300_2U.ini\`, the 32-TCONT profile and
operator-specific variants. Those \`.ini\` files are actual runtime
inputs, not documentation. They are retained in both production
oriented pruning profiles.

A profile can be valid syntax yet incompatible with a particular OLT.
For example, a profile change that alters the UNI or T-CONT mapping
can cause link loss. Do not default to another profile solely because
it advertises more GEM ports or higher bandwidth.

The build pruner excludes the old static readme but does not delete
the \`.ini\` files or replace operator-specific provisioning.
