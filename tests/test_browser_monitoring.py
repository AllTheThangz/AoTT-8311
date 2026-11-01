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
    script = script.replace(
        "<%=url('admin/8311/monitoring_credential')%>",
        "/cgi-bin/luci/admin/8311/monitoring_credential")
    script = script.replace(
        '<%=monitor.credential_configured and "true" or "false"%>', "false")
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
 <input name="aott_metrics_client" value="EXAMPLE_CLIENT_IPV4">
 <button id="aott-r8-monitor-save" type="submit">Save &amp; apply</button>
 <button id="aott-r8-monitor-test" type="button">Send test event</button>
 <button id="aott-r8-token-rotate" type="button">Rotate</button>
 <button id="aott-r8-token-revoke" type="button" disabled>Revoke</button>
 <span id="aott-r8-token-state"></span>
 <div id="aott-r8-secret-panel" hidden>
 <input id="aott-r8-secret" type="text" readonly>
 <button id="aott-r8-secret-copy" type="button">Copy</button></div>
</form>
<p id="aott-r8-monitor-status" role="status"></p>
<script>%s</script></body></html>""".replace("EXAMPLE_CLIENT_IPV4", "192" + ".0.2.40") % ("a" * 64, script)


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
                if "/monitoring_credential" in req.url:
                    if "credential_action=rotate" in (req.post_data or ""):
                        body = self.responses.get("rotate", {
                            "success":True, "revision":"c"*64,
                            "credential_configured":True, "aott_metrics":"1",
                            "collector_token":"a"*64})
                    else:
                        body = self.responses.get("revoke", {
                            "success":True, "revision":"d"*64,
                            "credential_configured":False, "aott_metrics":"0"})
                    status = 200 if body.get("success") else 409
                elif "/monitoring_test" in req.url:
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
                        "aott_metrics_client":"192" + ".0.2.40",
                        "credential_configured":True,
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

    def test_read_only_token_is_visible_only_after_rotation(self):
        self.page.locator("#aott-r8-token-rotate").click()
        self.page.get_by_text("Token generated. Copy it once", exact=False).wait_for()
        self.assertEqual(self.page.locator("#aott-r8-secret").input_value(), "a"*64)
        self.assertFalse(self.page.locator("#aott-r8-secret-panel").is_hidden())
        self.assertEqual(self.page.locator('input[name="revision"]').input_value(), "c"*64)
        self.assertFalse(self.page.locator("#aott-r8-token-revoke").is_disabled())
        self.assertTrue(self.received[0][0].endswith("/monitoring_credential"))
        self.assertIn("credential_action=rotate", self.received[0][1])
        self.assertNotIn("a"*64, self.received[0][1])
        self.assertEqual(self.errors, [])

    def test_revoke_removes_token_and_disables_metrics(self):
        self.page.locator("#aott-r8-token-rotate").click()
        self.page.get_by_text("Token generated. Copy it once", exact=False).wait_for()
        self.page.on("dialog", lambda dialog: dialog.accept())
        self.page.locator("#aott-r8-token-revoke").click()
        self.page.get_by_text("Credential revoked and external metrics disabled", exact=False).wait_for()
        self.assertEqual(self.page.locator("#aott-r8-secret").input_value(), "")
        self.assertTrue(self.page.locator("#aott-r8-secret-panel").is_hidden())
        self.assertEqual(self.page.locator('select[name="aott_metrics"]').input_value(), "0")
        self.assertEqual(self.page.locator('input[name="revision"]').input_value(), "d"*64)
        self.assertEqual(self.errors, [])

    def test_failed_token_rotation_never_reveals_a_token(self):
        self.responses["rotate"] = {"success":False, "error":"Settings changed"}
        self.page.locator("#aott-r8-token-rotate").click()
        self.page.get_by_text("Credential change not confirmed", exact=False).wait_for()
        self.assertEqual(self.page.locator("#aott-r8-secret").input_value(), "")
        self.assertTrue(self.page.locator("#aott-r8-secret-panel").is_hidden())
        self.assertIn("Settings changed", self.page.locator("#aott-r8-monitor-status").inner_text())
        self.assertEqual(self.errors, [])



if __name__ == "__main__":
    unittest.main()
