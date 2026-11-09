from pathlib import Path
import os, shutil, subprocess, unittest

ROOT=Path(__file__).resolve().parents[1]
MODULE=ROOT/"overlay/usr/lib/lua/8311/config_activation.lua"
CONFIG=ROOT/"overlay/usr/lib/lua/8311/config.lua"
WORKER=ROOT/"overlay/usr/libexec/8311-config-apply.lua"
VIEW=ROOT/"overlay/usr/lib/lua/luci/view/8311/config.htm"
JS=ROOT/"overlay/www/luci-static/resources/view/8311.js"
FIXTURE=ROOT/"tests/v3_config_activation_fixture.lua"
VENDOR=Path(os.getenv("AOTT_VENDOR_ROOTFS","/missing-vendor-rootfs"))

class V3ConfigActivationTests(unittest.TestCase):
    def run_fixture(self,command):
        p=subprocess.run(command,cwd=ROOT,capture_output=True,text=True,timeout=30)
        self.assertEqual(p.returncode,0,p.stderr)
        self.assertIn("AOTT_V3_CONFIG_ACTIVATION_PASS",p.stdout)

    def test_host_fixture(self):
        self.run_fixture(["lua5.1",str(FIXTURE),str(ROOT/"overlay/usr/lib/lua")])

    def test_vendor_mips_fixture(self):
        if not os.getenv("AOTT_VENDOR_ROOTFS"):
            raise unittest.SkipTest("No offline vendor rootfs configured")
        self.assertTrue((VENDOR/"usr/bin/lua").is_file())
        self.run_fixture([
            "qemu-mips-static","-L",str(VENDOR),str(VENDOR/"usr/bin/lua"),
            str(FIXTURE),str(ROOT/"overlay/usr/lib/lua")
        ])

    def test_module_compiles(self):
        p=subprocess.run(["luac5.1","-p",str(MODULE)],
                         capture_output=True,text=True,timeout=10)
        self.assertEqual(p.returncode,0,p.stderr)

    def test_traced_live_activation_set_has_22_fields_and_excludes_pon(self):
        s=MODULE.read_text()
        for field in (
            "lang","hostname","timezone","ntp_servers","https_redirect",
            "pingd","ping_ip","reverse_arp","console_en","dying_gasp_en",
            "rx_los","ethtool_speed","sfp_vendor","sfp_oui","sfp_partno","sfp_rev",
            "sfp_serial","sfp_date","sfp_vendordata","fix_vlans",
            "internet_vlan","services_vlan",
        ):
            self.assertIn(field+"=true",s)
        for absent in ("gpon_sn=true","root_pwhash=true","mib_file=true"):
            self.assertNotIn(absent,s)

    def test_native_consumers_are_fixed_and_bounded(self):
        s=MODULE.read_text()
        self.assertIn('"/etc/init.d/system"',s)
        self.assertIn('"/etc/init.d/sysntpd"',s)
        self.assertIn('"/bin/pidof","ntpd"',s)
        self.assertIn('"/proc/sys/kernel/hostname"',s)
        self.assertIn('fs.readlink("/tmp/localtime")',s)
        self.assertNotIn("os.execute",s)
        self.assertNotIn("io.popen",s)
        self.assertNotIn("shellquote",s)
        self.assertNotIn("ubiupdatevol",s)

    def test_language_is_not_falsely_verified_in_same_worker(self):
        s=MODULE.read_text()
        self.assertIn('"next_authenticated_luci_request"',s)
        self.assertIn("runtime_pending=true",s)
        self.assertIn("requires_new_authenticated_request",s)

    def test_runtime_mismatch_has_rollback_contract(self):
        s=MODULE.read_text()
        self.assertIn("rollback_attempted",s)
        self.assertIn("rollback_succeeded",s)
        self.assertIn('"runtime_effect_mismatch"',s)
        self.assertIn('"configured_readback_mismatch"',s)

if __name__=="__main__":
    unittest.main()
