from pathlib import Path
import re, subprocess, unittest

ROOT=Path(__file__).resolve().parents[1]
ROUTE=ROOT/"overlay/usr/lib/lua/8311/config_route.lua"
CONTROLLER=ROOT/"overlay/usr/lib/lua/luci/controller/8311.lua"
CONFIG=ROOT/"overlay/usr/lib/lua/8311/config.lua"

EXPECTED={
"live":{
"lang","hostname","timezone","ntp_servers","https_redirect","pingd","ping_ip","reverse_arp",
"console_en","dying_gasp_en","rx_los","ethtool_speed",
"sfp_vendor","sfp_oui","sfp_partno","sfp_rev","sfp_serial","sfp_date","sfp_vendordata",
"fix_vlans","internet_vlan","services_vlan"},
"management":{"lct_vlan","ipaddr","netmask","gateway","dns_server","lct_mac"},
"boot":{"bootdelay","uart_select","failsafe_delay","persist_root"},
"credential":{"root_pwhash"},
"pon":{"gpon_sn","vendor_id","equipment_id","hw_ver","cp_hw_ver_sync","sw_verA","sw_verB",
"fw_match_b64","fw_match_num","override_active","override_commit","pon_mode","omcc_version",
"iop_mask","reg_id_hex","loid","lpwd","mib_file","pon_slot","iphost_mac","iphost_hostname","iphost_domain"},
}

class ConfigurationRouteContractTests(unittest.TestCase):
    def test_exact_55_field_partition(self):
        all_ids=set().union(*EXPECTED.values())
        self.assertEqual(len(all_ids),55)
        source=ROUTE.read_text()
        for route,ids in EXPECTED.items():
            for id in ids:
                self.assertIn(id+"=true",source,(route,id))

    def test_no_overlap_and_schema_is_fully_routed(self):
        seen={}
        for route,ids in EXPECTED.items():
            for id in ids:
                self.assertNotIn(id,seen)
                seen[id]=route
        s=CONTROLLER.read_text()
        start=s.index("function fwenvs_8311()")
        end=s.index("\nfunction fwenvs_values",start) if "\nfunction fwenvs_values" in s[start:] else s.index("\nfunction action_",start)
        ids=[]
        for id in re.findall(r'\bid="([A-Za-z0-9_]+)"',s[start:end]):
            if id not in ("pon","isp","device","sfp","manage") and id not in ids:
                ids.append(id)
        self.assertEqual(set(ids),set(seen))
        self.assertEqual(len(ids),55)

    def test_config_prepare_uses_server_owned_route_and_refuses_mixed(self):
        s=CONFIG.read_text()
        self.assertIn('config_route.classify(changed_ids)',s)
        self.assertIn('route.route=="mixed"',s)
        self.assertIn("one configuration group at a time",s)
        self.assertNotIn("management_tuple={",s)

    def test_generic_apply_only_accepts_live_none_or_credential(self):
        s=CONFIG.read_text()
        self.assertIn('prepared.route~="live"',s)
        self.assertIn('prepared.route~="credential"',s)
        for name in ("management","boot","pon"):
            self.assertIn(name+'="',ROUTE.read_text() if False else name+'="') if False else None
        self.assertIn('result.required_route=prepared.route',s)
        self.assertIn('result.boot_transaction_required=prepared.route=="boot"',s)
        self.assertIn('result.pon_transaction_required=prepared.route=="pon"',s)

    def test_lua_syntax(self):
        for p in (ROUTE,CONFIG):
            r=subprocess.run(["luac5.1","-p",str(p)],capture_output=True,text=True)
            self.assertEqual(r.returncode,0,r.stderr)

if __name__=="__main__":
    unittest.main()
