#!/usr/bin/env python3
"""Read-only qualification of an extracted vendor fw_printenv, never real flash.

Creates its own CRC-valid ordinary-file environment fixtures. Every invocation
has an explicit private config and lock directory. It does not invoke a setter,
change the supplied rootfs, or conclude that emulation results describe hardware.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import resource
import shutil
import signal
import stat
import struct
import subprocess
import tempfile
import zlib

SIZE = 16384
# Synthetic input only. The deliberately empty value tests lossless observation.
VALUES = {"8311_lct_vlan": "0", "8311_gateway": "", "aott_probe_sentinel": "synthetic-only"}


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def image(redundant: bool, flag: int = 1) -> bytes:
    payload = b"\0".join((k+"="+v).encode() for k,v in VALUES.items()) + b"\0\0"
    payload += bytes(SIZE-(5 if redundant else 4)-len(payload))
    return struct.pack(">I",zlib.crc32(payload)&0xffffffff)+(bytes([flag]) if redundant else b"")+payload


def verify_image(raw: bytes, redundant: bool) -> bool:
    offset=5 if redundant else 4
    return len(raw)==SIZE and struct.unpack(">I",raw[:4])[0]==(zlib.crc32(raw[offset:])&0xffffffff) and b"\0\0" in raw[offset:]


def classify(returncode: int, stdout: str, stderr: str, expected: dict[str,str]) -> str:
    # A zero exit with fallback/default warnings is NOT a usable environment.
    if returncode<0:
        return "NATIVE_READER_SIGNAL_"+str(-returncode)
    if returncode!=0:
        return "NATIVE_READER_FAILED"
    if stderr:
        return "NATIVE_READER_DIAGNOSTIC_OUTPUT"
    rows={}
    for row in stdout.splitlines():
        if "=" not in row:
            return "NATIVE_READER_INVALID_OUTPUT"
        name,value=row.split("=",1)
        if not name or name in rows:
            return "NATIVE_READER_INVALID_OUTPUT"
        rows[name]=value
    if rows!=expected or (stdout and not stdout.endswith("\n")):
        return "NATIVE_READER_CONTENT_MISMATCH"
    return "SYNTHETIC_READER_PASS"


def child_limits() -> None:
    os.umask(0o077)
    resource.setrlimit(resource.RLIMIT_CORE,(0,0))
    resource.setrlimit(resource.RLIMIT_CPU,(5,5))
    resource.setrlimit(resource.RLIMIT_FSIZE,(1048576,1048576))


def native(vendor: Path, qemu: str, work: Path, args: list[str], trace: bool = False) -> dict:
    # U-Boot 2018.03 allocates the -l pathname with sizeof(pointer), not
    # strlen. Use only a fixed short relative directory in our private cwd.
    # Never accept a long absolute lock path or silently fall back to /dev.
    if args not in (["--help"], ["--version"]):
        if args != ["-c", str(work/"fw_env.config"), "-l", "locks"]:
            raise ValueError("Unqualified native reader arguments")
        st=(work/"locks").lstat()
        if not stat.S_ISDIR(st.st_mode) or st.st_uid!=os.geteuid() or stat.S_IMODE(st.st_mode)!=0o700:
            raise ValueError("Unsafe local lock directory")
    # The function can only invoke this one reader binary, never a user command.
    command=[qemu]+(["-strace"] if trace else [])+["-L",str(vendor),str(vendor/"usr/sbin/fw_printenv"),*args]
    try:
        process=subprocess.run(command,cwd=work,stdin=subprocess.DEVNULL,capture_output=True,
            timeout=8,preexec_fn=child_limits,env={"PATH":"/usr/bin:/bin","LANG":"C","HOME":str(work)})
        out,err=process.stdout,process.stderr
        return {"exit_code":process.returncode,"stdout":out.decode(errors="replace"),
                "stderr":err.decode(errors="replace"),"stdout_sha256":sha(out),"stderr_sha256":sha(err),"timed_out":False}
    except subprocess.TimeoutExpired:
        return {"exit_code":124,"stdout":"","stderr":"NATIVE_READ_TIMEOUT","timed_out":True}


def regular_private(path: Path, size: int) -> None:
    st=path.lstat()
    if not stat.S_ISREG(st.st_mode) or st.st_nlink!=1 or st.st_uid!=os.geteuid() or stat.S_IMODE(st.st_mode)!=0o600 or st.st_size!=size:
        raise ValueError("Unsafe private fixture file")


def qualify(vendor_rootfs: Path) -> dict:
    vendor=vendor_rootfs.resolve(strict=True)
    utility=vendor/"usr/sbin/fw_printenv"
    st=utility.lstat()
    if not stat.S_ISREG(st.st_mode) or st.st_size>1048576 or not utility.read_bytes().startswith(b"\x7fELF"):
        raise ValueError("Expected extracted regular ELF reader")
    qemu=shutil.which("qemu-mips-static")
    if not qemu:
        raise ValueError("MIPS interpreter missing")
    utility_hash=sha(utility.read_bytes())
    dependencies={}
    for relative in ("lib/libc.so","lib/libgcc_s.so.1","usr/sbin/fwenv_get","usr/sbin/fwenv_set","lib/8311-env-lock.sh"):
        file=vendor/relative
        if file.exists() and not file.is_symlink() and file.is_file() and file.stat().st_size<=8388608:
            dependencies[relative]=sha(file.read_bytes())
        else:
            dependencies[relative]=None
    with tempfile.TemporaryDirectory(prefix="aott-c014-native-env-probe-",dir="/var/tmp") as directory:
        work=Path(directory);work.chmod(0o700);lock=work/"locks";lock.mkdir(mode=0o700)
        help_result=native(vendor,qemu,work,["--help"])
        version_result=native(vendor,qemu,work,["--version"])
        cases=[]
        for redundant in (False,True):
            for absolute in (False,True):
                for name,flag in (("a",1),("b",0)):
                    p=work/name;p.write_bytes(image(redundant,flag));p.chmod(0o600)
                    regular_private(p,SIZE)
                    if not verify_image(p.read_bytes(),redundant):raise ValueError("Invalid generated CRC fixture")
                names=("a","b") if redundant else ("a",)
                config="".join((str(work/n) if absolute else n)+" 0x0 0x4000 0x4000 1\n" for n in names)
                cfg=work/"fw_env.config";cfg.write_text(config);cfg.chmod(0o600);regular_private(cfg,len(config))
                before={n:sha((work/n).read_bytes()) for n in ("a","b")}
                result=native(vendor,qemu,work,["-c",str(cfg),"-l","locks"])
                unchanged=before=={n:sha((work/n).read_bytes()) for n in ("a","b")}
                state=classify(result["exit_code"],result["stdout"],result["stderr"],VALUES)
                if not unchanged:state="READ_PROBE_MODIFIED_INPUT_REFUSED"
                cases.append({"redundant":redundant,"config_path_form":"absolute" if absolute else "relative",
                    "status":state,"exit_code":result["exit_code"],"input_images_unchanged":unchanged,
                    "generated_crc_verified":True,"timed_out":result["timed_out"],
                    "stdout_sha256":result.get("stdout_sha256"),"stderr_sha256":result.get("stderr_sha256")})
        # One bounded syscall trace locates the failure without returning raw
        # emulator output or any arbitrary filesystem/source data to the caller.
        trace=native(vendor,qemu,work,["-c",str(cfg),"-l","locks"],trace=True)
        opened_config=('open("'+str(cfg)+'",') in trace["stderr"]
        opened_image=any(('open("'+str(work/n)+'",') in trace["stderr"] or ('open("'+n+'",') in trace["stderr"] for n in ("a","b"))
        device_open=any(('open("/dev/'+prefix) in trace["stderr"] for prefix in ("mtd","ubi","mmc","sd"))
        if sha(utility.read_bytes())!=utility_hash:raise ValueError("Supplied vendor utility changed")
    for relative,digest in dependencies.items():
        if digest is not None and sha((vendor/relative).read_bytes())!=digest:
            raise ValueError("Vendor runtime dependency changed during probe")
    passed=all(c["status"]=="SYNTHETIC_READER_PASS" for c in cases)
    version_text=version_result["stdout"]+version_result["stderr"]
    version="2018.03" if "Compiled with U-Boot 2018.03" in version_text else "unclassified"
    return {"schema":2,"status":"SYNTHETIC_READ_PROBE_PASSED" if passed else "BLOCKED_NATIVE_ENVIRONMENT_READER",
        "basis":"EXTRACTED_VENDOR_UTILITY_ON_GENERATED_REGULAR_FILES",
        "lock_argument":"locks","lock_path_relative_to_private_cwd":True,"native_binary_sha256":utility_hash,
        "version_reported":version,"runtime_dependency_sha256":dependencies,"help_exit_code":help_result["exit_code"],"version_exit_code":version_result["exit_code"],
        "cases":cases,"trace":{"exit_code":trace["exit_code"],"config_open_observed":opened_config,
            "environment_image_open_observed":opened_image,"hardware_device_open_observed":device_open,
            "stderr_sha256":trace.get("stderr_sha256")},
        "reader_qualified_for_synthetic_backend":passed,"native_setter_invocations":0,
        "production_activation_allowed":False,"physical_device_tested":False,
        "binary_or_vendor_runtime_modified":False,"fixture_removed":True,
        "interpretation":"Short private lock-path qualification does not authorize a live write or prove physical durability."}


def main() -> int:
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("vendor_rootfs",type=Path)
    args=parser.parse_args()
    try:
        report=qualify(args.vendor_rootfs)
    except (OSError,ValueError,subprocess.SubprocessError):
        print(json.dumps({"status":"QUALIFICATION_INPUT_OR_EXECUTION_REFUSED","production_activation_allowed":False}))
        return 2
    print(json.dumps(report,sort_keys=True,indent=2))
    return 0 if report["reader_qualified_for_synthetic_backend"] else 2


if __name__=="__main__":
    raise SystemExit(main())
