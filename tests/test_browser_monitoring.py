"""Real Chromium verification for the r8 Monitoring GUI.

Loads the actual inline JavaScript from the shipped LuCI template into a
synthetic browser page. All requests are intercepted. No actual ONU,
monitoring host, or syslog service is used.
"""
import json
import os
from pathlib import Path
import re
import shutil
import unittest

ROOT = Path(__file__).resolve().parents[1]
VIEW = ROOT / "overlay/usr/lib/lua/luci/view/8311/monitoring.htm"
HOST = "http://aott.test"
try:
    from playwright.sync_api import sync_playwright
except ImportError:
    sync_playwright = None


def chromium_binary():
    return next((shutil.which(n) for n in
                 ("google-chrome-stable", "google-chrome", "chromium", "chromium-browser")
                 if shutil.which(n)), None)


def page_markup():
    # Only the framing HTML is synthetic; the actual inline monitoring JS
    # is extracted from the source template and executed unmodified.
    source = VIEW.read_text()
    scripts = re.findall(r"<script>(.*?)</script>", source, flags=re.S)
    assert len(scripts) == 1
    script = scripts[0].replace(
        "<%=url('admin/8311/monitoring_test')%>", "/cgi-bin/luci/admin/8311/monitoring_test")
    assert "<%" not in script
    return """<!doctype html><html><head><meta charset='utf-8'></head><body>
<form id="aott-r8-monitoring" action="/cgi-bin/luci/admin/8311/monitoring_save"
      method="post">
 <input name="token" type="hidden" value="synthetic-token">
 <input name="revision" type="hidden" value="%s">
 <select name="log_remote"><option value="0">Disabled</option>
 <option value="1" selected>Enabled</option></select>
 <input name="log_ip" value="collector.example.com">
 <input name="log_port" type="number" value="5514">
 <select name="log_proto"><option value="udp" selected>UDP</option>
 <option value="tcp">TCP</option></select>
 <select name="aott_metrics"><option value="0">Disabled</option>
 <option value="1" selected>Enabled</option></select>
 <button id="aott-r8-monitor-save" type="submit">Save &amp; apply</button>
 <button id="aott-r8-monitor-test" type="button">Send test event</button>
</form>
<p id="aott-r8-monitor-status" role="status"></p>
<script>%s</script></body></html>""" % ("a" * 64, script)


class MonitoringBrowserTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        needed = os.environ.get("AOTT_REQUIRE_BROWSER") == "1"
        binary = chromium_binary()
        if sync_playwright is None or binary is None:
            reason = "Real Chromium/Playwright dependencies are unavailable"
            if needed:
                raise AssertionError(reason)
            raise unittest.SkipTest(reason)
        cls.runner = sync_playwright().start()
        cls.browser = cls.runner.chromium.launch(
            headless=True, executable_path=binary,
            args=["--no-sandbox", "--disable-dev-shm-usage",
                  "--disable-background-networking", "--disable-extensions",
                  "--disable-component-update", "--no-first-run"])

    @classmethod
    def tearDownClass(cls):
        if getattr(cls, "browser", None):
            cls.browser.close()
        if getattr(cls, "runner", None):
            cls.runner.stop()

    def setUp(self):
        self.received = []
        self.responses = {}
        self.context = self.browser.new_context(viewport={"width":960,"height":700},
                                                service_workers="block")
        self.page = self.context.new_page()
        self.errors = []
        self.page.on("pageerror", lambda error: self.errors.append(str(error)))

        def handle(route):
            req = route.request
            if req.url == HOST + "/mock":
                return route.fulfill(status=200, content_type="text/html",
                                     body=page_markup())
            if req.url == HOST + "/favicon.ico":
                return route.fulfill(status=404, body="")
            if req.method == "POST" and req.url.startswith(
                HOST + "/cgi-bin/luci/admin/8311/monitoring_"):
                self.received.append((req.url, req.post_data or ""))
                if "/monitoring_test" in req.url:
                    body = self.responses.get("test", {
                        "success":True, "event_id":"0123456789abcdef",
                        "receiver_confirmed":False})
                    status = 200
                else:
                    body = self.responses.get("save", {
                        "success":True, "revision":"b" * 64,
                        "configured":True, "log_remote":"1",
                        "log_ip":"collector.example.com", "log_port":"5514",
                        "log_proto":"udp", "aott_metrics":"1",
                        "receiver_confirmed":False})
                    status = 409 if body.get("success") is False else 200
                return route.fulfill(status=status, content_type="application/json",
                                     body=json.dumps(body))
            raise AssertionError("Unexpected network request")

        self.page.route("**/*", handle)
        self.page.goto(HOST + "/mock", wait_until="load")

    def tearDown(self):
        self.context.close()

    def test_save_updates_revision_and_requires_explicit_receiver_verification(self):
        self.page.locator("#aott-r8-monitor-save").click()
        self.page.get_by_text("Settings saved and the local logging service reloaded",
                              exact=False).wait_for()
        self.assertEqual(self.page.locator('input[name="revision"]').input_value(), "b"*64)
        self.assertEqual(len(self.received), 1)
        self.assertIn("log_ip=collector.example.com", self.received[0][1])
        self.assertIn("token=synthetic-token", self.received[0][1])
        self.assertIn("not verified", self.page.locator("#aott-r8-monitor-status").inner_text())
        self.assertEqual(self.errors, [])

    def test_failed_save_does_not_claim_success(self):
        self.responses["save"] = {"success":False,
            "error":"Settings changed; refresh and review before saving"}
        self.page.locator("#aott-r8-monitor-save").click()
        self.page.get_by_text("Settings not confirmed:", exact=False).wait_for()
        self.assertEqual(self.page.locator('input[name="revision"]').input_value(), "a"*64)
        self.assertIn("changed", self.page.locator("#aott-r8-monitor-status").inner_text())
        self.assertEqual(self.errors, [])

    def test_test_event_reports_only_local_submission(self):
        self.page.locator("#aott-r8-monitor-test").click()
        self.page.get_by_text("Test marker 0123456789abcdef", exact=False).wait_for()
        self.assertIn("Verify it on your collector",
                      self.page.locator("#aott-r8-monitor-status").inner_text())
        self.assertEqual(len(self.received), 1)
        self.assertTrue(self.received[0][0].endswith("/monitoring_test"))
        self.assertIn("token=synthetic-token", self.received[0][1])
        self.assertEqual(self.errors, [])


if __name__ == "__main__":
    unittest.main()
