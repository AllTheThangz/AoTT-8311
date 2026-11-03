"""C-011: redacted read-only OMCI reporting source/effect contract.

Ten additional fixed, noncredential reporting fields. This does not
confirm an OLT sees the values or alter any firmware bank.
"""
import os
from pathlib import Path
import subprocess
import unittest

ROOT=Path(__file__).resolve().parents[1]
SOURCE=ROOT/"overlay/usr/lib/lua"
MODEL=SOURCE/"8311/effective_reporting_state.lua"
PROBE=SOURCE/"8311/effective_reporting_probe.lua"
CONTROLLER=SOURCE/"luci/controller/8311.lua"
VIEW=SOURCE/"luci/view/8311/config.htm"
JS=ROOT/"overlay/www/luci-static/resources/view/8311.js"
FIXTURE=ROOT/"tests/effective_reporting_fixture.lua"
VENDOR=Path(os.environ.get("AOTT_VENDOR_ROOTFS","/unavailable/vendor-rootfs"))
TEN=("equipment_id","hw_ver","cp_hw_ver_sync","sw_verA","sw_verB",
     "fw_match_b64","fw_match_num","override_active","override_commit",
     "pon_slot")


class C011ReportingTests(unittest.TestCase):
    def run_lua(self,cmd):
        r=subprocess.run(cmd+[str(FIXTURE),str(SOURCE)],cwd=ROOT,
                         capture_output=True,text=True,timeout=35)
        self.assertEqual(r.returncode,0,r.stderr)
        self.assertIn("AOTT_C011_REPORTING_FIXTURE_PASS checks=1269",
                      r.stdout)

    def test_host_lua_pure_model_and_probe(self):
        self.run_lua(["lua5.1"])

    def test_vendor_mips_lua_pure_model_and_probe(self):
        if not os.environ.get("AOTT_VENDOR_ROOTFS"):
            self.skipTest("Extracted vendor rootfs not available")
        self.assertTrue((VENDOR/"usr/bin/lua").is_file())
        self.run_lua(["qemu-mips-static","-L",str(VENDOR),
                      str(VENDOR/"usr/bin/lua")])

    def test_lua_51_compilation_and_fixed_ten(self):
        for path in (MODEL,PROBE,CONTROLLER):
            with self.subTest(path=path.name):
                p=subprocess.run(["luac5.1","-p",str(path)],
                                 capture_output=True,text=True,timeout=15)
                self.assertEqual(p.returncode,0,p.stderr)
        text=MODEL.read_text()
        self.assertIn('local FIELDS={',text)
        for id in TEN:
            self.assertIn('"'+id+'"',text)

    def test_no_sensitive_getters_or_exposed_contents(self):
        source=PROBE.read_text()
        for rejected in ("gpon_sn","vendor_id","reg_id_hex",
                         "root_pwhash","iphost_mac","iphost_hostname",
                         "iphost_domain","loid","lpwd","fwenv_set",
                         "fw_printenv","bankctl","ubiupdatevol",
                         "os.execute","io.popen","socket."):
            with self.subTest(rejected=rejected):
                self.assertNotIn(rejected,source)
        self.assertIn('"img_version"..bank',source)
        self.assertIn('model.field_set[id]~=true',source)
        self.assertIn('"/usr/sbin/fwenv_get"',source)
        self.assertIn('"/usr/bin/timeout","-k","1","3"',source)
        model=MODEL.read_text()
        for required in ("content_redacted=true",
                         "raw_value_exported=false",
                         "runtime_effect_proven=false",
                         "omci_mib_effect_proven=false",
                         "olt_received_reported_value_proven=false",
                         "actually_flashes_or_commits_firmware=false",
                         "actual_boot_bank_verified=false",
                         "no_subscriber_identity_exported=true",
                         "no_registration_secret_read=true",
                         "source_only_not_hardware_qualified=true"):
            self.assertIn(required,model)

    def test_authenticated_get_only_route(self):
        source=CONTROLLER.read_text()
        self.assertIn('require "8311.effective_reporting_probe"',source)
        self.assertEqual(source.count(
            '{"admin", "8311", "effective_reporting"}'),1)
        self.assertIn('call("action_effective_reporting")',source)
        self.assertNotIn('entry({"8311", "effective_reporting"}',source)
        handler=source.split("function action_effective_reporting()",1)[1].split(
            "function action_r5_security()",1)[0]
        for required in (
            'REQUEST_METHOD") ~= "GET"',
            'Cache-Control", "no-store, private"',
            'X-Content-Type-Options", "nosniff"',
            "pcall(effective_reporting_probe.live_reporting)",
            "snapshot.no_registration_secret_read~=true",
            "snapshot.no_subscriber_identity_exported~=true",
            "snapshot.no_raw_environment_value_exported~=true",
            "503","405","200",
        ):
            self.assertIn(required,handler)
        for forbidden in ("action_save","fwenv_set","set_8311_",
                          "http.formvalue","bankctl.sh"):
            self.assertNotIn(forbidden,handler)

    def test_manual_panel_redacts_values_and_rejects_false_runtime_claims(self):
        template=VIEW.read_text()
        self.assertIn('id="aott-reporting-effective-refresh"',template)
        self.assertIn('id="aott-reporting-effective-results"',template)
        self.assertIn("url('admin/8311/effective_reporting')",template)
        code=JS.read_text().split("function refreshReportingEffective()",1)[1].split(
            "function refreshPonEffective()",1)[0]
        for required in (
            "request8311(url,{method:'GET',cache:'no-store'})",
            "cell.textContent=value",
            "field.content_redacted!==true",
            "field.raw_value_exported!==false",
            "field.omci_mib_effect_proven!==false",
            "field.actually_flashes_or_commits_firmware!==false",
            "OLT effect unverified",
            "Reported label matches boot image label",
            "No settings changed.",
        ):
            self.assertIn(required,code)
        for forbidden in ("innerHTML","setInterval","post8311",
                          "localStorage","/dev/mtd","gpon_sn",
                          "root_pwhash","fwenv_set","reg_id_hex"):
            self.assertNotIn(forbidden,code)
        self.assertIn("refreshReportingEffective();",JS.read_text())

    def test_legacy_controller_test_stubs_probe(self):
        fixture=(ROOT/"tests/pon_me_fixture.lua").read_text()
        self.assertIn('package.preload["8311.effective_reporting_probe"]',fixture)
        self.assertIn('live_reporting=function()',fixture)


if __name__=="__main__":
    unittest.main()
