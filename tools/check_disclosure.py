#!/usr/bin/env python3
"""Fail-closed public-source privacy gate.

Reject embedded subscriber/network identifiers, credentials, and unreviewed
screen captures or binary artifacts. No match value is printed to stdout.
Third-party LuCI copyright notices are preserved for license compliance.

This is a defense-in-depth static check, not a substitute for reviewing every
proposed change, release artifact, Git history, or redacted screenshot.
"""
import ipaddress
import json
import pathlib
import re
import sys

DISALLOWED_MEDIA = {
    ".png", ".jpg", ".jpeg", ".webp", ".gif", ".svg", ".tif", ".tiff",
    ".bmp", ".heic", ".pdf", ".mp4", ".mov", ".webm", ".avif",
}
DISALLOWED_ARCHIVES = {
    ".img", ".bin", ".squashfs", ".ubi", ".tar", ".gz", ".zst",
    ".zip", ".7z", ".pcap", ".pcapng", ".sqlite", ".db", ".pem",
    ".p12", ".pfx", ".key", ".crt", ".der", ".ko", ".so",
}
DISALLOWED_PATH = re.compile(
    r"(?i)(?:^|/)(?:\.ssh|\.env(?:\.[^/]*)?|id_ed25519|id_rsa|"
    r"known_hosts|authorized_keys|shadow|ptconf|live-backups?|"
    r"subscriber|flash-dump|device-backup|network-export)(?:/|$)"
)
IPV4 = re.compile(r"(?<![\w.])(?:\d{1,3}\.){3}\d{1,3}(?![\w.])")
MAC = re.compile(r"(?<![a-fA-F0-9])(?:[a-fA-F0-9]{2}[:-]){5}[a-fA-F0-9]{2}(?![a-fA-F0-9])")
EMAIL = re.compile(r"\b[A-Za-z0-9_.+%-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
HOST = re.compile(r"(?<![\w./-])(?:[A-Za-z0-9-]+\.)+[A-Za-z]{2,}(?![\w.-])")
USER_HOME = re.compile(r"/(?:home|Users)/[A-Za-z0-9._-]+/")
PHONE = re.compile(r"(?<![A-Za-z0-9])(?:\+?1[-. ]?)?\(?[2-9]\d{2}\)?[-. ]+[2-9]\d{2}[-. ]+\d{4}(?![A-Za-z0-9])")
ONU_ID = re.compile(r"\b(?:ADTN|HWTC|ALCL|ZTEG|NOKI)[a-fA-F0-9]{8}\b")
KEY_MATERIAL = (
    re.compile(r"-----BEGIN (?:OPENSSH|RSA|EC|DSA|ENCRYPTED|PRIVATE) [^-]*KEY-----", re.I),
    re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9_]{28,}|github_pat_[A-Za-z0-9_]{35,})\b"),
    re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b|\bAIza[A-Za-z0-9_-]{30,}\b"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{30,}\b"),
    re.compile(r"\bssh-(?:ed25519|rsa)\s+[A-Za-z0-9+/]{65,}={0,2}"),
    re.compile(r"\$(?:1|5|6|y)\$[^\s'\"$]{3,24}\$[A-Za-z0-9./]{30,}"),
    re.compile(r"https?://[^\s/:@'\"]+:[^\s/@'\"]+@", re.I),
)
# These are TEST-NET documentation ranges, not allocated subscriber addresses.
def dotted(*octets):
    return ".".join(str(value) for value in octets)

DOCUMENTATION_NETS = tuple(
    ipaddress.ip_network(dotted(*prefix, 0) + "/24")
    for prefix in ((192, 0, 2), (198, 51, 100), (203, 0, 113))
)
# Generic factory/network constants only, generated without embedded IP literals.
FACTORY_VALUES = {
    dotted(*address) for address in (
        (192, 168, 11, 1), (255, 255, 255, 0), (0, 0, 0, 0),
        (0, 0, 0, 1), (127, 0, 0, 1),
    )
}
REFERENCE_HOSTS = {
    "github.com", "www.github.com", "openwrt.org", "www.openwrt.org",
    "hack-gpon.github.io", "pool.ntp.org",
    "example.com", "example.net", "example.org", "fs.com",
    "creativecommons.org", "www.w3.org",
    "midlink.org", "mein.io", "nut-bolt.nl",
    "daemon.info", "now.dev", "held.dev", "opened.dev", "st.dev",
}
REFERENCE_SUFFIXES = (".github.com", ".github.io", ".openwrt.org", ".example.com", ".example.net", ".example.org")
DOMAIN_TLDS = {"com", "org", "net", "io", "gov", "edu", "dev", "app", "cloud",
               "co", "uk", "nl", "de", "info", "me", "us", "ca", "au", "tech"}
