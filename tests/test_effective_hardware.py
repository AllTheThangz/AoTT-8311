"""C-011 advanced hardware readback, source-only and no device mutations.

No network connection, login credential, firmware bank or active GPIO
setter is accessed by the tests. Portable fixtures use synthetic states.
"""
import os
from pathlib import Path
import subprocess
import unittest

ROOT=Path(__file__).resolve().parents[1]
MOD=ROOT/"overlay/usr/lib/lua/8311/effective_hardware_state.lua"
PROBE=ROOT/"overlay/usr/lib/lua/8311/effective_hardware_probe.lua"
CONTROLLER=ROOT/"overlay/usr/lib/lua/luci/controller/8311.lua"
VIEW=ROOT/"overlay/usr/lib/lua/luci/view/8311/config.htm"
JS=ROOT/"overlay/www/luci-static/resources/view/8311.js"
FIXTURE=ROOT/"tests/effective_hardware_fixture.lua"
VENDOR=Path(os.getenv("AOTT_VENDOR_ROOTFS","/unavailable/offline/vendor"))


class AdvancedHardwareSourceTests(unittest.TestCase):
    def test_synthetic_portable_host_fixture(self):
        run=subprocess.run(["lua5.1",str(FIXTURE),
                            str(ROOT/"overlay/usr/lib/lua")],
                           capture_output=True,text=True,timeout=25)
        self.assertEqual(run.returncode,0,run.stderr)
        self.assertIn("AOTT_C011_HARDWARE_FIXTURE_PASS checks=167",run.stdout)

    def test_vendor_mips_lua_fixture(self):
        if not os.environ.get("AOTT_VENDOR_ROOTFS"):
            raise unittest.SkipTest("No offline vendor MIPS rootfs")
        self.assertTrue((VENDOR/"usr/bin/lua").is_file())
        run=subprocess.run(["qemu-mips-static","-L",str(VENDOR),
            str(VENDOR/"usr/bin/lua"),str(FIXTURE),
            str(ROOT/"overlay/usr/lib/lua")],
            capture_output=True,text=True,timeout=35)
        self.assertEqual(run.returncode,0,run.stderr)
        self.assertIn("AOTT_C011_HARDWARE_FIXTURE_PASS checks=167",run.stdout)

    def test_both_lua_modules_compile(self):
        for module in (MOD,PROBE):
            with self.subTest(file=module.name):
                p=subprocess.run(["luac5.1","-p",str(module)],
                     capture_output=True,text=True,timeout=10)
                self.assertEqual(p.returncode,0,p.stderr)

    def test_exact_eight_noncredential_fields_and_base_key_scoping(self):
        source=MOD.read_text()
        for key in ("bootdelay","uart_select","console_en",
                    "dying_gasp_en","rx_los","ethtool_speed",
                    "failsafe_delay","persist_root"):
            self.assertIn('"'+key+'"',source)
        self.assertIn("local BASE={bootdelay=true,uart_select=true}",source)
        self.assertIn("runtime_effect_proven=false",source)
        self.assertIn("hardware_qualified=false",source)
        self.assertIn("reboot_persistence_proven=false",source)
        self.assertIn("recovery_proven=false",source)
        self.assertIn("source_fields=8",source)
        self.assertIn("contains_credential_material=false",source)

    def test_no_credential_export_or_arbitrary_shell_execution(self):
        code=PROBE.read_text()
        self.assertIn('"/usr/sbin/fwenv_get"',code)
        self.assertIn('args[#args+1]="--8311"',code)
        self.assertIn('"/sys/class/gpio/gpio"..n',code)
        self.assertIn('"/sys/class/net/eth0_0/speed"',code)
        self.assertIn('"/bin/pidof","8311-rx_los.sh"',code)
        self.assertIn('uci:get("optic","common","dg_dis")',code)
        for forbidden in (
            "fwenv_set","fw_setenv","uci:set","uci:commit",
            "os.execute", "io.popen", "tc filter add",
            "gpio/export","/direction\", \"w",
            "bankctl.sh","ubiupdatevol","reboot(",
            "gpon_sn","reg_id_hex","loid","lpwd",
            "root_"+"pwhash", "bootcmd",
        ):
            with self.subTest(never=forbidden):
                executable="\n".join(line for line in code.splitlines()
                    if line.strip() and not line.lstrip().startswith("--"))
                self.assertNotIn(forbidden,executable)

    def test_kernel_gpio_or_link_not_advanced_function_proof(self):
        s=MOD.read_text()
        self.assertIn("gpio_levels_prove_serial_or_optic_signalling=false",s)
        self.assertIn("proves_speed_override_applied=false",s)
        self.assertIn("proves_subscriber_internet=false",s)
        self.assertIn("rx_los_daemon_proves_alarm=false",s)
        self.assertIn("early_uart_observed_after_boot=false",s)
        self.assertIn("failsafe_startup_timing_verified=false",s)
        self.assertIn("persistent_root_recovery_verified=false",s)
        self.assertNotIn("runtime_effect_proven=true",s)

    def test_get_only_admin_api(self):
        s=CONTROLLER.read_text()
        self.assertEqual(s.count('{"admin", "8311", "effective_hardware"}'),1)
        self.assertIn('call("action_effective_hardware")',s)
        self.assertNotIn('entry({"8311", "effective_hardware"}',s)
        action=s.split("function action_effective_hardware()",1)[1].split(
                      "function action_r5_security()",1)[0]
        self.assertIn('REQUEST_METHOD") ~= "GET"',action)
        self.assertIn('Cache-Control", "no-store, private"',action)
        self.assertIn('X-Content-Type-Options", "nosniff"',action)
        self.assertIn("pcall(effective_hardware_probe.live_hardware)",action)
        self.assertIn("contains_credential_material ~= false",action)
        self.assertNotIn("action_save",action)
        self.assertNotIn("fwenv_set",action)

    def test_manual_read_only_ui_with_safe_text(self):
        page=VIEW.read_text()
        code=JS.read_text()
        self.assertIn('id="aott-hardware-effective-refresh"',page)
        self.assertIn('id="aott-hardware-effective-results"',page)
        self.assertIn("url('admin/8311/effective_hardware')",page)
        self.assertIn("Root credentials and hashes are excluded.",page)
        self.assertEqual(code.count("function refreshHardwareEffective()"),1)
        ui=code.split("function refreshHardwareEffective()",1)[1].split(
                "function refreshVlanEffective()",1)[0]
        self.assertIn("request8311(url,{method:'GET',cache:'no-store'})",ui)
        self.assertIn("cell.textContent=value",ui)
        self.assertIn("runtime_effect_proven!==false",ui)
        self.assertIn("contains_credential_material!==false",ui)
        for forbidden in ("innerHTML","setInterval","post8311",
                          "localStorage","fwenv_set","reg_id","gpon_sn"):
            self.assertNotIn(forbidden,ui)

    def test_pme_legacy_mock_stubs_source_only_probe(self):
        s=(ROOT/"tests/pon_me_fixture.lua").read_text()
        self.assertIn('package.preload["8311.effective_hardware_probe"]',s)
        self.assertIn('live_hardware=function()',s)


if __name__=="__main__":
    unittest.main()
