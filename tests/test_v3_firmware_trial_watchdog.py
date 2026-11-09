from pathlib import Path
import os, subprocess, unittest

ROOT=Path(__file__).resolve().parents[1]
MODULE=ROOT/"overlay/usr/lib/lua/8311/firmware_trial_watchdog.lua"
WATCH=ROOT/"overlay/usr/libexec/8311-firmware-trial-watchdog"
CONFIRM=ROOT/"overlay/usr/libexec/8311-firmware-trial-confirm"
SYSINIT=ROOT/"overlay/etc/init.d/_8311-sysinit.sh"
FIXTURE=ROOT/"tests/v3_firmware_trial_watchdog_fixture.lua"
VENDOR=Path(os.getenv("AOTT_VENDOR_ROOTFS","/missing-vendor-rootfs"))

class FirmwareTrialWatchdogTests(unittest.TestCase):
    def run_fixture(self,cmd):
        p=subprocess.run(cmd,cwd=ROOT,capture_output=True,text=True,timeout=30)
        self.assertEqual(p.returncode,0,p.stderr)
        self.assertIn("AOTT_V3_FIRMWARE_TRIAL_WATCHDOG_PASS",p.stdout)

    def test_host_fixture(self):
        self.run_fixture(["lua5.1",str(FIXTURE),str(ROOT/"overlay/usr/lib/lua")])

    def test_vendor_mips_fixture(self):
        if not os.getenv("AOTT_VENDOR_ROOTFS"):
            self.skipTest("No vendor runtime configured")
        self.run_fixture([
            "qemu-mips-static","-L",str(VENDOR),str(VENDOR/"usr/bin/lua"),
            str(FIXTURE),str(ROOT/"overlay/usr/lib/lua")
        ])

    def test_module_compiles_and_timeout_is_local_only(self):
        p=subprocess.run(["luac5.1","-p",str(MODULE)],capture_output=True,text=True,timeout=10)
        self.assertEqual(p.returncode,0,p.stderr)
        s=MODULE.read_text()
        self.assertIn('local ROOT="/var/run/aott-firmware-trial"',s)
        self.assertIn('local WAIT_SECONDS=180',s)
        self.assertIn('{"/usr/sbin/8311-bankctl.sh","rollback"}',s)
        self.assertIn("firmware_trial_watchdog_rollback_failed",s)
        for forbidden in ("curl","wget","ping ","nslookup","http://","https://"):
            self.assertNotIn(forbidden,s)

    def test_confirmation_is_boot_local_and_nonpersistent(self):
        s=MODULE.read_text()
        self.assertIn('local CONFIRMED=ROOT.."/confirmed"',s)
        self.assertIn('"/proc/sys/kernel/random/boot_id"',s)
        self.assertNotIn("/ptconf/",s)
        self.assertIn("FIRMWARE_TRIAL_WATCHDOG_CONFIRMED",s)

    def test_sysinit_starts_watchdog_detached_after_normal_boot_setup(self):
        s=SYSINIT.read_text()
        self.assertIn("/sbin/start-stop-daemon -S -b -m",s)
        self.assertIn("-p /tmp/8311-firmware-trial-watchdog.pid",s)
        self.assertIn("-x /usr/bin/lua -- /usr/libexec/8311-firmware-trial-watchdog",s)
        self.assertLess(s.index('start "$@"'),
                        s.index("/usr/libexec/8311-firmware-trial-watchdog"))

    def test_executables_use_fixed_module(self):
        self.assertIn('require "8311.firmware_trial_watchdog"',WATCH.read_text())
        self.assertIn("watchdog.run()",WATCH.read_text())
        self.assertIn('require "8311.firmware_trial_watchdog"',CONFIRM.read_text())
        self.assertIn("watchdog.confirm()",CONFIRM.read_text())

if __name__=="__main__":
    unittest.main()
