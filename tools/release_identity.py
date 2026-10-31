#!/usr/bin/env python3
"""Generate source release labels and verify an independently extracted image.

Only --write-source changes files, and only four generated text files in a
source checkout. Rootfs and archive-control checks are read-only. Hardware
compatibility remains pinned independently of the product revision.
"""
import argparse
import json
from pathlib import Path
import re
import sys

HERE = Path(__file__).resolve().parent.parent
KEYS = {"schema", "product", "version", "revision", "variant", "target",
        "hardware_profile", "status"}


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate canonical release field")
        result[key] = value
    return result


def load_release(source=HERE):
    path = regular_path(source, "release.json")
    if not path.is_file() or path.stat().st_size > 4096:
        raise ValueError("Canonical release metadata must be a bounded regular file")
    spec = json.loads(path.read_text(), object_pairs_hook=unique_object)
    if (not isinstance(spec, dict) or set(spec) != KEYS or
            type(spec["schema"]) is not int or spec["schema"] != 1):
        raise ValueError("Unsupported canonical release metadata")
    fixed = {"product": "AoTT-8311", "variant": "basic", "target": "WAS-110",
             "hardware_profile": "potron-prx126-aott-v1",
             "status": "offline-candidate"}
    if any(spec[k] != value for k, value in fixed.items()):
        raise ValueError("Unqualified release family or hardware profile")
    for key, prefix in (("version", "v"), ("revision", "r")):
        if not isinstance(spec[key], str) or not re.fullmatch(prefix + r"[1-9][0-9]{0,3}", spec[key]):
            raise ValueError("Invalid release version or revision")
    spec["release"] = spec["product"] + "-" + spec["version"] + spec["revision"]
    spec["display"] = spec["product"] + "-" + spec["version"] + " " + spec["revision"]
    return spec


def firmware_fields(spec):
    return {
        "FW_VER": spec["release"],
        "FW_VERSION": spec["release"],
        "FW_LONG_VERSION": spec["release"] + "_" + spec["variant"],
        "FW_REV": spec["revision"],
        "FW_REVISION": spec["revision"],
        "FW_VARIANT": spec["variant"],
        "FW_SUFFIX": "",
    }


def assignments(fields):
    return "".join(key + "=" + value + "\n" for key, value in fields.items())


def generated_files(spec):
    aott = {
        "AOTT_RELEASE": spec["version"][1:],
        "AOTT_NAME": spec["release"],
        "AOTT_AUTHOR": "AoTT",
        "AOTT_VERSION": spec["version"],
        "AOTT_REVISION": spec["revision"],
        "BASE_VERSION": "AoTT-v1",
        "BASE_REVISION": "aott-v1",
        "BASE_PROFILE": spec["hardware_profile"],
        "PROVEN_MAINT5_VERSION": "v2.8.3-maint5",
        "PROVEN_MAINT5_REVISION": "7d89440-m5",
    }
    banner = (
        "------------------------------------------------------------\n"
        " " + spec["display"] + " | LL-XS1010 / PRX126-SFP-PON\n"
        " Firmware author: AoTT\n"
        " Base firmware: AoTT-v1 / v2.8.3-maint5\n"
        " OpenWrt / LEDE / community upstream components retained\n"
        "------------------------------------------------------------\n"
    )
    lua = 'module "8311.version"\n\n' + "".join(
        key + " = " + json.dumps(value) + "\n" for key, value in (
            ("variant", spec["variant"]), ("version", spec["release"]),
            ("revision", spec["revision"]), ("display", spec["display"])))
    return {
        "etc/8311_version": assignments(firmware_fields(spec)),
        "etc/aott_release": assignments(aott),
        "etc/banner": banner,
        "usr/lib/lua/8311/version.lua": lua,
    }


def regular_path(root, relative):
    root = Path(root)
    relative_path = Path(relative)
    if root.is_symlink() or not root.is_dir():
        raise ValueError("Identity root must be a separate regular directory")
    if relative_path.is_absolute() or ".." in relative_path.parts:
        raise ValueError("Invalid relative identity path")
    path = root / relative_path
    current = root
    for part in Path(relative).parts:
        current = current / part
        if current.is_symlink():
            raise ValueError("Symlink in identity path: " + relative)
    return path


