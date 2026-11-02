"""C-011 source-only readback for three ISP VLAN controls.

No ONU access, traffic control operations, VLAN hook execution,
firmware changes, credential reads or service changes.
"""
from __future__ import annotations
import os
from pathlib import Path
import subprocess
import unittest

ROOT=Path(__file__).resolve().parents[1]
MODEL=ROOT/"overlay/usr/lib/lua/8311/effective_vlan_state.lua"
PROBE=ROOT/"overlay/usr/lib/lua/8311/effective_vlan_probe.lua"
CONTROLLER=ROOT/"overlay/usr/lib/lua/luci/controller/8311.lua"
VIEW=ROOT/"overlay/usr/lib/lua/luci/view/8311/config.htm"
JS=ROOT/"overlay/www/luci-static/resources/view/8311.js"
FIXTURE=ROOT/"tests/effective_vlan_fixture.lua"
VENDOR=Path(os.environ.get("AOTT_VENDOR_ROOTFS","/missing/offline/vendor"))


class VlanSourceTests(unittest.TestCase):
    def test_portable_host_fixture(self):
        p=subprocess.run(["lua5.1",str(FIXTURE),
                          str(ROOT/"overlay/usr/lib/lua")],
                         capture_output=True,text=True,timeout=22)
        self.assertEqual(p.returncode,0,p.stderr)
        self.assertIn("AOTT_C011_ISP_VLAN_FIXTURE_PASS checks=114",p.stdout)

    def test_portable_vendor_mips_fixture(self):
        if not os.environ.get("AOTT_VENDOR_ROOTFS"):
            raise unittest.SkipTest("Offline vendor MIPS rootfs not supplied")
        binary=VENDOR/"usr/bin/lua"
        self.assertTrue(binary.is_file())
        p=subprocess.run(["qemu-mips-static","-L",str(VENDOR),
            str(binary),str(FIXTURE),str(ROOT/"overlay/usr/lib/lua")],
            capture_output=True,text=True,timeout=34)
        self.assertEqual(p.returncode,0,p.stderr)
        self.assertIn("AOTT_C011_ISP_VLAN_FIXTURE_PASS checks=114",p.stdout)

    def test_two_modules_compile_and_are_source_only(self):
        for path in (MODEL,PROBE):
            with self.subTest(module=path.name):
                p=subprocess.run(["luac5.1","-p",str(path)],
                                 capture_output=True,text=True,timeout=12)
                self.assertEqual(p.returncode,0,p.stderr)
        s=MODEL.read_text()
        self.assertIn('{"fix_vlans","internet_vlan","services_vlan"}',s)
        self.assertIn("source_only_not_hardware_qualified=true",s)
        self.assertIn("runtime_effect_proven=specific_rule_verified",s)
        self.assertIn("internet_path_verified=false",s)
        self.assertIn("current_traffic_control_rules_verified=verified",s)
        self.assertIn("topology_match_proves_rules_current=false",s)

    def test_readonly_only_fixed_three_environment_keys(self):
        source=PROBE.read_text()
        self.assertIn('{"fix_vlans","internet_vlan","services_vlan"}',source)
        self.assertIn('"/usr/sbin/fwenv_get","--8311",id',source)
        self.assertIn('"/usr/sbin/8311-detect-config.sh","-H"',source)
        self.assertIn('"/bin/pidof","8311-vlansd.sh"',source)
        self.assertIn('"/tmp/8311-config.sh"',source)
        self.assertIn("st.modedec~=600",source)
        self.assertIn("st.uid~=0",source)
        self.assertIn("st.type~=\"reg\"",source)
        self.assertIn("st.size>4096",source)
        self.assertIn('"/usr/bin/timeout","-k","1","5"',source)

    def test_never_run_hook_or_tc_write_or_collect_registration(self):
        s=PROBE.read_text()
        for bad in (
            "fwenv_set","fw_setenv","uci commit","uci:set",
            "system.exec","os.execute","io.popen",
            "tc filter", "8311-fix-vlans.sh", "vlan_fixes_hook.sh",
            "bankctl.sh","ubiupdatevol","fw_printenv",
            '"/usr/bin/pon","psg"',"gpon_sn","reg_id_hex",
            "loid","lpwd","root_pwhash","vendor_id"
        ):
            with self.subTest(disallowed=bad):
                self.assertNotIn(bad,s)
        self.assertIn("No input from the browser",s) if "No input from the browser" in s else self.assertIn("Only three fixed environment names",s)

    def test_source_hash_can_be_collected_only_for_valid_receipt(self):
        s=PROBE.read_text()
        self.assertIn("if parsed then",s)
        self.assertIn("safe(adapter.network_hash)",s)
        self.assertIn("model.parse_last_reconciliation(snapshot)",s)
        self.assertIn("return model.inspect(saved,snapshot,current_hash,daemon,",s)
        self.assertIn("local st=fs.lstat(path)",s)
        self.assertIn("fs.readfile(path,4097)",s)

    def test_authenticated_get_only_noncredential_route(self):
        s=CONTROLLER.read_text()
        self.assertEqual(s.count('{"admin", "8311", "effective_vlan"}'),1)
        self.assertIn('call("action_effective_vlan")',s)
        self.assertNotIn('entry({"8311", "effective_vlan"}',s)
        fn=s.split("function action_effective_vlan()",1)[1].split(
            "function action_r5_security()",1)[0]
        self.assertIn('REQUEST_METHOD") ~= "GET"',fn)
        self.assertIn('Cache-Control", "no-store, private"',fn)
        self.assertIn('X-Content-Type-Options", "nosniff"',fn)
        self.assertIn("pcall(effective_vlan_probe.live_vlan)",fn)
        self.assertIn("contains_registration_secret ~= false",fn)
        self.assertNotIn("action_save",fn)
        self.assertNotIn("fwenv_set",fn)

    def test_manual_panel_no_automatic_poll_and_no_false_tc_success(self):
        html=VIEW.read_text()
        script=JS.read_text()
        self.assertIn('id="aott-vlan-effective-refresh"',html)
        self.assertIn('id="aott-vlan-effective-results"',html)
        self.assertIn("url('admin/8311/effective_vlan')",html)
        self.assertEqual(script.count("function refreshVlanEffective()"),1)
        body=script.split("function refreshVlanEffective()",1)[1].split(
            "function refreshPonEffective()",1)[0]
        self.assertIn("request8311(url,{method:'GET',cache:'no-store'})",body)
        self.assertIn("cell.textContent=value",body)
        self.assertIn("not independently verified",body)
        self.assertIn("Even a selected-rule match does not prove all rules",body)
        for bad in ("innerHTML","setInterval","post8311","localStorage",
                    "fwenv_set","gpon_sn","reg_id","loid","lpwd"):
            with self.subTest(disallowed=bad):
                self.assertNotIn(bad,body)

    def test_legacy_controller_fixture_stubs_module(self):
        s=(ROOT/"tests/pon_me_fixture.lua").read_text()
        self.assertIn('package.preload["8311.effective_vlan_probe"]',s)
        self.assertIn('live_vlan=function()',s)


if __name__=="__main__":
    unittest.main()
