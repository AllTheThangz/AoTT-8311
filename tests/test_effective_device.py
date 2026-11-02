"""C-011 read-only system and virtual SFP identity evidence tests.

No live ONU connection, manufacturer EEPROM read, firmware or config write.
"""
import os
from pathlib import Path
import shutil
import subprocess
import unittest
from unittest import mock

ROOT=Path(__file__).resolve().parents[1]
MOD=ROOT/"overlay/usr/lib/lua/8311/effective_device_state.lua"
PROBE=ROOT/"overlay/usr/lib/lua/8311/effective_device_probe.lua"
CONTROLLER=ROOT/"overlay/usr/lib/lua/luci/controller/8311.lua"
VIEW=ROOT/"overlay/usr/lib/lua/luci/view/8311/config.htm"
JS=ROOT/"overlay/www/luci-static/resources/view/8311.js"
FIX=ROOT/"tests/effective_device_fixture.lua"
VENDOR=Path(os.getenv("AOTT_VENDOR_ROOTFS","/missing-vendor-rootfs"))


class DeviceEffectiveSourceTests(unittest.TestCase):
    def test_host_fixture(self):
        result=subprocess.run(["lua5.1",str(FIX),
                    str(ROOT/"overlay/usr/lib/lua")],
                  capture_output=True,text=True,timeout=20)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertIn("AOTT_C011_DEVICE_SFP_FIXTURE_PASS checks=168",
                      result.stdout)

    def test_vendor_mips_fixture(self):
        if not os.getenv("AOTT_VENDOR_ROOTFS"):
            raise unittest.SkipTest("No offline vendor rootfs configured")
        self.assertTrue((VENDOR/"usr/bin/lua").is_file())
        result=subprocess.run(["qemu-mips-static","-L",str(VENDOR),
                str(VENDOR/"usr/bin/lua"),str(FIX),
                str(ROOT/"overlay/usr/lib/lua")],
                capture_output=True,text=True,timeout=30)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertIn("AOTT_C011_DEVICE_SFP_FIXTURE_PASS checks=168",
                      result.stdout)

    def test_model_and_probe_compile(self):
        for path in (MOD,PROBE):
            with self.subTest(path=path.name):
                x=subprocess.run(["luac5.1","-p",str(path)],
                                 capture_output=True,text=True,timeout=10)
                self.assertEqual(x.returncode,0,x.stderr)

    def test_only_eleven_expected_gui_fields_are_scoped(self):
        model=MOD.read_text()
        options={
            "sfp_vendor":"vendor_name",
            "sfp_oui":"vendor_oui",
            "sfp_partno":"vendor_partno",
            "sfp_rev":"vendor_rev",
            "sfp_serial":"serial_no",
            "sfp_date":"datecode",
            "sfp_vendordata":"vendor_data",
        }
        for name,target in options.items():
            self.assertIn(name+'="'+target+'"',model)
        self.assertIn('"hostname","lang","timezone","ntp_servers"',model)
        self.assertIn("source_only_not_hardware_qualified=true",model)
        self.assertIn("runtime_effect_proven=false",model)
        self.assertIn("persist",model)
        self.assertIn("recovery_proven=false",model)
        self.assertIn("kernel_proc_hostname",model)

    def test_never_claim_uci_sfp_as_host_eeprom(self):
        model=MOD.read_text()
        self.assertIn("virtual_eeprom_configuration_not_host_readback",model)
        self.assertIn("configured_servers_do_not_prove_ntp_sync",model)
        self.assertIn("luci_config_not_active_session_language_proof",model)
        self.assertIn("uci_zonename_not_active_localtime_proof",model)
        self.assertEqual(model.count("set_observed("),2)
        self.assertIn('set_observed(fields.hostname,actual_hostname',model)

    def test_no_registration_secrets_or_native_configuration_actions(self):
        p=PROBE.read_text()
        self.assertIn('"/proc/sys/kernel/hostname"',p)
        self.assertIn('"sfp_eeprom","default",key',p)
        self.assertIn('"/usr/sbin/fwenv_get","--8311",id',p)
        for absent in ('fwenv_set','uci commit','uci:set','uci:commit',
                       'os.execute','io.popen','ssh -','ubiupdatevol',
                       'bankctl.sh','"reg_id_hex"','"root_pwhash"',
                       '"loid"','"lpwd"','"gpon_sn"','factory_mode'):
            with self.subTest(absent=absent):
                self.assertNotIn(absent,p)

    def test_read_only_admin_api_and_cached_response_controls(self):
        code=CONTROLLER.read_text()
        self.assertEqual(code.count('{"admin", "8311", "effective_device"}'),1)
        self.assertIn('call("action_effective_device")',code)
        self.assertNotIn('entry({"8311", "effective_device"}',code)
        self.assertIn('function action_effective_device()',code)
        func=code.split("function action_effective_device()",1)[1].split(
                     "function action_r5_security()",1)[0]
        self.assertIn('REQUEST_METHOD") ~= "GET"',func)
        self.assertIn('Cache-Control", "no-store, private"',func)
        self.assertIn('X-Content-Type-Options", "nosniff"',func)
        self.assertIn('pcall(effective_device_probe.live_device)',func)
        self.assertNotIn("action_save(",func)

    def test_no_automatic_network_polling_or_dynamic_html(self):
        page=VIEW.read_text()
        code=JS.read_text()
        self.assertIn('id="aott-device-effective-refresh"',page)
        self.assertIn('id="aott-device-effective-results"',page)
        self.assertIn("url('admin/8311/effective_device')",page)
        self.assertEqual(code.count("function refreshDeviceEffective()"),1)
        inner=code.split("function refreshDeviceEffective()",1)[1].split(
                   "function refreshManagementEffective()",1)[0]
        self.assertIn("request8311(url,{method:'GET',cache:'no-store'})",inner)
        self.assertIn("cell.textContent=value",inner)
        self.assertIn('Virtual EEPROM configured; host presentation unverified',inner)
        self.assertIn('NTP servers configured; synchronization unverified',inner)
        for absent in ("setInterval","post8311","innerHTML","localStorage",
                       "firmwareBank", "fwenv_set"):
            self.assertNotIn(absent,inner)

if __name__=="__main__":
    unittest.main()
