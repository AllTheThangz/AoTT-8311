"""C-011 effective management observation tests, source only.

There are no live ONU requests, configuration writes, reboot operations,
public endpoints, provisioning values or private-image copies here.
"""
from __future__ import annotations
import hashlib
import os
from pathlib import Path
import re
import shutil
import subprocess
import unittest

ROOT=Path(__file__).resolve().parents[1]
MODEL=ROOT/"overlay/usr/lib/lua/8311/effective_state.lua"
PROBE=ROOT/"overlay/usr/lib/lua/8311/effective_probe.lua"
GUI=ROOT/"overlay/usr/lib/lua/luci/view/8311/config.htm"
CONTROLLER=ROOT/"overlay/usr/lib/lua/luci/controller/8311.lua"
JS=ROOT/"overlay/www/luci-static/resources/view/8311.js"
FIXTURE=ROOT/"tests/effective_management_fixture.lua"
VENDOR=Path(os.getenv("AOTT_VENDOR_ROOTFS","/nonexistent/offline_vendor"))

class EffectiveManagementSourceTests(unittest.TestCase):
    def test_host_lua_model_and_probe_behavior(self):
        p=subprocess.run(["lua5.1",str(FIXTURE),
            str(ROOT/"overlay/usr/lib/lua")],
            capture_output=True,text=True,timeout=25)
        self.assertEqual(p.returncode,0,p.stderr)
        self.assertIn("AOTT_C011_EFFECTIVE_STATE_FIXTURE_PASS checks=97",p.stdout)

    def test_real_vendor_mips_lua_fixture(self):
        if not os.getenv("AOTT_VENDOR_ROOTFS"):
            raise unittest.SkipTest("No OFFLINE vendor rootfs supplied")
        binary=VENDOR/"usr/bin/lua"
        self.assertTrue(binary.is_file())
        p=subprocess.run(["qemu-mips-static","-L",str(VENDOR),
            str(binary),str(FIXTURE),str(ROOT/"overlay/usr/lib/lua")],
            capture_output=True,text=True,timeout=35)
        self.assertEqual(p.returncode,0,p.stderr)
        self.assertIn("AOTT_C011_EFFECTIVE_STATE_FIXTURE_PASS checks=97",p.stdout)

    def test_lua_syntax_on_both_modules(self):
        for p in (MODEL,PROBE):
            with self.subTest(file=p.name):
                out=subprocess.run(["luac5.1","-p",str(p)],
                    capture_output=True,text=True,timeout=12)
                self.assertEqual(out.returncode,0,out.stderr)

    def test_fixed_source_names_no_secret_probes_or_unauthorized_mutations(self):
        p=PROBE.read_text()
        self.assertIn('"ipaddr","netmask","gateway","dns_server","pingd"',p)
        self.assertIn('"ping_ip","lct_mac","reverse_arp","https_redirect"',p)
        self.assertIn('"/usr/sbin/fwenv_get","--8311",name',p)
        self.assertIn('"/sbin/ip","-o","-4","addr","show","dev",iface',p)
        self.assertIn('"/sbin/ip","-4","route","show","default"',p)
        self.assertIn('"/sys/class/net/"..iface.."/address"',p)
        for forbidden in (
            "fwenv_set", "fw_setenv", "uci set", "uci commit", "uci:commit",
            "ubiupdatevol", "bankctl.sh", "reboot", "runuser", "ssh ",
            '"/usr/sbin/fw_printenv"', "system.exec", "os.execute", "io.popen",
            "root_pwhash", "gpon_sn", "reg_id_hex", "lpwd", "loid",
        ):
            with self.subTest(token=[REDACTED]
                # "reboot" is a permitted *commentary* denial.
                if forbidden=="reboot":
                    self.assertNotRegex(p,r'["\'](?:/sbin/)?reboot["\']')
                else:
                    self.assertNotIn(forbidden,p)

    def test_lua_model_distinguishes_saved_configured_and_observed(self):
        p=MODEL.read_text()
        for entry in (
            "saved_value", "configured_value", "observed_value",
            "saved_to_configured", "configured_to_observed",
            "saved_to_observed", "runtime_effect_proven",
            "persist_after_reboot_proven", "recovery_proven",
            "hardware_qualified", "no_device_write",
            "kernel_ipv4_interface", "kernel_default_route_via",
            "uci_dns_is_not_effective_resolver_evidence",
            "running_daemon_does_not_prove_feature_enabled",
        ):
            self.assertIn(entry,p)
        self.assertNotIn("fwenv_set",p)
        self.assertNotIn("uci commit",p)
        self.assertNotIn("os.execute",p)

    def test_only_authenticated_admin_route_exposes_management_observation(self):
        s=CONTROLLER.read_text()
        registration='entry({"admin", "8311", "effective_management"},'
        self.assertEqual(s.count(registration),1)
        self.assertNotIn('entry({"8311", "effective_management"}',s)
        self.assertIn('call("action_effective_management")',s)
        self.assertIn('http.getenv("REQUEST_METHOD") ~= "GET"',s)
        self.assertIn('http.header("Cache-Control", "no-store, private")',s)
        self.assertIn("pcall(effective_probe.live_management)",s)
        self.assertIn("Read-only GET required",s)
        self.assertIn("Effective management readback unavailable",s)

    def test_ui_is_manual_read_only_not_polling_or_a_new_setter(self):
        page=GUI.read_text()
        js=JS.read_text()
        self.assertIn('id="aott-management-effective-refresh"',page)
        self.assertIn('id="aott-management-effective-results"',page)
        self.assertIn("url('admin/8311/effective_management')",page)
        self.assertIn("function refreshManagementEffective()",js)
        body=js.split("function refreshManagementEffective()",1)[1].split(
            "function openHookEditor()",1)[0]
        self.assertIn("request8311(url, {method:'GET',cache:'no-store'})",body)
        self.assertNotIn("setInterval",body)
        self.assertNotIn("post8311",body)
        self.assertNotIn(".innerHTML",body)
        self.assertNotIn("localStorage",body)
        self.assertIn("cell.textContent=value",body)
        self.assertIn("field.runtime_effect_proven===true",body)
        self.assertIn("No settings changed.",body)

    def test_saved_effect_is_not_claimed_qualified(self):
        for p in (MODEL,PROBE):
            text=p.read_text()
            self.assertIn("read-only",text.lower())
            self.assertNotRegex(text,r"\bFULLY_QUALIFIED\b")
        self.assertIn("hardware_qualified=false",MODEL.read_text())

if __name__=="__main__":
    unittest.main()
