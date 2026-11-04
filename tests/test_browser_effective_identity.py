"""Exercise the real configuration template and JavaScript in Chromium.
All HTTP data is synthetic. No live identity or credential is requested.
"""
import json
from pathlib import Path
import re
import unittest
from urllib.parse import urlsplit
import test_browser_effective_reporting as reporting

ROOT = Path(__file__).resolve().parents[1]
VIEW = ROOT / "overlay/usr/lib/lua/luci/view/8311/config.htm"
JS = ROOT / "overlay/www/luci-static/resources/view/8311.js"
JQUERY = Path("/usr/share/javascript/jquery/jquery.min.js")
HOST = "http://aott.test"
PAGE = "/cgi-bin/luci/admin/8311/config"
ENDPOINT = "/cgi-bin/luci/admin/8311/effective_identity"
FIELDS = ("gpon_sn", "vendor_id", "reg_id_hex", "loid", "lpwd",
          "iphost_mac", "iphost_hostname", "iphost_domain", "root_pwhash")


def payload():
    rows = {}
    for name in FIELDS:
        rows[name] = dict(id=name, source_status="valid_saved_override",
            content_redacted=True, raw_value_exported=False, value_hash_exported=False,
            value_length_exported=False, stored_override_only=True,
            fallback_value_not_resolved=True, runtime_effect_proven=False,
            authentication_success_proven=False, survives_reboot_proven=False,
            hardware_qualified=False)
    return {"success": True, "data": dict(schema=1,
        group="sensitive_identity_override", fields=rows,
        summary=dict(source_fields=9, runtime_effects_verified=0, hardware_qualified=0),
        no_device_write=True, no_identity_exported=True, no_credential_hash_exported=True,
        no_raw_environment_exported=True, no_olt_or_login_authentication_claim=True,
        source_only_not_hardware_qualified=True)}


def html():
    section = re.search(r'<section id="aott-identity-effective".*?</section>',
                        VIEW.read_text(), re.S).group()
    section = section.replace("<%=esc(url('admin/8311/effective_identity'))%>", ENDPOINT)
    assert '<%' not in section
    return "<!doctype html><html><head><meta charset='utf-8'></head><body>" + section + "</body></html>"


class IdentityBrowserTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        reporting.ReportingBrowserTests.setUpClass.__func__(cls)

    @classmethod
    def tearDownClass(cls):
        reporting.ReportingBrowserTests.tearDownClass.__func__(cls)

    def setUp(self):
        self.context = self.browser.new_context(viewport={"width": 1050, "height": 820},
            service_workers="block", accept_downloads=False)
        self.page = self.context.new_page()
        self.calls, self.unexpected, self.errors = [], [], []
        self.code, self.payload = 200, payload()
        self.page.on("pageerror", lambda e: self.errors.append(str(e)))
        self.page.route("**/*", self.route)
        self.page.goto(HOST + PAGE, wait_until="load", timeout=13000)
        self.page.add_script_tag(path=str(JQUERY))
        self.page.add_script_tag(path=str(JS))
        self.page.wait_for_function("typeof refreshIdentityEffective === 'function'")

    def tearDown(self):
        self.context.close()

    def route(self, route):
        req = route.request
        path = urlsplit(req.url).path
        if req.url.startswith(HOST) and path == PAGE:
            return route.fulfill(status=200, content_type="text/html", body=html())
        if req.url.startswith(HOST) and path == ENDPOINT:
            self.calls.append((req.method, path))
            return route.fulfill(status=self.code, content_type="application/json",
                                 body=json.dumps(self.payload), headers={"Cache-Control": "no-store"})
        if req.url.startswith(HOST) and path == "/favicon.ico":
            return route.fulfill(status=404, body="")
        self.unexpected.append(req.url)
        route.abort()

    def refresh(self, failed=False):
        self.page.locator("#aott-identity-effective-refresh").click()
        needle = "readback unavailable" if failed else "check complete"
        self.page.wait_for_function("(needle) => document.getElementById('aott-identity-effective-status').textContent.includes(needle)", arg=needle)
        self.assertEqual(self.errors, [])
        self.assertEqual(self.unexpected, [])

    def test_manual_get_nine_rows_no_background_poll(self):
        self.assertEqual(self.calls, [])
        self.refresh()
        self.assertEqual(self.calls, [("GET", ENDPOINT)])
        self.assertEqual(self.page.locator("#aott-identity-effective-results tr").count(), 10)
        self.assertIn("unverified", self.page.locator("#aott-identity-effective-results").inner_text())

    def test_unset_and_read_failure_remain_distinct(self):
        self.payload["data"]["fields"]["lpwd"]["source_status"] = "unset"
        self.payload["data"]["fields"]["root_pwhash"]["source_status"] = "unavailable"
        self.refresh()
        text = self.page.locator("#aott-identity-effective-results").inner_text()
        self.assertIn("Override unset; defaults or fallback not checked", text)
        self.assertIn("Read unavailable; presence is unknown", text)

    def test_extra_value_or_hash_key_fails_closed(self):
        for key in ("raw_value", "saved_value", "hash", "length"):
            with self.subTest(key=key):
                self.payload = payload()
                self.payload["data"]["fields"]["gpon_sn"][key] = "INJECTED_PRIVATE_CONTENT"
                self.refresh(failed=True)
                self.assertNotIn("INJECTED_PRIVATE_CONTENT", self.page.locator("body").inner_text())
                self.assertEqual(self.page.locator("#aott-identity-effective-results table").count(), 0)

    def test_server_error_is_not_reflected(self):
        self.code = 503
        self.payload = {"success": False, "error": "DO_NOT_ECHO_PRIVATE_VALUE<script>bad</script>"}
        self.refresh(failed=True)
        self.assertNotIn("DO_NOT_ECHO", self.page.locator("body").inner_text())

    def test_revoked_session_clears_previous_success(self):
        self.refresh()
        self.code = 403
        self.payload = {"success": False, "error": "revoked"}
        self.refresh(failed=True)
        self.assertEqual(self.page.locator("#aott-identity-effective-results table").count(), 0)
        self.assertTrue(self.page.locator("#aott-identity-effective-results").evaluate("x=>x.hidden"))

    def test_false_hardware_or_authentication_claim_refused(self):
        for name in ("hardware_qualified", "runtime_effect_proven", "authentication_success_proven"):
            with self.subTest(name=name):
                self.payload = payload()
                self.payload["data"]["fields"]["loid"][name] = True
                self.refresh(failed=True)

    def test_external_and_protocol_relative_endpoints_refused(self):
        for url in ("https://external.example/", "//external.example/", "/\\external.example/"):
            self.page.locator("#aott-identity-effective").evaluate(
                "(x,url)=>x.setAttribute('data-effective-url',url)", url)
            self.page.locator("#aott-identity-effective-refresh").click()
            self.assertIn("invalid", self.page.locator("#aott-identity-effective-status").inner_text())
        self.assertEqual(self.calls, [])
        self.assertEqual(self.unexpected, [])

    def test_mobile_and_color_scheme_operation(self):
        self.page.set_viewport_size({"width": 375, "height": 812})
        for scheme in ("dark", "light"):
            self.page.emulate_media(color_scheme=scheme)
            self.refresh()
            self.assertEqual(self.page.locator("#aott-identity-effective-results tr").count(), 10)
            self.assertFalse(self.page.locator("#aott-identity-effective-refresh").is_disabled())


if __name__ == "__main__":
    unittest.main()