THIRD_PARTY_NOTICE_FILES = {
    "overlay/usr/lib/lua/luci/view/admin_status/index.htm",
    "overlay/usr/lib/lua/luci/view/themes/bootstrap/header.htm",
}
THIRD_PARTY_NOTICE_DOMAINS = {"midlink.org", "mein.io", "openwrt.org", "nut-bolt.nl"}

def upstream_notice(path, line, mail):
    if path not in THIRD_PARTY_NOTICE_FILES:
        return False
    if not re.search(r"(?i)copyright\s+[0-9]{4}", line):
        return False
    return mail.rsplit("@", 1)[-1].lower() in THIRD_PARTY_NOTICE_DOMAINS

def check_text(relative, text):
    """Return (category, 1-based line) findings. Never include matched values."""
    errors = set()
    def flag(category, offset):
        errors.add((category, text.count("\n", 0, offset) + 1))
    for match in IPV4.finditer(text):
        try: addr = ipaddress.IPv4Address(match.group())
        except ValueError: continue
        if str(addr) in FACTORY_VALUES or any(addr in block for block in DOCUMENTATION_NETS):
            continue
        flag("embedded_site_or_public_ipv4", match.start())
    for pattern, label in (
        (MAC, "hardware_mac_address"), (PHONE, "telephone_number"),
        (ONU_ID, "subscriber_onu_identity"),
        (USER_HOME, "personal_home_directory"),
    ):
        for match in pattern.finditer(text):
            flag(label, match.start())
    for pattern in KEY_MATERIAL:
        for match in pattern.finditer(text):
            flag("credential_or_key_material", match.start())
    copyright_email_spans = set()
    for match in EMAIL.finditer(text):
        start = text.rfind("\n", 0, match.start()) + 1
        line = text[start:text.find("\n", match.start()) if "\n" in text[match.start():] else len(text)]
        if upstream_notice(relative, line, match.group()):
            copyright_email_spans.add(match.start())
        else:
            flag("embedded_personal_email", match.start())
    for match in HOST.finditer(text):
        host = match.group().lower()
        if host.rsplit(".", 1)[-1] not in DOMAIN_TLDS:
            continue
        if host in REFERENCE_HOSTS or host.endswith(REFERENCE_SUFFIXES):
            continue
        # A LuCI dotted property can have .info without being a hostname.
        if host.startswith("luci.") and host.endswith(".info"):
            continue
        if match.start() and text[match.start()-1] == "@":
            start = match.start()
            if any(abs(start - previous) < 100 for previous in copyright_email_spans):
                continue
        flag("unreviewed_hostname_or_domain", match.start())
    return sorted(errors)

def scan(root):
    root = pathlib.Path(root).resolve()
    issues = []
    scanned = 0
    for file in sorted(root.rglob("*")):
        relative = file.relative_to(root)
        if ".git" in relative.parts or "__pycache__" in relative.parts:
            continue
        name = relative.as_posix()
        if file.is_symlink():
            issues.append((name, "symlink_not_allowed", 0))
            continue
        if not file.is_file():
            continue
        scanned += 1
        if DISALLOWED_PATH.search(name):
            issues.append((name, "private_or_sensitive_filename", 0))
        if file.suffix.lower() in DISALLOWED_MEDIA:
            issues.append((name, "screenshot_or_media_requires_separate_review", 0))
        if file.suffix.lower() in DISALLOWED_ARCHIVES:
            issues.append((name, "binary_or_archive_forbidden", 0))
        if file.stat().st_size > 1_000_000:
            issues.append((name, "oversized_file", 0))
            continue
        raw = file.read_bytes()
        if b"\0" in raw:
            issues.append((name, "binary_data", 0))
            continue
        try: text = raw.decode("utf-8")
        except UnicodeDecodeError:
            issues.append((name, "non_utf8_content", 0))
            continue
        for label, line in check_text(name, text):
            issues.append((name, label, line))
    return scanned, issues

def main():
    root = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else ".")
    try: count, problems = scan(root)
    except (ValueError, OSError) as err:
        print("DISCLOSURE CHECK ERROR:", type(err).__name__, file=sys.stderr)
        return 2
    print("Public source files examined:", count)
    if problems:
        print("DISCLOSURE GATE FAILED:", len(problems), "finding(s)", file=sys.stderr)
        for path, label, lineno in problems[:60]:
            print("{}:{}: {}".format(path, lineno, label), file=sys.stderr)
        return 1
    print("DISCLOSURE GATE PASS: no detected subscriber identifiers, embedded network addresses, credentials or unreviewed media")
    print("Third-party copyright attributions are retained; manual review of Git history and provenance is still necessary.")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
