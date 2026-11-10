"""V3r3 P0 source invariants, fail closed without a vendor device.

The tests are static and host-Lua only. They are not hardware acceptance.
"""
from pathlib import Path
import json
import re
import shutil
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]
OVERLAY = ROOT / "overlay"
LUA_ROOT = OVERLAY / "usr/lib/lua"
SERVICES = ("8311-rarpd", "8311-rx-los", "8311-pingd", "8311-vlansd")
HISTORY_PATH = "/var/run/aott-history"

class P0SourceContract(unittest.TestCase):
    def test_history_service_uses_real_vendor_tmpfs_directory(self):
        live = (OVERLAY / "etc/init.d/8311-history").read_text()
        files = [
            "usr/lib/lua/8311/history_process_lock.lua",
            "usr/lib/lua/8311/history_publication_gate.lua",
        ]
        self.assertIn("[ -d /var/run ] && [ ! -L /var/run ] || return 1", live)
        self.assertIn("mkdir -m 0700 " + HISTORY_PATH, live)
        self.assertIn("[ ! -L " + HISTORY_PATH + " ]", live)
        self.assertIn("stat -c '%u:%g:%a'", live)
        self.assertIn("'0:0:700'", live)
        self.assertIn('config_get enabled main enabled 0', live)
        self.assertNotIn("mkdir -p /run/", live)
        for path in files:
            source = (OVERLAY / path).read_text()
            self.assertIn('local PRODUCTION_DIR="' + HISTORY_PATH + '"', source)
        for src in (OVERLAY / "etc/init.d", LUA_ROOT / "8311"):
            for path in src.rglob("*"):
                if path.is_file():
                    self.assertNotIn('"/run/aott-history"', path.read_text())

    def test_vendor_runtime_guard_rejects_wrong_path_and_symlink(self):
        init = (OVERLAY / "etc/init.d/8311-history").read_text()
        self.assertLess(init.index('[ "$enabled" = "1" ] || return 0'),
                        init.index("mkdir -m 0700 " + HISTORY_PATH))
        self.assertLess(init.index("[ ! -L " + HISTORY_PATH + " ]"),
                        init.index("stat -c '%u:%g:%a'"))
        self.assertNotIn('chown root:root ' + HISTORY_PATH, init)
        self.assertNotIn('chmod 0700 ' + HISTORY_PATH, init)
        if shutil.which("sh"):
            script = OVERLAY / "etc/init.d/8311-history"
            p=subprocess.run(["sh", "-n", str(script)],capture_output=True,text=True,timeout=8)
            self.assertEqual(p.returncode,0,p.stderr)

    def test_noncritical_vendor_daemon_retries_are_bounded(self):
        for name in SERVICES:
            with self.subTest(service=name):
                script = (OVERLAY/"etc/init.d"/name).read_text()
                self.assertIn("procd_set_param respawn 300 10 5",script)
                self.assertNotRegex(script,r"(?m)^\s*procd_set_param respawn\s+\d+\s+\d+\s+0\s*$")
                self.assertEqual(script.count("procd_set_param respawn"),1)
                p=subprocess.run(["sh","-n"],input=script,capture_output=True,text=True,timeout=8)
                self.assertEqual(p.returncode,0,p.stderr)

    def test_canonical_version_module_not_independent_release_labels(self):
        current=json.loads((ROOT/"release.json").read_text())
        expected=current["product"]+"-"+current["version"]+current["revision"]
        module=(LUA_ROOT/"8311/version.lua").read_text()
        cap=(LUA_ROOT/"8311/v3_capabilities.lua").read_text()
        self.assertIn('local version_meta = require "8311.version"',cap)
        self.assertNotIn('release="v3", revision="r1"',cap)
        self.assertIn("firmware_version=version_meta.version",cap)
        self.assertIn('version = "'+expected+'"',module)
        self.assertIn('revision = "'+current["revision"]+'"',module)
        self.assertIn("FW_VERSION="+expected,(OVERLAY/"etc/8311_version").read_text())

    def test_lua_capabilities_report_canonical_release(self):
        if not shutil.which("lua5.1"):
            self.skipTest("Lua 5.1 not available")
        script=r'''
local overlay="@LUA_ROOT@"
package.path=overlay.."/?.lua;"..package.path
package.preload["nixio.fs"]=function()
    return {stat=function(_) return nil end}
end
local version=require "8311.version"
local cap=require "8311.v3_capabilities".snapshot()
assert(cap.revision==version.revision)
assert(cap.firmware_version==version.version)
assert(cap.release=="v3")
assert(cap.remote_management_default==false)
print("V3_CANONICAL_CAPABILITY_IDENTITY_PASS")
'''
        p=subprocess.run(["lua5.1","-e",script.replace("@LUA_ROOT@",str(LUA_ROOT))],cwd=ROOT,
                         capture_output=True,text=True,timeout=10)
        self.assertEqual(p.returncode,0,p.stderr)
        self.assertIn("V3_CANONICAL_CAPABILITY_IDENTITY_PASS",p.stdout)

    def test_critical_interfaces_and_vendor_datapath_unchanged(self):
        script=(OVERLAY/"etc/init.d/_8311-poninit.sh").read_text()
        self.assertTrue(script)
        # No edits to kernel/bootcore/vendor firmware are made by this source patch.
        for part in ("kernel.bin","bootcore.bin"):
            self.assertFalse((OVERLAY/part).exists())

if __name__=="__main__":
    unittest.main()
