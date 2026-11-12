from pathlib import Path
import json, unittest
ROOT=Path(__file__).resolve().parents[1]

class V3FoundationTests(unittest.TestCase):
    def test_release_identity(self):
        r=json.loads((ROOT/"release.json").read_text())
        self.assertEqual((r["version"],r["revision"]),("v3","r4"))
        self.assertIn("AoTT-8311-v3r4",(ROOT/"overlay/etc/8311_version").read_text())
        self.assertIn("AoTT-8311-v3 r4",(ROOT/"overlay/etc/banner").read_text())

    def test_runtime_history_primitives_ship(self):
        needed=[
            "history_model.lua","history_sampler.lua","history_aggregate.lua",
            "history_export.lua","history_preferences.lua","history_native_probe.lua",
            "history_process_lock.lua","history_snapshot_shape.lua",
            "history_snapshot_ipc.lua","history_publication_gate.lua",
            "history_http_readonly.lua",
        ]
        for name in needed:
            self.assertTrue((ROOT/"overlay/usr/lib/lua/8311"/name).is_file(),name)

    def test_opt_in_history_runtime_ships_disabled_by_default(self):
        overlay=ROOT/"overlay"
        for relative in (
            "etc/init.d/8311-history",
            "usr/libexec/8311-history-wrapper",
            "usr/libexec/8311-history-worker.lua",
            "usr/lib/lua/8311/history_config.lua",
            "usr/lib/lua/8311/history_live_snapshot.lua",
            "usr/lib/lua/luci/view/8311/history.htm",
            "www/luci-static/resources/view/aott-history.js",
            "www/luci-static/bootstrap/aott-history.css",
        ):
            self.assertTrue((overlay/relative).is_file(),relative)
        init=(overlay/"etc/init.d/8311-history").read_text()
        self.assertIn('config_get enabled main enabled 0',init)
        self.assertNotIn("procd_set_param respawn",init)

    def test_v3_status_is_authenticated_tree_only(self):
        c=(ROOT/"overlay/usr/lib/lua/luci/controller/8311.lua").read_text()
        self.assertIn('entry({"admin", "8311", "v3"}',c)
        self.assertIn('entry({"admin", "8311", "v3_status"}',c)
        self.assertNotIn('entry({"8311", "v3_status"}',c)

    def test_remote_gui_remains_default_off(self):
        m=(ROOT/"overlay/usr/lib/lua/8311/v3_capabilities.lua").read_text()
        self.assertIn('remote_management_default=false',m)
        self.assertIn('feature("remote_gui"',m)
        self.assertIn('"integrated_opt_in_unqualified"',m)
        self.assertIn("Remote HTTPS remains disabled by default",m)

if __name__=="__main__":
    unittest.main()