def check_files(root, spec):
    for relative, expected in generated_files(spec).items():
        path = regular_path(root, relative)
        if not path.is_file() or path.read_bytes() != expected.encode("utf-8"):
            raise ValueError("Release identity mismatch: " + relative)


def write_source(source=HERE):
    source = Path(source)
    if source.is_symlink():
        raise ValueError("Source checkout cannot be a symlink")
    source = source.resolve()
    if not regular_path(source, "MANIFEST.json").is_file() or not (source / "overlay").is_dir():
        raise ValueError("A source checkout with an overlay and manifest is required")
    spec = load_release(source)
    planned = []
    for relative, content in generated_files(spec).items():
        path = regular_path(source, "overlay/" + relative)
        if path.exists() and not path.is_file():
            raise ValueError("Generated identity destination is not a regular file")
        planned.append((path, content))
    # Discover an unsafe later path before changing any earlier identity file.
    for path, content in planned:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        path.chmod(0o644)
    check_files(source / "overlay", spec)
    return spec


def parse_assignments(path):
    path = Path(path)
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 4096:
        raise ValueError("Identity control must be a bounded regular file")
    raw = path.read_bytes()
    if not raw or any(byte != 10 and not 32 <= byte <= 126 for byte in raw):
        raise ValueError("Unsupported identity control text")
    result = {}
    for line in raw.decode("ascii").splitlines():
        if not line:
            continue
        if "=" not in line:
            raise ValueError("Malformed identity control")
        key, value = line.split("=", 1)
        if key in result or not re.fullmatch(r"[A-Z][A-Z0-9_]*", key):
            raise ValueError("Duplicate or malformed identity field")
        result[key] = value
    return result


def check_control(path, spec):
    fields = parse_assignments(path)
    expected = firmware_fields(spec)
    expected.update(FW_TARGET=spec["target"], FW_PROFILE=spec["hardware_profile"])
    if any(fields.get(key) != value for key, value in expected.items()):
        raise ValueError("Archive control disagrees with canonical release identity")


def check_rootfs(rootfs, source=HERE, control=None):
    original = Path(rootfs)
    rootfs = original.resolve()
    if original.is_symlink() or rootfs == Path("/") or not rootfs.is_dir():
        raise ValueError("An offline extracted rootfs directory is required")
    spec = load_release(source)
    check_files(rootfs, spec)
    profile = regular_path(rootfs, "lib/8311-release-profile").read_text().splitlines()
    for expected in ("profile " + spec["hardware_profile"],
                     "target " + spec["target"], "variant " + spec["variant"]):
        key = expected.split()[0]
        if [line for line in profile if line.startswith(key + " ")] != [expected]:
            raise ValueError("Runtime hardware profile disagrees with release")
    if control is not None:
        check_control(control, spec)
    return {"release": spec["release"], "display": spec["display"],
            "runtime_identity": "passed", "hardware_qualified": False,
            "control_identity": "passed" if control is not None else "not-checked"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=HERE)
    parser.add_argument("--write-source", action="store_true")
    parser.add_argument("--rootfs", type=Path)
    parser.add_argument("--control", type=Path)
    args = parser.parse_args()
    try:
        if args.write_source and (args.rootfs is not None or args.control is not None):
            raise ValueError("Source generation and image verification are separate operations")
        if args.control is not None and args.rootfs is None:
            raise ValueError("Control verification requires an extracted rootfs")
        if args.write_source:
            spec = write_source(args.source)
            result = {"release": spec["release"], "source_identity": "generated"}
        elif args.rootfs is not None:
            result = check_rootfs(args.rootfs, args.source, args.control)
        else:
            spec = load_release(args.source)
            check_files(args.source / "overlay", spec)
            result = {"release": spec["release"], "source_identity": "passed"}
    except (ValueError, OSError) as exc:
        print(json.dumps({"status": "failed", "reason": str(exc)}))
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
