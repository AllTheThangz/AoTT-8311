from pathlib import Path
import os, shutil, subprocess, unittest

ROOT=Path(__file__).resolve().parents[1]
MODULE=ROOT/"overlay/usr/lib/lua/8311/daemon_state.lua"
PING=ROOT/"overlay/usr/sbin/8311-pingd.sh"
RARP=ROOT/"overlay/usr/sbin/8311-rarpd.sh"
FIXTURE=ROOT/"tests/v3_daemon_state_fixture.lua"
VENDOR=Path(os.getenv("AOTT_VENDOR_ROOTFS","/missing-vendor-rootfs"))

class V3DaemonRuntimeReceiptTests(unittest.TestCase):
    def run_fixture(self,cmd):
        p=subprocess.run(cmd,cwd=ROOT,capture_output=True,text=True,timeout=25)
        self.assertEqual(p.returncode,0,p.stderr)
        self.assertIn("AOTT_V3_DAEMON_STATE_PASS",p.stdout)

    def test_host_fixture(self):
        self.run_fixture(["lua5.1",str(FIXTURE),str(ROOT/"overlay/usr/lib/lua")])

    def test_vendor_mips_fixture(self):
        if not os.getenv("AOTT_VENDOR_ROOTFS"):
            self.skipTest("Vendor rootfs not supplied")
        self.run_fixture(["qemu-mips-static","-L",str(VENDOR),str(VENDOR/"usr/bin/lua"),
                          str(FIXTURE),str(ROOT/"overlay/usr/lib/lua")])

    def test_shell_scripts_compile_on_host_and_vendor_busybox(self):
        for script in (PING,RARP):
            p=subprocess.run(["sh","-n",str(script)],capture_output=True,text=True,timeout=10)
            self.assertEqual(p.returncode,0,p.stderr)
            if os.getenv("AOTT_VENDOR_ROOTFS"):
                p=subprocess.run(["qemu-mips-static","-L",str(VENDOR),
                                  str(VENDOR/"bin/busybox"),"sh","-n",str(script)],
                                 capture_output=True,text=True,timeout=15)
                self.assertEqual(p.returncode,0,p.stderr)

    def test_receipts_are_ram_only_bounded_and_process_bound(self):
        state=MODULE.read_text()
        self.assertIn('local ROOT="/var/run/aott-runtime"',state)
        self.assertIn('modedec~=600',state)
        self.assertIn('boot_id',state)
        self.assertIn('process_identity_verified=true',state)
        self.assertIn('"/proc/"..tostring(pid).."/cmdline"',state)
        self.assertNotIn("/ptconf",state)
        self.assertNotIn("fwenv_set",state)
        for script in (PING,RARP):
            s=script.read_text()
            self.assertIn("STATE_DIR=/var/run/aott-runtime",s)
            self.assertIn("chmod 600",s)
            self.assertIn("boot_id=",s)
            self.assertNotIn("/ptconf",s)

    def test_ping_receipt_contains_consumed_target_and_rarp_separates_active(self):
        ping=PING.read_text()
        rarp=RARP.read_text()
        self.assertIn("target=%s",ping)
        self.assertIn("active=%s",ping)
        self.assertIn("active=%s",rarp)
        self.assertIn('state_write 1 1 "$PING_HOST"',ping)
        self.assertIn('state_write "$RARP_CONFIGURED" 0',rarp)

if __name__=="__main__":
    unittest.main()
