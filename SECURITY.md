# Secret handling and security policy

**Never commit site, subscriber or personal configuration.** This includes:

- Root/password hash databases, boot environment backups, PON serial, PLOAM
  registration ID, LOID/password, WAN passwords, ISP subscriber MAC identity.
- SSH private keys, authorized_keys, known_hosts captured from real devices,
  TLS private keys, exported cert/key bundles and API/OAuth tokens.
- Live /etc/config, /etc/shadow, user passwords, SSH sessions, device backups,
  UBI firmware volumes, Cloudflare configuration and private routing exports.
- Actual production WAN/LAN IP ranges, hostnames or personal domains.

No default root password is supplied. Use a new, unique credential per
device, established by an out-of-repository first-boot workflow. A shared
root/root credential or empty root password is NOT an acceptable default.

This repository intentionally excludes proprietary vendor binary code. Do not
copy a device flash dump into the repo: even a private repository can leak
sensitive material through CI logs, forks and later history.

For every change:

    python3 tools/verify_release.py .
    python3 tools/check_disclosure.py .
    python3 -m unittest discover -s tests -v
    git diff --cached

If credentials were ever committed, assume they are exposed and rotate or
revoke them. Deleting a secret in a later commit does not remove its history.

The read-only status endpoint can report credential configuration state but
must never return hash material. Changes to firewall/SSH, firmware banks,
management routing and PON identity must use independent approval and a
validated recovery route.

## Public assets, screenshots and history

Never publish screen captures, photographs, video, PDFs, exported logs, or
generated diagrams without checking visible content and embedded metadata.
The disclosure gate currently prohibits all such files. This restriction
is intentional until a reviewed image-sanitization process is established.

Never publish actual WAN or management addresses, device MACs, PON serials,
subscriber identifiers, personal domains, login credentials, device-specific
filesystem paths, private hostnames, or device configuration exports.
Use only documentation-reserved examples or parameter names.

Review changes and reachable Git history. Removing a sensitive file from the
current commit does not remove it from prior commits, forks, or CI logs.
A known historical exposure requires independent investigation and rotation.

Upstream copyright and license notices are preserved for attribution. Those
public third-party attributions are distinct from operator and subscriber data.
No screenshots, private backups or complete firmware images are distributed.
