"""v2r8 monitoring backend contract and isolated Lua tests."""

import json
from pathlib import Path
import re
import shutil
import subprocess
import unittest


ROOT = Path(__file__).resolve().parents[1]
CONTROLLER = ROOT / "overlay/usr/lib/lua/luci/controller/8311.lua"
MODULE = ROOT / "overlay/usr/lib/lua/8311/monitoring.lua"
TEMPLATE = ROOT / "overlay/usr/lib/lua/luci/view/8311/monitoring.htm"
FIXTURE = ROOT / "tests/monitoring_fixture.lua"


class MonitoringBackendTests(unittest.TestCase):
    def test_backend_runs_with_mocked_uci_and_logger(self):
        if not shutil.which("lua5.1"):
            self.skipTest("Lua 5.1 not installed")
        result = subprocess.run(
            ["lua5.1", str(FIXTURE), str(MODULE)],
            capture_output=True, text=True, timeout=12, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("MONITORING_FIXTURE_PASS", result.stdout)

    def test_lua51_syntax_for_new_and_existing_controller(self):
        if not shutil.which("luac5.1"):
            self.skipTest("Lua 5.1 compiler not installed")
        for p in (MODULE, CONTROLLER, FIXTURE):
            with self.subTest(path=p):
                r = subprocess.run(["luac5.1", "-p", str(p)],
                    capture_output=True, text=True, timeout=8)
                self.assertEqual(r.returncode, 0, r.stderr)

    def test_inherited_anonymous_metrics_route_removed(self):
        s = CONTROLLER.read_text()
        self.assertNotIn('entry({"8311", "metrics"}', s)
        self.assertIn('entry({"admin", "8311", "metrics"}', s)
        self.assertIn('call("action_metrics")', s)
        self.assertIn('monitoring.metrics_enabled()', s)
        self.assertIn('Cache-Control", "no-store, private"', s)
        self.assertIn('X-Content-Type-Options", "nosniff"', s)

    def test_config_writes_are_authenticated_and_csrf_checked(self):
        s = CONTROLLER.read_text()
        for name in ("action_r8_monitoring_save", "action_r8_monitoring_test"):
            anchor = "function " + name + "()"
            self.assertIn(anchor, s)
            body = s.split(anchor, 1)[1].split("\nend", 1)[0]
            self.assertIn("dispatcher.context.authsession", body)
            self.assertIn("dispatcher.test_post_security(true)", body)
            self.assertIn("operation_form(", body)

    def test_only_existing_safe_logger_and_no_agent(self):
        s = MODULE.read_text()
        self.assertIn('"/etc/init.d/log", "reload"', s)
        self.assertIn('"/usr/bin/logger"', s)
        self.assertIn('web.lock("/tmp/8311-monitoring.lock")', s)
        self.assertIn('changes("system")', s)
        self.assertIn('u:commit("system")', s)
        self.assertIn('system_section(u)', s)
        for forbidden in ("os.execute(", "io.popen(", "loadstring(", "/etc/init.d/network",
                          "logrotate", "prometheus-node-exporter"):
            self.assertNotIn(forbidden, s)

    def test_interface_never_claims_remote_delivery_or_severity_control(self):
        s = TEMPLATE.read_text()
        self.assertIn('name="log_ip"', s)
        self.assertIn('name="log_port"', s)
        self.assertIn('name="log_proto"', s)
        self.assertIn('name="aott_metrics"', s)
        self.assertIn('name="revision"', s)
        self.assertIn('name="token"', s)
        self.assertIn('Receiver', s)
        self.assertIn("receiver's availability cannot be inferred", s.lower())
        self.assertIn("filter log levels on your collector", s)
        self.assertIn("requires an authenticated administrator session", s.lower())
        self.assertNotIn('name="log_level"', s)
        self.assertNotIn("192.168.0.", s)

    def test_new_components_are_in_source_manifest(self):
        m = json.loads((ROOT / "MANIFEST.json").read_text())
        entries = {e["path"] for e in m["overlay_files"]}
        self.assertIn("usr/lib/lua/8311/monitoring.lua", entries)
        self.assertIn("usr/lib/lua/luci/view/8311/monitoring.htm", entries)


if __name__ == "__main__":
    unittest.main()
