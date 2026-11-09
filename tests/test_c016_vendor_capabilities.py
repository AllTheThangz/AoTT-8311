from pathlib import Path
import importlib.util, json, os, sys, unittest

ROOT=Path(__file__).resolve().parents[1]
TOOLS=ROOT/"tools"
OUTPUT=ROOT/"docs/C-016-VENDOR-CAPABILITY-REGISTRY.json"
VENDOR=Path(os.getenv("AOTT_VENDOR_ROOTFS",
    "/var/tmp/aott-v3-rc3-release-20261107/build-A-final/rootfs"))

sys.path.insert(0,str(TOOLS))
spec=importlib.util.spec_from_file_location(
    "c016",TOOLS/"build_c016_vendor_capabilities.py")
c016=importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(c016)

class C016VendorCapabilityRegistryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not VENDOR.is_dir(): raise unittest.SkipTest("offline vendor rootfs unavailable")
        cls.report=c016.build(ROOT,VENDOR)
        cls.rows={r["id"]:r for r in cls.report["capabilities"]}

    def test_all_discovered_records_are_classified(self):
        self.assertEqual(self.report["summary"]["unclassified_remaining"],0)
        self.assertEqual(self.report["vendor_config_domains"],13)
        self.assertEqual(self.report["vendor_config_option_names"],89)
        self.assertGreaterEqual(self.report["summary"]["classified_records"],120)

    def test_existing_aott_mappings_are_not_double_counted(self):
        expected={
            "uci:gpon:iop_mask":"iop_mask",
            "uci:gpon:nSerial":"gpon_sn",
            "uci:gpon:pon_mode":"pon_mode",
            "uci:gpon:regID":"reg_id_hex",
            "uci:luci:lang":"lang",
            "uci:uhttpd:redirect_https":"https_redirect",
        }
        for key,value in expected.items():
            self.assertEqual(self.rows[key]["classification"],"EXISTING_AOTT_CONTROL")
            self.assertEqual(self.rows[key]["mapped_aott_field"],value)

    def test_runtime_supported_access_controls_are_discovered(self):
        for option in ("PasswordAuth","RootPasswordAuth","Port","RootLogin",
                       "SSHKeepAlive","IdleTimeout","MaxAuthTries","GatewayPorts"):
            row=self.rows["uci:dropbear:"+option]
            self.assertTrue(row["native_runtime_consumer_discovered"])
            self.assertIn(row["classification"],
                          {"PRODUCT_CONTROL_CANDIDATE","EXPERT_CONTROL_CANDIDATE"})
        self.assertEqual(
            self.rows["uci:dropbear:DirectInterface"]["classification"],
            "DEPENDENCY_MANAGED")

    def test_web_runtime_controls_and_tls_ownership_are_distinct(self):
        for option in ("listen_http","listen_https","script_timeout",
                       "network_timeout","max_requests","max_connections",
                       "http_keepalive","tcp_keepalive","rfc1918_filter"):
            self.assertEqual(
                self.rows["uci:uhttpd:"+option]["classification"],
                "PRODUCT_CONTROL_CANDIDATE")
        for option in ("cert","key","key_type","ec_curve","days","bits"):
            self.assertEqual(
                self.rows["uci:uhttpd:"+option]["classification"],
                "SUBSYSTEM_MANAGED")

    def test_low_level_pon_knobs_stay_test_olt_only(self):
        experimental=set(self.report["test_olt_experimental_candidate_ids"])
        for option in ("key_size","plev_cap","ploam_timeout_0",
                       "ploam_timeout_6","ploam_timeout_cpi","ploam_timeout_cpl","psk"):
            self.assertIn("uci:gpon:"+option,experimental)

    def test_framework_schema_not_inflated_into_product_features(self):
        for domain in ("firewall","rpcd","ucitrack"):
            rows=[r for r in self.report["capabilities"] if r["domain"]==domain and r["option"]]
            self.assertTrue(rows)
            self.assertTrue(all(r["classification"]=="INTERNAL_FRAMEWORK" for r in rows))

    def test_committed_registry_matches_source_and_contains_no_values(self):
        committed=json.loads(OUTPUT.read_text())
        self.assertEqual(committed,self.report)
        self.assertFalse(committed["live_device_queried"])
        self.assertFalse(committed["device_configuration_modified"])
        self.assertFalse(committed["contains_runtime_values_or_credentials"])
        text=OUTPUT.read_text()
        for forbidden in ("root:root","192.168.","BEGIN PRIVATE KEY","PLOAM"):
            self.assertNotIn(forbidden,text)

if __name__=="__main__":
    unittest.main()
