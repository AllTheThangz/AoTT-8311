"""H-026 real Chromium tests for explicit same-origin history API client.

Loads the exact source-only H-016 preview plus the *uninstalled*
H-026 client candidate. HTTP requests are intercepted. No actual
service, credentials, network or hardware is contacted.
"""
import json
import os
from pathlib import Path
import shutil
import subprocess
import unittest
from urllib.parse import urlsplit

ROOT=Path(__file__).resolve().parents[1]
UI=ROOT/"prototypes/history/ui"
HTML=UI/"history.html"
STYLE=UI/"history.css"
VIEW=UI/"history.js"
CLIENT=UI/"history_authenticated_client.js"
FIXTURE=ROOT/"tests/h016_history_export_fixture.lua"
SOURCE=ROOT/"prototypes/history"

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    sync_playwright=None


def chromium():
    return next((shutil.which(name) for name in (
        "google-chrome-stable","google-chrome",
        "chromium","chromium-browser") if shutil.which(name)),None)


def projection():
    output=subprocess.run(
        ["lua5.1",str(FIXTURE),str(SOURCE),"emit_json"],
        cwd=ROOT,capture_output=True,text=True,timeout=20)
    if output.returncode:
        raise AssertionError(output.stderr)
    payload=[line.split("=",1)[1] for line in output.stdout.splitlines()
             if line.startswith("AOTT_H016_JSON_PAYLOAD=")]
    if len(payload)!=1:
        raise AssertionError("Expected exactly one real H-016 JSON fixture")
    return payload[0]


class AuthenticatedClientChromiumTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.executable=chromium()
        unavailable=[]
        if not cls.executable:unavailable.append("Chromium")
        if sync_playwright is None:unavailable.append("Playwright")
        if not shutil.which("lua5.1"):unavailable.append("Lua 5.1")
        if unavailable:
            msg="Missing H-026 Chromium dependencies: "+", ".join(unavailable)
            if os.environ.get("AOTT_REQUIRE_BROWSER")=="1":
                raise AssertionError(msg)
            raise unittest.SkipTest(msg)
        cls.raw=projection()
        cls.runner=sync_playwright().start()
        cls.browser=cls.runner.chromium.launch(
            executable_path=cls.executable,headless=True,
            args=["--no-sandbox","--disable-dev-shm-usage",
                  "--disable-background-networking",
                  "--disable-extensions","--no-first-run",
                  "--disable-component-update"],
        )

    @classmethod
    def tearDownClass(cls):
        if getattr(cls,"browser",None):cls.browser.close()
        if getattr(cls,"runner",None):cls.runner.stop()

    def setUp(self):
        self.context=self.browser.new_context(
            viewport={"width":1100,"height":850},
            service_workers="block",accept_downloads=False,
        )
        self.page=self.context.new_page()
        self.unexpected=[]
        self.api_calls=[]
        self.page_errors=[]
        self.status=200
        self.mime="application/json; charset=utf-8"
        self.body=self.raw
        self.redirect=False
        self.page.on("pageerror",lambda e:self.page_errors.append(str(e)))
        self.page.route("**/*",self.route)
        self.page.goto("http://aott.test/h026/history.html",
                       wait_until="load",timeout=15000)
        self.page.wait_for_function(
            "window.AoTTHistoryView && window.AoTTHistoryView.sourceOnly",
            timeout=7000)
        self.page.add_script_tag(path=str(CLIENT))
        self.page.wait_for_function(
            "window.AoTTHistoryAdminPreview && window.AoTTHistoryAdminPreview.sourceOnly",
            timeout=7000)

    def tearDown(self):
        self.context.close()

    def route(self,route):
        req=route.request
        url=urlsplit(req.url)
        static={
            "/h026/history.html":("text/html",HTML),
            "/h026/history.css":("text/css",STYLE),
            "/h026/history.js":("application/javascript",VIEW),
        }
        if url.scheme=="http" and url.hostname=="aott.test" and url.path in static:
            mime,path=static[url.path]
            return route.fulfill(status=200,content_type=mime,
                                 body=path.read_text(),
                                 headers={"Cache-Control":"no-store"})
        if (url.scheme=="http" and url.hostname=="aott.test" and
                url.path=="/admin/8311/history_data"):
            self.api_calls.append(req)
            if self.redirect:
                return route.fulfill(
                    status=302,body="",
                    headers={"Location":"https://example.invalid/leak"})
            return route.fulfill(
                status=self.status,content_type=self.mime,
                body=self.body,headers={"Cache-Control":"no-store"})
        self.unexpected.append(req.url)
        route.abort()

    def load(self):
        return self.page.evaluate(
            "()=>window.AoTTHistoryAdminPreview.load()")

    def test_no_automatic_network_and_no_installed_endpoint_claim(self):
        self.assertEqual(self.api_calls,[])
        self.assertFalse(self.page.locator("#history-json").is_enabled())
        self.assertFalse(
            self.page.evaluate("window.AoTTHistoryAdminPreview.autoFetch"))
        self.assertFalse(
            self.page.evaluate("window.AoTTHistoryAdminPreview.endpointInstalled"))
        self.assertEqual(self.unexpected,[])
        self.assertEqual(self.page_errors,[])

    def test_explicit_authenticated_get_renders_source_history(self):
        result=self.load()
        self.assertTrue(result["loaded"])
        self.assertTrue(result["sourceOnly"])
        self.assertFalse(result["liveHardwareVerified"])
        self.assertTrue(result["noLiveProbesStarted"])
        self.assertEqual(len(self.api_calls),1)
        call=self.api_calls[0]
        self.assertEqual(call.method,"GET")
        self.assertEqual(urlsplit(call.url).path,"/admin/8311/history_data")
        self.assertEqual(urlsplit(call.url).query,"")
        self.assertEqual(call.headers.get("accept"),"application/json")
        self.assertTrue(self.page.locator("#history-json").is_enabled())
        self.assertIn("Source-only cached observations",
                      self.page.locator("#prototype-notice").inner_text())
        self.assertEqual(self.page.locator("#wan-state").inner_text(),
                         "Not verified")
        self.assertEqual(self.unexpected,[])
        self.assertEqual(self.page_errors,[])

    def test_unauthenticated_status_and_server_error_do_not_render(self):
        for status in (401,403,500,503):
            with self.subTest(http_status=status):
                self.status=status
                result=self.load()
                self.assertFalse(result["loaded"])
                self.assertFalse(self.page.locator("#history-json").is_enabled())
                self.assertIn("unavailable",
                              self.page.locator("#prototype-notice").inner_text())
        self.assertEqual(len(self.api_calls),4)
        self.assertEqual(self.unexpected,[])
        self.assertEqual(self.page_errors,[])

    def test_auth_expiry_clears_prior_history_and_disables_exports(self):
        first=self.load()
        self.assertTrue(first["loaded"])
        self.assertTrue(self.page.locator("#history-json").is_enabled())
        self.assertGreater(self.page.locator("#history-sample-rows tr").count(),0)
        self.status=403
        refused=self.load()
        self.assertFalse(refused["loaded"])
        self.assertFalse(self.page.locator("#history-json").is_enabled())
        self.assertFalse(self.page.locator("#history-csv").is_enabled())
        self.assertEqual(self.page.locator("#history-sample-rows tr").count(),0)
        self.assertEqual(self.page.locator("#history-event-rows tr").count(),0)
        self.assertEqual(self.page.locator("#wan-state").inner_text(),
                         "Not verified")
        self.assertEqual(self.unexpected,[])
        self.assertEqual(self.page_errors,[])

    def test_html_mime_and_invalid_json_are_rejected(self):
        self.mime="text/html; charset=utf-8"
        result=self.load()
        self.assertFalse(result["loaded"])
        self.assertFalse(self.page.locator("#history-json").is_enabled())
        self.mime="application/json"
        self.body="<script>leak()</script>"
        result=self.load()
        self.assertFalse(result["loaded"])
        self.assertEqual(self.page.locator("script[src='https://example.invalid']").count(),0)
        self.assertEqual(self.unexpected,[])
        self.assertEqual(self.page_errors,[])

    def test_inconsistent_live_claims_are_rejected(self):
        data=json.loads(self.raw)
        data["actual_isp_uptime_unverified"]=False
        self.body=json.dumps(data,separators=(",",":"))
        result=self.load()
        self.assertFalse(result["loaded"])
        self.assertFalse(self.page.locator("#history-json").is_enabled())
        self.assertEqual(self.unexpected,[])
        self.assertEqual(self.page_errors,[])

    def test_oversized_content_is_rejected_without_render(self):
        self.body=self.raw+(" "*70_000)
        result=self.load()
        self.assertFalse(result["loaded"])
        self.assertFalse(self.page.locator("#history-json").is_enabled())
        self.assertEqual(self.unexpected,[])
        self.assertEqual(self.page_errors,[])

    def test_redirect_cannot_leak_request_to_external_origin(self):
        self.redirect=True
        result=self.load()
        self.assertFalse(result["loaded"])
        self.assertEqual(len(self.api_calls),1)
        self.assertEqual(self.unexpected,[])
        self.assertEqual(self.page_errors,[])

    def test_duplicate_load_calls_do_not_make_multiple_requests(self):
        results=self.page.evaluate("""async () => {
            return await Promise.all([
                window.AoTTHistoryAdminPreview.load(),
                window.AoTTHistoryAdminPreview.load()
            ]);
        }""")
        self.assertEqual(len(self.api_calls),1)
        self.assertEqual(sum(x["loaded"] is True for x in results),1)
        self.assertEqual(self.unexpected,[])
        self.assertEqual(self.page_errors,[])


if __name__=="__main__":
    unittest.main()
