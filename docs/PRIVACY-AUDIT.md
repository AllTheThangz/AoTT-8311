# Public-source privacy and publication gate

This repository intentionally contains a source overlay rather than
personalized, ready-to-flash firmware.

## Prohibited publication content

Do not commit or attach actual public/private site IP addresses, concrete
hardware MACs, PON serials, OLT registration data, LOIDs, passwords, SSH keys,
TLS keys, private hostnames, user contact details, cloud API credentials,
production network exports, copied bank images, logs, or file paths containing
personal account names.

Documentation examples must use reserved documentation networks or
nonfunctional placeholders. The default device setup, if required by an
unmodified upstream file, must be reviewed as a generic factory setting rather
than a private site configuration.

## Screenshots and embedded media

No device screenshots, photos, PDFs, exported dashboards, recorded sessions,
videos or other image-bearing media are present in the distribution.

The automated disclosure gate **fails** when such a file is introduced.
Before enabling media distribution, define a separate review process covering
visible serials, MACs, addresses, credentials, browser URLs, QR codes,
embedded metadata (including EXIF/GPS), image captions, linked thumbnails,
and any cached or historical versions.

Do not assume that removing a visible label also removes embedded metadata.

## Checks required on every change

    python3 tools/verify_release.py .
    python3 tools/check_disclosure.py .
    python3 -m unittest discover -s tests -v

The original release checker validates the curated text overlay, source
manifest, provenance boundaries, and common credential formats.

The disclosure gate adds checks for embedded IP and MAC literals,
subscriber serial patterns, personal contact details, hard-coded hostnames,
credential/key material, sensitive filenames, binary payloads, and media.
Both tools report categories and file/line locations without printing
potential secrets to CI logs.

Automated pattern matching cannot prove the absence of all private data.
Manual diff review, Git history review, dependency/provenance review, and
inspection of every artifact remain mandatory.

## Historical Git objects

A later deletion does not retract prior commits, release downloads, caches,
forks, CI artifacts, or screenshots. If actual secrets or subscriber
identifiers were published, stop distribution, rotate credentials when
appropriate, and perform an independently reviewed exposure response.

Third-party open-source copyright and license notices are preserved.
Those publicly available upstream attributions must not be confused with
subscriber/operator identity or personal provisioning data.

## Release scope

Only the reviewed, allowlisted source and documentation may be published.
The tested proprietary binary image, device backups, runtime provisioning,
host-specific configuration, and other private deployment artifacts are
not part of this repository.
