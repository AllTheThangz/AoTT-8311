"""Source-only V3r4 reboot/interrupted-stage recovery tests.

The Lua fixture simulates persistent boot environment writes, power loss,
native setter exceptions and failed restoration. No ONU is accessed.
"""
import os
from pathlib import Path
import shutil
import subprocess
import unittest

ROOT=Path(__file__).resolve().parents[1]
FIXTURE=ROOT/"tests/v3_boot_config_crash_fixture.lua"
TX=ROOT/"overlay/usr/lib/lua/8311/boot_config_transaction.lua"
STORE=ROOT/"overlay/usr/lib/lua/8311/boot_config_store.lua"
VENDOR=Path(os.getenv("AOTT_VENDOR_ROOTFS","/missing-vendor-rootfs"))


class BootCrashRecoveryTests(unittest.TestCase):
    def fixture(self,argv):
        p=subprocess.run(argv+[str(FIXTURE),str(ROOT/"overlay/usr/lib/lua")],
                         capture_output=True,text=True,timeout=40,cwd=ROOT)
        self.assertEqual(p.returncode,0,p.stderr)
        self.assertIn("AOTT_V3_BOOT_CONFIG_CRASH_RECOVERY_PASS",p.stdout)
        self.assertIn("checks=41",p.stdout)

    def test_host_lua_memory_only_recovery(self):
        if not shutil.which("lua5.1"):
            self.skipTest("Host Lua 5.1 unavailable")
        self.fixture(["lua5.1"])

    def test_vendor_mips_lua_memory_only_recovery(self):
        if not os.getenv("AOTT_VENDOR_ROOTFS"):
            self.skipTest("Offline vendor rootfs not supplied")
        native=VENDOR/"usr/bin/lua"
        self.assertTrue(native.is_file())
        self.fixture(["qemu-mips-static","-L",str(VENDOR),str(native)])

    def test_source_uses_atomic_two_phase_preparation(self):
        t=TX.read_text()
        s=STORE.read_text()
        self.assertIn("plan.phase=\"preparing\"",s)
        self.assertIn("preparing=true,prepared=true",s)
        self.assertIn("pcall(store.phase,job,\"prepared\",nil)",t)
        self.assertLess(t.index("store.arm({"),
                        t.index("pcall(store.phase,job,\"prepared\",nil)"))
        self.assertLess(t.index("if not verify(candidate,nil)"),
                        t.index("pcall(store.phase,job,\"prepared\",nil)"))
        self.assertIn('p.phase=="preparing"',t)
        self.assertIn("BOOT_CONFIG_INTERRUPTED_STAGE_RESTORED",t)
        self.assertIn("boot_config_stage_restore_unverified",t)
        self.assertIn("boot_config_stage_recovery_disarm_unverified",t)
        self.assertIn("recovery_required=",t)
        view=(ROOT/"overlay/usr/lib/lua/luci/view/8311/config.htm").read_text()
        self.assertIn('boot_trial.phase == "preparing"',view)
        self.assertIn("Boot configuration recovery required",view)
        self.assertIn("This is not an approved trial",view)
        self.assertLess(view.index('boot_trial.phase == "preparing"'),
                        view.index('boot_trial.phase == "prepared"'))
        self.assertNotIn("os.execute",t)
        self.assertNotIn("io.popen",t)

    def test_lua_syntax(self):
        for file in (TX,STORE,FIXTURE):
            with self.subTest(file=file.name):
                p=subprocess.run(["luac5.1","-p",str(file)],
                                 capture_output=True,text=True,timeout=8)
                self.assertEqual(p.returncode,0,p.stderr)


if __name__=="__main__":
    unittest.main()
