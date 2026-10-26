#!/usr/bin/env python3
"""Fail-closed source-only distribution audit for AoTT-8311-v2r1.

Not a guarantee that all possible secret formats are detectable. An independent
human git diff/provenance review remains mandatory before public publication.
"""
import hashlib
import json
import pathlib
import re
import sys

RISKY_FILENAMES = re.compile(
    r"(^|/)(?:\.ssh|\.git-credentials|id_ed25519|id_rsa|authorized_keys|"
    r"known_hosts|shadow|boot-environment(?:\.txt)?|ptconf|live-backup|"
    r"flash-dump|device-backup|server\.key)(?:/|$)",re.I)
FORBIDDEN_EXTENSIONS = {
    ".img",".bin",".ubi",".ko",".so",".gz",".tar",".zip",".pem",
    ".crt",".key",".p12",".pfx",".sqlite",".db",".squashfs"
}
SKIP = {".git", "__pycache__"}
FACTORY_IPS = {
    "192.168.11.1", "255.255.255.0", "0.0.0.1",
    "192.0.2.1", "192.0.2.10", "198.51.100.10", "203.0.113.10"
}
IPV4 = re.compile(r"(?<![\w.])(?:\d{1,3}\.){3}\d{1,3}(?![\w.])")
MAC = re.compile(r"(?<![0-9a-f])(?:[0-9a-f]{2}[:-]){5}[0-9a-f]{2}(?![0-9a-f])",re.I)
SIGNATURES = (
    ("private key", re.compile(r"-----BEGIN (?:OPENSSH|RSA|EC|DSA|PGP|ENCRYPTED|PRIVATE) [^-]*KEY-----",re.I)),
    ("GitHub token", re.compile(r"\bgh[pousr]_[A-Za-z0-9_]{28,}\b")),
    ("GitHub fine-grained token",re.compile(r"\bgithub_pat_[A-Za-z0-9_]{35,}\b")),
    ("OpenAI style token",re.compile(r"\bsk-[A-Za-z0-9_-]{30,}\b")),
    ("AWS access ID",re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b")),
    ("Google API key",re.compile(r"\bAIza[0-9A-Za-z_-]{30,}\b")),
    ("SSH public key material",re.compile(r"\bssh-(?:ed25519|rsa)\s+[A-Za-z0-9+/]{65,}={0,2}")),
    ("password hash",re.compile(r"\$(?:1|5|6|y)\$[^\s'\"$]{3,24}\$[A-Za-z0-9./]{30,}")),
    ("URL with inline password",re.compile(r"https?://[^\s/:'\"]+:[^\s/@'\" ]+@",re.I)),
)
# Explicit constant credential fields: ordinary dynamic config code and warning
# messages are not rejected; only hardcoded, non-placeholder literal assignments.
CREDENTIAL = re.compile(
    r"(?im)^\s*(?:export\s+)?(?:DEFAULT_)?(?:ROOT_PASSWORD|"
    r"PON_PASSWORD|LOID_PASSWORD|PLOAM_PASSWORD|API_TOKEN|AUTH_TOKEN|"
    r"GITHUB_TOKEN|CLOUDFLARE_TOKEN|PRIVATE_KEY)\s*[:=]\s*"
    r"['\"]([^\s'\"#;]{6,})['\"]")
EXAMPLE_SECRET = re.compile(
    r"(?im)^DEFAULT_(?:PASSWORD|LOID_PASSWORD|PON_SERIAL|REGISTRATION_ID|LOID)=(\S+)$")
GENERIC_SECRET = re.compile(
    r"(?im)^\s*(?:export\s+)?[a-z_]*(?:password|secret|token|"
    r"api_key)\s*=\s*['\"]([^\s'\"]{8,})['\"]\s*$")

def inspect_text(path, text):
    """Return categorized findings only; do not echo candidate secret values."""
    issues=[]
    for label,rule in SIGNATURES:
        if rule.search(text):
            issues.append(label)
    if MAC.search(text):
        issues.append("literal hardware MAC address")
    for address in IPV4.findall(text):
        if address not in FACTORY_IPS:
            issues.append("unapproved embedded IPv4 address")
            break
    for match in EXAMPLE_SECRET.finditer(text):
        val=match.group(1)
        if not (val.startswith("__") and val.endswith("__")):
            issues.append("non-placeholder factory credential")
    for regex in (CREDENTIAL,GENERIC_SECRET):
        for match in regex.finditer(text):
            val=match.group(1)
            # Docs contain explicit inactive, non-operational placeholders.
            if not (val.startswith("__") and val.endswith("__")):
                issues.append("possible hardcoded credential")
                break
    return sorted(set(issues))

def files_under(root):
    for p in sorted(root.rglob("*")):
        if any(part in SKIP for part in p.relative_to(root).parts):
            continue
        if p.is_symlink():
            yield p, "symlink"
        elif p.is_file():
            yield p, "file"

def check(root):
    root=pathlib.Path(root).resolve()
    if not (root/"MANIFEST.json").is_file():
        raise ValueError("Manifest missing")
    manifest=json.loads((root/"MANIFEST.json").read_text())
    assert manifest.get("release")=="AoTT-8311-v2r1"
    assert manifest.get("source_only") is True
    assert manifest.get("firmware_binaries_included") is False
    entries=manifest["overlay_files"]
    names=[x["path"] for x in entries]
    assert len(set(names))==len(names),"Duplicate overlay path"
    expected={"overlay/"+p for p in names}
    actual={p.relative_to(root).as_posix()
            for p,kind in files_under(root) if p.relative_to(root).parts[0]=="overlay"}
    assert expected==actual,("Unexpected staged source",sorted(expected^actual)[:12])
    count=0; findings=[]
    for file,kind in files_under(root):
        rel=file.relative_to(root).as_posix()
        if kind!="file":
            findings.append((rel,"symlink not permitted in source package"))
            continue
        if RISKY_FILENAMES.search(rel):
            findings.append((rel,"prohibited credential/machine file path"))
        if file.suffix.lower() in FORBIDDEN_EXTENSIONS:
            findings.append((rel,"binary or sensitive extension prohibited"))
        if rel.startswith("overlay/etc/config/") or rel.startswith("overlay/lib/modules/"):
            findings.append((rel,"production config or vendor kernel module"))
        raw=file.read_bytes()
        if b"\0" in raw or len(raw)>1_000_000:
            findings.append((rel,"binary or unexpectedly large source"))
            continue
        try:text=raw.decode("utf-8")
        except UnicodeDecodeError:
            findings.append((rel,"source not UTF-8"))
            continue
        for problem in inspect_text(rel,text):
            # A regex definition in the checker itself is syntax, not an
            # embedded credential; credentials in code still fail by values.
            findings.append((rel,problem))
        count+=1
    for entry in entries:
        p=root/"overlay"/entry["path"]
        if not p.is_file():continue
        if hashlib.sha256(p.read_bytes()).hexdigest()!=entry["sha256"]:
            findings.append((entry["path"],"overlay manifest SHA mismatch"))
        if p.stat().st_size != entry["bytes"]:
            findings.append((entry["path"],"overlay manifest size mismatch"))
        if bool(p.stat().st_mode & 0o111) != entry["executable"]:
            findings.append((entry["path"],"overlay manifest executable-mode mismatch"))
    return count, findings

def main():
    root=pathlib.Path(sys.argv[1]) if len(sys.argv)>1 else pathlib.Path(".")
    try:count,findings=check(root)
    except Exception as ex:
        print("ERROR:",str(ex)[:180],file=sys.stderr)
        return 2
    print("Source files scanned:",count)
    print("Overlay entries:",len(json.loads((root/"MANIFEST.json").read_text())["overlay_files"]))
    if findings:
        print("SANITIZATION FAILED:",len(findings),"finding(s)",file=sys.stderr)
        for path,problem in findings[:50]:
            print(path+": "+problem,file=sys.stderr)
        return 1
    print("SANITIZATION PASS: zero detected secrets, prohibited files or manifest drift")
    print("This is not a legal license audit or a guarantee against unknown secret formats.")
    return 0

if __name__=="__main__":
    raise SystemExit(main())
