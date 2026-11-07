from pathlib import Path
import json, unittest
ROOT=Path(__file__).resolve().parents[1]

class V3FoundationTests(unittest.TestCase):
    def test_release_identity(self):
        r=json.loads((ROOT/"release.json").read_text())
        self.assertEqual((r["version"],r["revision"]),("v3","r1"))
        self.assertIn("AoTT-8311-v3r1",(ROOT/"overlay/etc/8311_version").read_text())
        self.assertIn("AoTT-8311-v3 r1",(ROOT/"overlay/etc/banner").read_text())

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

    def test_v3_status_is_authenticated_tree_only(self):
        c=(ROOT/"overlay/usr/lib/lua/luci/controller/8311.lua").read_text()
        self.assertIn('entry({"admin", "8311", "v3"}',c)
        self.assertIn('entry({"admin", "8311", "v3_status"}',c)
        self.assertNotIn('entry({"8311", "v3_status"}',c)

    def test_remote_gui_remains_default_off(self):
        m=(ROOT/"overlay/usr/lib/lua/8311/v3_capabilities.lua").read_text()
        self.assertIn('remote_management_default=false',m)
        self.assertIn('feature("remote_gui"',m)
        self.assertIn('"disabled"',m)

if __name__=="__main__":
    unittest.main()
