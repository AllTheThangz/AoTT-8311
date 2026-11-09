from pathlib import Path
import os, subprocess, unittest

ROOT=Path(__file__).resolve().parents[1]
TX=ROOT/"overlay/usr/lib/lua/8311/boot_config_transaction.lua"
STORE=ROOT/"overlay/usr/lib/lua/8311/boot_config_store.lua"
SYSINIT=ROOT/"overlay/etc/init.d/_8311-sysinit.sh"
WATCHDOG=ROOT/"overlay/usr/libexec/8311-boot-config-watchdog"
FIXTURE=ROOT/"tests/v3_boot_config_transaction_fixture.lua"
VENDOR=Path(os.getenv("AOTT_VENDOR_ROOTFS","/missing"))

class V3BootConfigTransactionTests(unittest.TestCase):
    def run_fixture(self,command):
        p=subprocess.run(command,cwd=ROOT,capture_output=True,text=True,timeout=30)
        self.assertEqual(p.returncode,0,p.stderr)
        self.assertIn("AOTT_V3_BOOT_CONFIG_TRANSACTION_PASS",p.stdout)

    def test_host_fixture(self):
        self.run_fixture(["lua5.1",str(FIXTURE),str(ROOT/"overlay/usr/lib/lua")])

    def test_vendor_mips_fixture(self):
        if not os.getenv("AOTT_VENDOR_ROOTFS"): self.skipTest("No vendor rootfs")
        self.run_fixture([
            "qemu-mips-static","-L",str(VENDOR),str(VENDOR/"usr/bin/lua"),
            str(FIXTURE),str(ROOT/"overlay/usr/lib/lua")
        ])

    def test_persistent_recovery_is_armed_before_candidate_write(self):
        s=TX.read_text()
        armed=s.index("store.arm({")
        write_loop=s.index("for _,id in ipairs(ids) do",armed)
        self.assertLess(armed,write_loop)
        self.assertIn("bootcmd_before=bootcmd",s)
        self.assertIn("restore(p)",s)

    def test_boot_entry_precedes_persistent_root_bootcmd_repair(self):
        s=SYSINIT.read_text()
        self.assertLess(s.index("8311-boot-config-guard enter"),
                        s.index("_8311_check_persistent_root"))

    def test_watchdog_restores_then_reboots(self):
        s=WATCHDOG.read_text()
        self.assertIn("sleep 180",s)
        self.assertIn("8311-boot-config-guard timeout",s)
        self.assertIn("sync",s)
        self.assertIn("reboot",s)

    def test_only_four_boot_fields_are_accepted(self):
        s=TX.read_text()
        for field in ("bootdelay","uart_select","failsafe_delay","persist_root"):
            self.assertIn(field,s)
        self.assertNotIn('gpon_sn={',s)
        self.assertNotIn('ipaddr={',s)

    def test_no_dynamic_shell_or_firmware_bank_action(self):
        for p in (TX,STORE):
            s=p.read_text()
            for forbidden in ("os.execute","io.popen","ubiupdatevol","8311-bankctl"):
                self.assertNotIn(forbidden,s)

    def test_lua_syntax(self):
        for p in (TX,STORE):
            r=subprocess.run(["luac5.1","-p",str(p)],capture_output=True,text=True)
            self.assertEqual(r.returncode,0,r.stderr)

if __name__=="__main__":
    unittest.main()
