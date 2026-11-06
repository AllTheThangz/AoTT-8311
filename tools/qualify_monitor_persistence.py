#!/usr/bin/env python3
"""Offline prototype for v2r8 durable monitoring configuration.

This tool NEVER accesses /ptconf, rootfs_data, a running ONU, or a firmware
bank. It validates a synthetic record, atomically writes it into a new
temporary directory, and optionally checks real extracted vendor CLI
parsers against disposable UCI configuration files under that directory.

This is research and regression evidence, NOT a boot installer.
"""
import argparse
import ipaddress
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import tempfile

FIELDS = (
    "schema", "log_remote", "log_ip", "log_port", "log_proto",
    "aott_metrics", "aott_metrics_client", "aott_metrics_sha256"
)
SAFE_HOST = re.compile(r"^[A-Za-z0-9.-]{1,253}$")
HEX64 = re.compile(r"^[0-9a-f]{64}$")


def valid_ipv4(value):
    if not isinstance(value, str) or not re.fullmatch(
            r"[0-9]{1,3}(?:\.[0-9]{1,3}){3}", value):
        return False
    if any(len(part) > 1 and part.startswith("0") for part in value.split(".")):
        return False
    try:
        return not ipaddress.IPv4Address(value).is_multicast and (
            0 < int(value.split(".")[0]) < 224)
    except ipaddress.AddressValueError:
        return False


def validate(record):
    if not isinstance(record, dict) or set(record) != set(FIELDS):
        raise ValueError("Unexpected monitoring store field set")
    if record["schema"] != 1 or type(record["schema"]) is not int:
        raise ValueError("Unsupported monitoring schema")
    if any(type(record[k]) is not str for k in FIELDS if k != "schema"):
        raise ValueError("Monitoring options must be bounded strings")
    if record["log_remote"] not in ("0", "1") or record["aott_metrics"] not in ("0", "1"):
        raise ValueError("Invalid monitoring enable flag")
    if record["log_proto"] not in ("udp", "tcp"):
        raise ValueError("Unsupported syslog protocol")
    if not record["log_port"].isdigit() or not 1 <= int(record["log_port"]) <= 65535:
        raise ValueError("Invalid remote logging port")
    ip = record["log_ip"]
    if ip:
        if not SAFE_HOST.fullmatch(ip) or ".." in ip or ip[0] in ".-" or ip[-1] in ".-":
            raise ValueError("Invalid syslog destination")
        if ip.replace(".", "").isdigit() and not valid_ipv4(ip):
            raise ValueError("Invalid IPv4 syslog destination")
        if any(not 0 < len(label) <= 63 or label.startswith("-") or
               label.endswith("-") for label in ip.split(".")):
            raise ValueError("Invalid hostname label")
    if record["log_remote"] == "1" and not ip:
        raise ValueError("Syslog enabled without destination")
    client = record["aott_metrics_client"]
    if client and not valid_ipv4(client):
        raise ValueError("Invalid collector IP")
    digest = record["aott_metrics_sha256"]
    if digest and not HEX64.fullmatch(digest):
        raise ValueError("Invalid stored collector digest")
    if record["aott_metrics"] == "1" and (not client or not digest):
        raise ValueError("Metrics enabled without collector scope")
    return record


def canonical(record):
    validate(record)
    payload = (json.dumps(record, sort_keys=True,
                          separators=(",", ":"), ensure_ascii=True) + "\n").encode()
    if len(payload) > 2048:
        raise ValueError("Monitoring record over size bound")
    return payload


def write_atomic(directory, payload):
    """Operate only on a trusted private scratch directory, never /ptconf."""
    directory = Path(directory)
    if not directory.is_dir() or directory.is_symlink():
        raise ValueError("Unsafe test directory")
    if stat.S_IMODE(directory.stat().st_mode) != 0o700:
        raise ValueError("Unsafe test directory permissions")
    if directory.name == "8311-monitoring" or "/ptconf/" in str(directory):
        raise ValueError("Refusing to modify a device persistence directory")
    destination = directory / "config.json"
    if destination.is_symlink():
        raise ValueError("Symlink configuration file")
    if destination.exists() and (
        not destination.is_file() or destination.stat().st_nlink != 1):
        raise ValueError("Unsafe existing configuration file")
    fd, name = tempfile.mkstemp(prefix=".candidate-", dir=directory)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "wb") as file:
            fd = -1
            file.write(payload)
            file.flush()
            os.fsync(file.fileno())
        os.replace(name, destination)
        dirfd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(dirfd)
        finally:
            os.close(dirfd)
    finally:
        if fd >= 0:
            os.close(fd)
        if os.path.exists(name):
            os.unlink(name)
    return destination


