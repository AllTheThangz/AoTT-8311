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

    def test_bounded_optical_metrics_fixture(self):
        if not shutil.which("lua5.1"):
            self.skipTest("Lua 5.1 unavailable")
        result = subprocess.run(
            ["lua5.1", str(ROOT / "tests/metrics_bounded_fixture.lua"),
             str(ROOT / "overlay/usr/lib/lua/8311/tools.lua")],
            capture_output=True, text=True, timeout=12)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("BOUNDED_METRICS_FIXTURE_PASS", result.stdout)

    def test_boot_restore_runs_in_isolated_lua(self):
        if not shutil.which("lua5.1"):
            self.skipTest("Lua 5.1 unavailable")
        result = subprocess.run([
            "lua5.1", str(ROOT / "tests/monitor_restore_fixture.lua"),
            str(ROOT / "overlay/usr/lib/lua/8311/monitor_restore.lua")],
            capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("BOOTS_RESTORE_ISOLATED_PASS", result.stdout)

    def test_lua51_syntax_for_new_and_existing_controller(self):
        if not shutil.which("luac5.1"):
            self.skipTest("Lua 5.1 compiler not installed")
        for p in (
            MODULE, CONTROLLER, FIXTURE,
            ROOT / "overlay/usr/lib/lua/8311/monitor_store.lua",
            ROOT / "overlay/usr/lib/lua/8311/monitor_restore.lua",
            ROOT / "overlay/usr/libexec/8311-monitoring-restore",
            ROOT / "tests/monitor_restore_fixture.lua",
        ):
            with self.subTest(path=p):
                r = subprocess.run(["luac5.1", "-p", str(p)],
                    capture_output=True, text=True, timeout=8)
                self.assertEqual(r.returncode, 0, r.stderr)

    def test_inherited_anonymous_metrics_route_replaced_with_guard(self):
        s = CONTROLLER.read_text()
        self.assertIn('entry({"8311", "metrics"}, call("action_collector_metrics"))', s)
        self.assertIn('entry({"admin", "8311", "metrics"}', s)
        self.assertIn('monitoring.collector_authorized(http.getenv)', s)
        self.assertIn('call("action_metrics")', s)
        self.assertIn('monitoring.metrics_enabled()', s)
        self.assertIn('Cache-Control", "no-store, private"', s)
        self.assertIn('X-Content-Type-Options", "nosniff"', s)

    def test_config_writes_are_authenticated_and_csrf_checked(self):
        s = CONTROLLER.read_text()
        for name in ("action_r8_monitoring_save", "action_r8_monitoring_test",
                     "action_r8_monitoring_credential"):
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
        self.assertIn("External endpoint", s)
        self.assertIn("X-AOTT-Metrics-Token", s)
        self.assertIn('name="aott_metrics_client"', s)
        self.assertIn("aott-r8-token-rotate", s)
        self.assertIn("aott-r8-token-revoke", s)
        self.assertIn("monitor.durable_consistent", s)
        self.assertNotIn('name="log_level"', s)
        self.assertNotIn("192.168.0.", s)

    def test_collector_auth_is_strict_and_never_accepts_query_tokens(self):
        s = MODULE.read_text()
        self.assertIn('function M.collector_authorized(getenv)', s)
        self.assertIn('function M.change_credential(revision, operation)', s)
        self.assertIn('getenv("HTTPS")', s)
        self.assertIn('getenv("REMOTE_ADDR")', s)
        self.assertIn('getenv("SERVER_ADDR")', s)
        self.assertIn('getenv("HTTP_X_AOTT_METRICS_TOKEN")', s)
        self.assertIn('trusted_local_address(u, local_addr)', s)
        self.assertIn('web.digest_text("AoTT-8311:v2r8:metrics:" .. token)', s)
        self.assertNotIn('getenv("HTTP_X_FORWARDED_FOR")', s)
        self.assertNotIn('getenv("QUERY_STRING")', s)
        self.assertNotIn("io.popen(", s)

    def test_durable_store_fails_closed_and_precedes_uci_change(self):
        s = MODULE.read_text()
        self.assertIn('local store = require "8311.monitor_store"', s)
        self.assertIn("store.write(target)", s)
        self.assertIn("store.same_live(saved)", s)
        self.assertIn("store.same_live(values)", s)
        self.assertIn("local function safe_to_update(snapshot)", s)
        self.assertIn("safe_to_update(before)", s)
        self.assertIn('operation ~= "revoke"', s)
        self.assertIn("safe_to_update(old)", s)
        self.assertLess(s.index("store.write(target)"),
                        s.index("set_options(u, before.section, values)"))
        credential = s.split("function M.change_credential", 1)[1]
        self.assertLess(credential.index("store.write(desired)"),
                        credential.index("set_options(u, old.section, values)"))
        self.assertNotIn('store.write(old.', credential)

    def test_boot_hook_restores_before_logger_without_ubus(self):
        defaults = (ROOT / "overlay/etc/uci-defaults/zzz-8311").read_text()
        sysctl = (ROOT / "overlay/etc/init.d/sysctl").read_text()
        entry = (ROOT / "overlay/usr/libexec/8311-monitoring-restore").read_text()
        script = (ROOT / "overlay/usr/lib/lua/8311/monitor_restore.lua").read_text()
        self.assertIn("START=11", sysctl)
        self.assertIn("apply_defaults", sysctl)
        self.assertIn("/usr/bin/timeout -k 1 12", sysctl)
        self.assertIn("/usr/libexec/8311-monitoring-restore", sysctl)
        self.assertIn("/ptconf/8311-monitoring/config.json", sysctl)
        self.assertNotIn("/usr/libexec/8311-monitoring-restore", defaults)
        self.assertIn('require("8311.monitor_restore").run()', entry)
        self.assertIn('source.read()', script)
        self.assertIn('"/sbin/uci", "-q"', script)
        self.assertIn('invoke("changes", "system")', script)
        self.assertIn('invoke("revert", "system")', script)
        self.assertNotIn('os.execute(', script)
        self.assertNotIn("ubus", script)
        self.assertNotIn("firmware-install", defaults)
        # The source-only package forbids symlinks. Use the already
        # provisioned vendor S11sysctl symlink instead.
        self.assertFalse((ROOT/"overlay/etc/rc.d/S118311-monitoring").exists())
        self.assertFalse((ROOT/"overlay/etc/init.d/8311-monitoring").exists())

    def test_vendor_s11_sysctl_logic_remains_byte_equivalent_before_hook(self):
        source = (ROOT / "overlay/etc/init.d/sysctl").read_text()
        self.assertTrue(source.startswith("#!/bin/sh /etc/rc.common"))
        self.assertEqual(source.count("apply_defaults"), 2)
        self.assertLess(source.index("sysctl -e -p"), source.index("8311-monitoring-restore"))
        self.assertEqual(source.count("/usr/libexec/8311-monitoring-restore"), 1)

    def test_private_vendor_cli_harness_enforces_chroot_isolation(self):
        source = (ROOT / "tests/test_vendor_boot_cli_v2r8.py").read_text()
        self.assertIn('"unshare", "--mount", "--propagation", "private"', source)
        self.assertIn("mount --bind /proc", source)
        self.assertIn("chroot", source)
        self.assertIn('(self.config / "system").write_text', source)
        self.assertIn('self.assertEqual(self.cli("changes", "system"), (0, ""))', source)
        self.assertNotIn('"-p", self.internal_stage', source)
        self.assertNotIn('"-P", self.internal_stage', source)

    def test_new_components_are_in_source_manifest(self):
        m = json.loads((ROOT / "MANIFEST.json").read_text())
        entries = {e["path"] for e in m["overlay_files"]}
        self.assertIn("usr/lib/lua/8311/monitoring.lua", entries)
        self.assertIn("usr/lib/lua/luci/view/8311/monitoring.htm", entries)
        for path in (
            "usr/lib/lua/8311/monitor_store.lua",
            "usr/lib/lua/8311/monitor_restore.lua",
            "usr/libexec/8311-monitoring-restore",
            "etc/init.d/sysctl",
        ):
            self.assertIn(path, entries)


if __name__ == "__main__":
    unittest.main()
