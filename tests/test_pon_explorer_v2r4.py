"""Offline regression checks for the v2r4 PON ME Explorer.

These tests use text sources and dummy LuCI route names. They do not access
a subscriber system, collect data, or embed site-specific identifiers.
"""
from pathlib import Path
import re
import shutil
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]
CONTROLLER = (ROOT / "overlay/usr/lib/lua/luci/controller/8311.lua").read_text()
VIEW = (ROOT / "overlay/usr/lib/lua/luci/view/8311/pon_me.htm").read_text()
JS = (ROOT / "overlay/www/luci-static/resources/view/8311.js").read_text()
HEALTH = (ROOT / "overlay/usr/lib/lua/luci/view/8311/health.htm").read_text()
SECURITY = (ROOT / "overlay/usr/lib/lua/luci/view/8311/security.htm").read_text()


class PonMeExplorerTests(unittest.TestCase):
    def test_listing_uses_bounded_read_only_omci_command(self):
        self.assertIn('web.capture({"/usr/bin/omci_pipe.sh", "md"},262144)', CONTROLLER)

    def test_omci_listing_escapes_untrusted_strings(self):
        self.assertIn("tools.html_escape(line)", CONTROLLER)
        self.assertIn("tools.html_escape(href)", CONTROLLER)
        self.assertIn("tonumber(class) <= 65535", CONTROLLER)
        self.assertIn("tonumber(instance) <= 65535", CONTROLLER)

    def test_device_aware_absolute_route_generation(self):
        self.assertIn('dispatcher.build_url("admin", "8311", "pon_dump", class, instance)', CONTROLLER)
        self.assertIn('luci.dispatcher.build_url("admin", "8311", "pon_dump")', VIEW)
        self.assertIn('data-dump-base=', VIEW)
        self.assertIn('pcdata(luci.dispatcher.build_url(', VIEW)

    def test_inputs_are_range_checked_on_client_and_server(self):
        self.assertIn('id:match("^%d+$")', CONTROLLER)
        self.assertIn('#id > 5 or tonumber(id) > 65535', CONTROLLER)
        self.assertRegex(JS, r'const validId\s*=\s*value\s*=>')
        self.assertIn('Number(value) <= 65535', JS)

    def test_raw_omci_reply_is_never_cached(self):
        self.assertIn('http.header("Cache-Control", "no-store, private")', CONTROLLER)
        self.assertIn('http.header("X-Content-Type-Options", "nosniff")', CONTROLLER)
        self.assertIn("cache:false", JS)

    def test_raw_omci_output_uses_text_only_rendering(self):
        self.assertIn('http.prepare_content("text/plain; charset=utf-8")', CONTROLLER)
        self.assertIn("$('#me_dump').text(data", JS)
        self.assertNotIn("$('#me_dump').html(", JS)

    def test_read_failure_cannot_echo_untrusted_raw_output(self):
        self.assertIn('http.status(502, "Managed entity read failed")', CONTROLLER)
        self.assertIn('http.write("Managed entity lookup did not complete successfully.")', CONTROLLER)

    def test_unavailable_or_invalid_route_fails_closed(self):
        self.assertIn("base.startsWith('/')", JS)
        self.assertIn("base.startsWith('//')", JS)
        self.assertRegex(JS, r"admin\\/8311\\/pon_dump")
        self.assertIn("Invalid Managed Entity identifier. No request was sent.", JS)

    def test_no_em_dash_placeholders_in_diagnostic_views(self):
        for view in (HEALTH, SECURITY):
            self.assertNotIn("\u2014", view)
            self.assertIn("Not available", view)

    def test_lua51_privacy_and_routing_fixture(self):
        if not shutil.which("lua5.1"):
            self.skipTest("Lua 5.1 unavailable on local system")
        result = subprocess.run(
            ["lua5.1", "tests/pon_me_fixture.lua",
             "overlay/usr/lib/lua/luci/controller/8311.lua"],
            cwd=ROOT, capture_output=True, text=True, timeout=10
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("privacy and routing checks passed", result.stdout)


if __name__ == "__main__":
    unittest.main()