def read_record(path):
    path = Path(path)
    if path.is_symlink():
        raise ValueError("Symlink monitoring store")
    meta = path.stat()
    if not stat.S_ISREG(meta.st_mode) or stat.S_IMODE(meta.st_mode) != 0o600 or (
            meta.st_nlink != 1 or meta.st_size > 2048 or meta.st_uid != os.geteuid()):
        raise ValueError("Invalid persistent file properties")
    raw = path.read_bytes()
    def unique(pairs):
        result = {}
        for k, v in pairs:
            if k in result:
                raise ValueError("Duplicate monitoring field")
            result[k] = v
        return result
    record = json.loads(raw, object_pairs_hook=unique)
    validate(record)
    return record


def synthetic_record():
    return {
        "schema": 1,
        "log_remote": "1",
        "log_ip": "collector.example.com",
        "log_port": "5514",
        "log_proto": "udp",
        "aott_metrics": "1",
        "aott_metrics_client": "192" + ".0.2.40",
        "aott_metrics_sha256": "a" * 64,
    }


def execute_vendor_cli(root, scratch, record):
    root = Path(root)
    uci = root / "sbin/uci"
    jsonfilter = root / "usr/bin/jsonfilter"
    if not uci.is_file() or not jsonfilter.is_file():
        raise ValueError("Vendor UCI and jsonfilter binaries not found")
    import shutil
    if not shutil.which("qemu-mips-static"):
        raise ValueError("qemu-mips-static is required for target validation")
    prefix = ["qemu-mips-static", "-L", str(root)]
    def execute(command):
        r = subprocess.run(prefix + command, text=True,
                           capture_output=True, timeout=12)
        if r.returncode:
            raise RuntimeError("Vendor parser command failed: " + r.stderr[:150])
        return r.stdout.strip()
    encoded = canonical(record).decode()
    for name in ("log_proto", "aott_metrics_client", "aott_metrics_sha256"):
        output = execute([str(jsonfilter), "-s", encoded,
                          "-e", "@." + name])
        if output != record[name]:
            raise RuntimeError("Target JSON parser did not preserve field " + name)

    # A new temporary UCI section simulates freshly generated /etc/config/system.
    conf = scratch / "fresh-config"
    staged = scratch / "uci-stage"
    conf.mkdir(mode=0o700)
    staged.mkdir(mode=0o700)
    (conf / "system").write_text("config system 'cfg0a'\n\toption hostname 'generic-test'\n")
    execute([str(uci), "-c", str(conf), "-p", str(staged),
             "-q", "get", "system.cfg0a.hostname"])
    for field in FIELDS:
        if field == "schema":
            continue
        execute([str(uci), "-c", str(conf), "-p", str(staged),
                 "-q", "set", "system.cfg0a." + field + "=" + record[field]])
    execute([str(uci), "-c", str(conf), "-p", str(staged), "commit", "system"])
    for field in FIELDS:
        if field == "schema":
            continue
        actual = execute([str(uci), "-c", str(conf), "-p", str(staged),
                          "-q", "get", "system.cfg0a." + field])
        if actual != record[field]:
            raise RuntimeError("Target UCI roundtrip mismatch on " + field)
    return True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--vendor-rootfs", type=Path)
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="aott-r8-persist-lab-",
                                     dir="/var/tmp") as temp:
        scratch = Path(temp)
        directory = scratch / "private-record"
        directory.mkdir(mode=0o700)
        record = synthetic_record()
        path = write_atomic(directory, canonical(record))
        assert read_record(path) == record
        disabled = dict(record, aott_metrics="0", aott_metrics_sha256="")
        write_atomic(directory, canonical(disabled))
        assert read_record(path) == disabled
        write_atomic(directory, canonical(record))
        assert read_record(path) == record
        if args.vendor_rootfs:
            execute_vendor_cli(args.vendor_rootfs, scratch, record)
            print("VENDOR_MIPS_UCI_JSON_PERSISTENCE_LAB_PASS")
        print("MONITORING_ATOMIC_SCRATCH_STORE_PASS")
    print("NO_PRODUCTION_PERSISTENT_STORE_OR_FIRMWARE_MODIFIED")


if __name__ == "__main__":
    main()
