"""Source-only C-011 noncredential PON/OMCI verification contracts.

Never contact an ONU, read PLOAM/LOID/PON serial or alter optics, UCI,
firmware selectors, flash, network interfaces or boot settings.
"""
import os
from pathlib import Path
import re
import subprocess
import unittest

ROOT=Path(__file__).resolve().parents[1]
MODULE=ROOT/"overlay/usr/lib/lua/8311/effective_pon_state.lua"
PROBE=ROOT/"overlay/usr/lib/lua/8311/effective_pon_probe.lua"
CONTROLLER=ROOT/"overlay/usr/lib/lua/luci/controller/8311.lua"
CONFIG=ROOT/"overlay/usr/lib/lua/luci/view/8311/config.htm"
JAVASCRIPT=ROOT/"overlay/www/luci-static/resources/view/8311.js"
FIXTURE=ROOT/"tests/effective_pon_fixture.lua"
VENDOR=Path(os.environ.get("AOTT_VENDOR_ROOTFS","/no/vendor/rootfs"))


class PonOmciSourceTests(unittest.TestCase):
    def test_host_portable_lua_fixture(self):
        p=subprocess.run(["lua5.1",str(FIXTURE),
                          str(ROOT/"overlay/usr/lib/lua")],
                         capture_output=True,text=True,timeout=20)
        self.assertEqual(p.returncode,0,p.stderr)
        self.assertIn("AOTT_C011_PON_OMCI_FIXTURE_PASS checks=99",p.stdout)

    def test_vendor_mips_lua_fixture(self):
        if not os.environ.get("AOTT_VENDOR_ROOTFS"):
            raise unittest.SkipTest("No separately extracted OFFLINE vendor rootfs")
        binary=VENDOR/"usr/bin/lua"
        self.assertTrue(binary.is_file())
        p=subprocess.run(["qemu-mips-static","-L",str(VENDOR),
            str(binary),str(FIXTURE),str(ROOT/"overlay/usr/lib/lua")],
            capture_output=True,text=True,timeout=25)
        self.assertEqual(p.returncode,0,p.stderr)
        self.assertIn("AOTT_C011_PON_OMCI_FIXTURE_PASS checks=99",p.stdout)

    def test_lua51_syntax_and_fixed_four_noncredential_fields(self):
        for file in (MODULE,PROBE):
            with self.subTest(module=file.name):
                p=subprocess.run(["luac5.1","-p",str(file)],
                    capture_output=True,text=True,timeout=10)
                self.assertEqual(p.returncode,0,p.stderr)
        model=MODULE.read_text()
        self.assertIn('IDS={"pon_mode","omcc_version","iop_mask","mib_file"}',model)
        self.assertIn("persist",model)
        self.assertIn("hardware_qualified=false",model)
        self.assertIn("runtime_effect_proven=false",model)
        self.assertIn("proves_internet_connectivity=false",model)
        self.assertIn("proves_setting_effect=false",model)
        self.assertIn("contains_registration_secret=false",model)

    def test_readonly_native_probe_exact_uci_and_environment_whitelist(self):
        p=PROBE.read_text()
        for part in (
            'pon_mode={"gpon","ponip","pon_mode"}',
            'omcc_version={"omci","default","omcc_version"}',
            'iop_mask={"gpon","ponip","iop_mask"}',
            'mib_file={"omci","default","mib_file"}',
            '"/usr/sbin/fwenv_get","--8311",id',
            '"/usr/bin/pon","psg"',
            '"/usr/bin/timeout","-k","1","3"',
            'return model.inspect(saved,configured,state)',
        ):
            self.assertIn(part,p)
        # No registrar identity or credential getters, even by accident.
        for bad in ("gpon_sn","vendor_id","equipment_id",
                    "reg_id_hex","loid","lpwd","root_pwhash",
                    "iphost_mac","iphost_hostname","iphost_domain",
                    "fw_printenv","uci set","uci commit","set_8311_",
                    "os.execute", "io.popen", "bankctl.sh", "ubiupdatevol",
                    "mqtt","http.post"):
            with self.subTest(disallowed=bad):
                self.assertNotIn(bad,p)
        self.assertIn("Only PON state code is extracted",p)

    def test_authenticated_admin_only_get_not_anonymous_metrics(self):
        source=CONTROLLER.read_text()
        self.assertIn('require "8311.effective_pon_probe"',source)
        self.assertEqual(
            source.count('{"admin", "8311", "effective_pon"}'),1)
        self.assertIn('call("action_effective_pon")',source)
        self.assertNotIn('entry({"8311", "effective_pon"}',source)
        fn=source.split("function action_effective_pon()",1)[1].split(
           "function action_r5_security()",1)[0]
        self.assertIn('REQUEST_METHOD") ~= "GET"',fn)
        self.assertIn('Cache-Control", "no-store, private"',fn)
        self.assertIn('X-Content-Type-Options", "nosniff"',fn)
        self.assertIn("pcall(effective_pon_probe.live_pon)",fn)
        self.assertIn("contains_registration_secret ~= false",fn)
        self.assertNotIn("action_save",fn)
        self.assertNotIn("fwenv_set",fn)
        self.assertIn("Read-only GET required",fn)

    def test_manual_panel_status_and_source_consequences(self):
        template=CONFIG.read_text()
        js=JAVASCRIPT.read_text()
        self.assertIn('id="aott-pon-effective-refresh"',template)
        self.assertIn('id="aott-pon-effective-results"',template)
        self.assertIn("url('admin/8311/effective_pon')",template)
        self.assertIn("function refreshPonEffective()",js)
        code=js.split("function refreshPonEffective()",1)[1].split(
             "function refreshDeviceEffective()",1)[0]
        for part in (
            "request8311(url,{method:'GET',cache:'no-store'})",
            "cell.textContent=value",
            "PON state: O5.1 associated.",
            "OMCI effect unverified",
            "No settings changed.",
            "contains_registration_secret!==false",
        ):
            self.assertIn(part,code)
        for bad in ("innerHTML","setInterval","post8311",
                    "localStorage","fetch('https", "fwenv_set",
                    "gpon_sn","reg_id","loid","lpwd","root_pwhash"):
            with self.subTest(disallowed=bad):
                self.assertNotIn(bad,code)

    def test_no_confused_pon_state_as_effective_setting(self):
        model=MODULE.read_text()
        self.assertIn("independently_effective_verified=0",model)
        self.assertIn("=false",model)
        self.assertEqual(model.count("runtime_effect_proven=false"),1)
        self.assertIn("no_device_write=true",model)
        self.assertIn("no_firmware_commits=true",model)

    def test_legacy_fixture_stubs_new_authenticated_dependency(self):
        fixture=(ROOT/"tests/pon_me_fixture.lua").read_text()
        self.assertIn('package.preload["8311.effective_pon_probe"]',fixture)
        self.assertIn('live_pon=function()',fixture)


if __name__=="__main__":
    unittest.main()
