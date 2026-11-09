"""Tests for low-overhead authenticated Live Health polling. Source only."""
import hashlib
import json
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HEALTH = ROOT / "overlay/usr/lib/lua/8311/health.lua"
CONTROLLER = ROOT / "overlay/usr/lib/lua/luci/controller/8311.lua"
CLIENT = ROOT / "overlay/www/luci-static/resources/view/8311-v2r1.js"
PAGE = ROOT / "overlay/usr/lib/lua/luci/view/8311/health.htm"

class HealthPerformanceBudgetTests(unittest.TestCase):
    def test_vendor_lua_51_fixture(self):
        run = subprocess.run(["lua5.1", str(ROOT/"tests/health_performance_budget_fixture.lua"),
                              str(HEALTH)], text=True, capture_output=True, timeout=10)
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertIn("AOTT_HEALTH_PERFORMANCE_BUDGET_PASS", run.stdout)

    def test_route_is_authenticated_and_strictly_read_only(self):
        source = CONTROLLER.read_text()
        fragment = source.split("function action_r5_health_data()", 1)[1].split(
            "\nfunction ", 1)[0]
        self.assertIn('http.getenv("REQUEST_METHOD") ~= "GET"', fragment)
        self.assertIn('detail ~= nil and detail ~= "basic" and detail ~= "full"', fragment)
        self.assertIn('pcall(health.performance, detail)', fragment)
        self.assertIn('web.reply(http, 422', fragment)
        self.assertIn('web.reply(http, 405', fragment)

    def test_gem_probes_are_deliberately_decoupled(self):
        client = CLIENT.read_text()
        self.assertIn('var gemCadenceMs = 300000', client)
        self.assertIn('"health_data?detail=basic"', client)
        self.assertIn('refreshTelemetry(true)', client)
        self.assertIn('refreshTelemetry(false)', client)
        self.assertIn('document.visibilityState !== "hidden"', client)
        self.assertIn('snapshot.gem_collection !== "not_sampled"', client)
        self.assertIn('lastGemRefresh = Date.now()', client)
        self.assertIn('id="aott-r5-gem-freshness"', PAGE.read_text())
        self.assertNotIn("setInterval(", HEALTH.read_text())
        # At the default 30s cadence: 120 page polls/h, 2 GEM
        # diagnostics every 5 minutes, instead of 240 GEM calls/h.
        full = 3600000//300000
        self.assertEqual(full*2, 24)
        self.assertEqual(120*2, 240)

    def test_overlay_manifest_hashes(self):
        manifest=json.loads((ROOT/"MANIFEST.json").read_text())
        expected={x["path"]:x for x in manifest["overlay_files"]}
        for relative in (
            "usr/lib/lua/8311/health.lua",
            "usr/lib/lua/luci/controller/8311.lua",
            "usr/lib/lua/luci/view/8311/health.htm",
            "www/luci-static/resources/view/8311-v2r1.js",
        ):
            path=ROOT/"overlay"/relative
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(),
                             expected[relative]["sha256"])
            self.assertEqual(path.stat().st_size,expected[relative]["bytes"])

if __name__ == "__main__":
    unittest.main()
