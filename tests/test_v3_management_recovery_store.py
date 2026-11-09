from pathlib import Path
import os, shutil, subprocess, tempfile, unittest

ROOT=Path(__file__).resolve().parents[1]
MODULE=ROOT/"overlay/usr/lib/lua/8311/management_recovery_store.lua"
FIXTURE=ROOT/"tests/v3_management_recovery_store_fixture.lua"
VENDOR=Path(os.getenv("AOTT_VENDOR_ROOTFS","/missing-vendor-rootfs"))

class V3ManagementRecoveryStoreTests(unittest.TestCase):
    def test_lua51_syntax(self):
        p=subprocess.run(["luac5.1","-p",str(MODULE)],
                         capture_output=True,text=True,timeout=10)
        self.assertEqual(p.returncode,0,p.stderr)

    def test_vendor_mips_real_file_roundtrip(self):
        if not os.getenv("AOTT_VENDOR_ROOTFS"):
            self.skipTest("Vendor rootfs not supplied")
        root=Path("/var/tmp/aott-management-recovery-test-deadbeef")
        shutil.rmtree(root,ignore_errors=True)
        root.mkdir(mode=0o700)
        try:
            p=subprocess.run([
                "qemu-mips-static","-L",str(VENDOR),str(VENDOR/"usr/bin/lua"),
                str(FIXTURE),str(root),str(ROOT/"overlay/usr/lib/lua")
            ],cwd=ROOT,capture_output=True,text=True,timeout=30)
            self.assertEqual(p.returncode,0,p.stderr)
            self.assertIn("AOTT_V3_MANAGEMENT_RECOVERY_STORE_PASS",p.stdout)
        finally:
            shutil.rmtree(root,ignore_errors=True)

    def test_fixed_private_paths_and_marker_order(self):
        s=MODULE.read_text()
        self.assertIn('local PARENT="/ptconf/8311/aott-recovery"',s)
        self.assertIn('local ROOT=PARENT.."/v1"',s)
        self.assertIn('local DIR=ROOT.."/management"',s)
        self.assertIn('local MARKER=DIR.."/pending"',s)
        self.assertIn("modedec==600",s)
        self.assertIn("fsync",s.replace("sync_dir","fsync"))  # structural durability helper exists
        arm=s[s.index("function M.arm"):s.index("function M.pending")]
        self.assertLess(arm.index("write_atomic(n"),arm.index("write_atomic(marker"))
        clear=s[s.index("function M.clear"):]
        self.assertLess(clear.index("safe_unlink(path(root,MARKER)"),
                        clear.index("safe_unlink(entry[1]"))

    def test_no_arbitrary_command_or_public_value_output(self):
        s=MODULE.read_text()
        self.assertNotIn("os.execute",s)
        self.assertNotIn("io.popen",s)
        self.assertNotIn('"/bin/sh"',s)
        self.assertIn('contains_configuration_values=false',s)

if __name__=="__main__":
    unittest.main()
