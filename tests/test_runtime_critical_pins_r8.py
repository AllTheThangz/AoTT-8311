"""Prove r8 security-critical runtime files must be pinned before staging."""
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
FILE=ROOT/"tools/refresh_runtime_profile.py"
spec=importlib.util.spec_from_file_location("r8_runtime_profile_checker",FILE)
profile=importlib.util.module_from_spec(spec)
spec.loader.exec_module(profile)


class R8RuntimeCriticalPinTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix="aott-r8-profile-test-")
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)/"rootfs"
        self.root.mkdir()
        self.items={}
        for name in profile.R8_CRITICAL_FILES:
            f=self.root/name
            f.parent.mkdir(parents=True,exist_ok=True)
            f.write_bytes(("synthetic-pin:"+name+"\n").encode())
            if name.startswith(("etc/init.d/","usr/libexec/")):
                f.chmod(0o755)
            self.items[name]=(f.stat().st_size,hashlib.sha256(f.read_bytes()).hexdigest())
        for name,target in profile.R8_CRITICAL_LINKS.items():
            f=self.root/name
            f.parent.mkdir(parents=True,exist_ok=True)
            f.symlink_to(target)
        # Keep the standard >=11-entry validator independent of the r8 rule.
        for name in ("etc/openwrt_release","etc/inittab"):
            f=self.root/name
            f.parent.mkdir(parents=True,exist_ok=True)
            f.write_text("synthetic-common\n")
            self.items[name]=(f.stat().st_size,hashlib.sha256(f.read_bytes()).hexdigest())
        self.manifest=Path(self.temp.name)/"source-manifest.json"
        self.manifest.write_text(json.dumps({
            "revision":"r8", "source_only":True,
            "firmware_binaries_included":False,
            "overlay_files":[{"path":name,"bytes":size,"sha256":sha}
                             for name,(size,sha) in self.items.items()
                             if name in profile.R8_CRITICAL_FILES]
        }))
        self.profile=self.root/"lib/8311-release-profile"
        self.profile.parent.mkdir(parents=True)
        header=[
            "profile potron-prx126-aott-v1",
            "target WAS-110",
            "variant basic",
        ]
        for name,(size,sha) in profile.QUALIFIED_COMPONENTS.items():
            header.append(f"component {name} {size} {sha}")
        lines=header[:]
        for name,(size,sha) in self.items.items():
            scope="candidate" if name in profile.R8_CRITICAL_FILES else "common"
            lines.append(f"file {scope} {name} {size} {sha}")
        for name,target in profile.R8_CRITICAL_LINKS.items():
            lines.append(f"link common {name} {target}")
        self.original=lines
        self.profile.write_text("\n".join(lines)+"\n")

    def test_complete_pins_pass(self):
        result=profile.assess(self.root,self.manifest)
        self.assertTrue(result["verified"])
        self.assertGreaterEqual(result["checked_entries"],12)

    def test_each_missing_pin_fails(self):
        for name in profile.R8_CRITICAL_FILES:
            with self.subTest(name=name):
                self.profile.write_text("\n".join(
                    line for line in self.original if f" {name} " not in line)+"\n")
                with self.assertRaises(profile.RuntimeProfileError):
                    profile.assess(self.root,self.manifest)

    def test_scope_downgrade_fails(self):
        name=profile.R8_CRITICAL_FILES[0]
        self.profile.write_text(
            "\n".join(self.original).replace(f"file candidate {name} ",
                                             f"file common {name} ")+"\n")
        with self.assertRaisesRegex(profile.RuntimeProfileError,
                                    "R8_CRITICAL_RUNTIME_PIN_ABSENT"):
            profile.assess(self.root,self.manifest)

    def test_changed_critical_bytes_fail(self):
        name=profile.R8_CRITICAL_FILES[1]
        f=self.root/name
        f.write_bytes(b"changed critical runtime\n")
        with self.assertRaises(profile.RuntimeProfileError):
            profile.assess(self.root,self.manifest)

    def test_links_must_be_pinned_and_exact(self):
        for name in profile.R8_CRITICAL_LINKS:
            with self.subTest(name=name):
                self.profile.write_text("\n".join(
                    line for line in self.original if f" {name} " not in line)+"\n")
                with self.assertRaises(profile.RuntimeProfileError):
                    profile.assess(self.root,self.manifest)
        self.profile.write_text("\n".join(self.original)+"\n")
        f=self.root/"etc/rc.d/S11sysctl"
        f.unlink()
        f.symlink_to("../init.d/other")
        with self.assertRaises(profile.RuntimeProfileError):
            profile.assess(self.root,self.manifest)


if __name__=="__main__":
    unittest.main()
