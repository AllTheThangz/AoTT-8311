from pathlib import Path
import os, subprocess, unittest

ROOT=Path(__file__).resolve().parents[1]
MODULE=ROOT/"overlay/usr/lib/lua/8311/mib_profile.lua"
FIXTURE=ROOT/"tests/v3_mib_profile_fixture.lua"
CONFIG=ROOT/"overlay/usr/lib/lua/8311/config.lua"
CONTROLLER=ROOT/"overlay/usr/lib/lua/luci/controller/8311.lua"
VIEW=ROOT/"overlay/usr/lib/lua/luci/view/8311/config.htm"
JS=ROOT/"overlay/www/luci-static/resources/view/8311.js"
VENDOR=Path(os.getenv("AOTT_VENDOR_ROOTFS","/missing-vendor-rootfs"))

class V3MibProfileTests(unittest.TestCase):
    def run_fixture(self,command):
        p=subprocess.run(command,cwd=ROOT,capture_output=True,text=True,timeout=30)
        self.assertEqual(p.returncode,0,p.stderr)
        self.assertIn("AOTT_V3_MIB_PROFILE_PASS",p.stdout)

    def test_host_real_profiles(self):
        if not os.getenv("AOTT_VENDOR_ROOTFS"):
            self.skipTest("No extracted vendor rootfs configured")
        self.run_fixture(["lua5.1",str(FIXTURE),str(ROOT/"overlay/usr/lib/lua"),str(VENDOR)])

    def test_vendor_mips_real_profiles(self):
        if not os.getenv("AOTT_VENDOR_ROOTFS"):
            self.skipTest("No extracted vendor rootfs configured")
        self.run_fixture([
            "qemu-mips-static","-L",str(VENDOR),str(VENDOR/"usr/bin/lua"),
            str(FIXTURE),str(ROOT/"overlay/usr/lib/lua"),str(VENDOR)
        ])

    def test_module_and_callers_compile(self):
        for p in (MODULE,CONFIG,CONTROLLER):
            r=subprocess.run(["luac5.1","-p",str(p)],capture_output=True,text=True,timeout=10)
            self.assertEqual(r.returncode,0,r.stderr)

    def test_parser_is_read_only_fixed_scope(self):
        s=MODULE.read_text()
        self.assertIn('^/etc/mibs/[A-Za-z0-9_.-]+%.ini$',s)
        self.assertIn("physical_uni_count",s)
        self.assertIn("tcont_me262_count",s)
        self.assertIn("iphost_me134_count",s)
        self.assertIn("veip_me329_count",s)
        self.assertIn("slot_editable",s)
        self.assertIn("validate_for_configuration",s)
        for forbidden in ("os.execute","io.popen","fw_setenv","uci:set","writefile","rename("):
            self.assertNotIn(forbidden,s)

    def test_server_validation_uses_profile_capabilities(self):
        s=CONFIG.read_text()
        self.assertIn('mib_profile.inspect(v.mib_file)',s)
        self.assertIn('mib_profile.validate_for_configuration(profile,v,changed_map)',s)
        self.assertIn('profile.topology.slot_editable',s)
        self.assertIn('"check-slot", v.mib_file, v.pon_slot',s)

    def test_authenticated_profile_endpoint(self):
        s=CONTROLLER.read_text()
        self.assertIn('entry({"admin", "8311", "mib_profile"}, post("action_mib_profile"))',s)
        block=s[s.index("function action_mib_profile()"):s.index("function action_history()",s.index("function action_mib_profile()"))]
        self.assertIn("dispatcher.context.authsession",block)
        self.assertIn("dispatcher.test_post_security()",block)
        self.assertIn('dispatcher.context.authuser~="root"',block)
        self.assertIn("mib_profile.inspect(values.mib_file)",block)
        self.assertIn("contains_subscriber_values",MODULE.read_text())

    def test_worker_and_mib_applicator_recheck_profile_capability(self):
        tx=(ROOT/"overlay/usr/lib/lua/8311/pon_config_transaction.lua").read_text()
        runtime=(ROOT/"overlay/usr/lib/lua/8311/pon_mib_runtime.lua").read_text()
        self.assertIn('mib_profile.inspect(selected)',tx)
        self.assertIn('mib_profile.validate_for_configuration(profile,proposed,changed)',tx)
        self.assertIn('mib_profile.inspect(p)',runtime)
        self.assertIn('"pon_mib_slot_not_applicable"',runtime)

    def test_initial_mib_selector_does_not_parse_every_profile(self):
        s=CONTROLLER.read_text()
        start=s.index("local function mib_profile_options()")
        end=s.index("\nend\n",start)+5
        block=s[start:end]
        self.assertIn('fs.glob("/etc/mibs/*.ini")',block)
        self.assertNotIn("mib_profile.inspect",block)
        # Selected-profile capability discovery must remain authenticated and live.
        self.assertIn("mib_profile.inspect(values.mib_file)",s)

    def test_configuration_page_is_profile_driven(self):
        v=VIEW.read_text()
        j=JS.read_text()
        self.assertIn("data-mib-profile-url",v)
        self.assertIn('id="aott-mib-profile-summary"',v)
        self.assertIn("refreshMibProfile",j)
        self.assertIn("Clear incompatible slot override",j)
        self.assertIn("IP Host Config Data ME 134",j)
        self.assertIn("T-CONT ME 262 records",j)
        self.assertIn("OLT/provider compatibility is not inferred",j)

if __name__=="__main__":
    unittest.main()
