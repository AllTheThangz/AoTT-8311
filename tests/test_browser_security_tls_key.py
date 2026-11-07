"""Actual Chromium test for the read-only Security page TLS key diagnostics.

Only the LuCI server-side directives are replaced with fixtures. The shipped
JS and page markup are tested unmodified; all requests are intercepted.
"""
import json
import os
from pathlib import Path
import re
import shutil
import unittest

ROOT=Path(__file__).resolve().parents[1]
TEMPLATE=ROOT/"overlay/usr/lib/lua/luci/view/8311/security.htm"
JS=ROOT/"overlay/www/luci-static/resources/view/8311-v2r1.js"
HOST="http://aott.test"

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    sync_playwright=None

def page_markup():
    source=TEMPLATE.read_text()
    source=source.replace("<%+header%>","").replace("<%+footer%>","")
    source=source.replace("<%=resource%>/view/8311-v2r1.js?v=aott-8311-v2r1",
                          "/static/8311-v2r1.js")
    source=re.sub(r"<%=(?:url|esc)\(.*?\)%>","#",source,flags=re.S)
    assert "<%" not in source, "Unresolved LuCI tag"
    return '<!doctype html><html data-aott-theme="dark"><head><meta charset="utf-8"></head><body>'+source+'</body></html>'

def example_response(state, warning=True):
    findings=[]
    if warning:
        findings=[{"severity":"critical" if state=="unsafe" else "warning",
                   "code":"tls_key_file_integrity" if state=="unsafe" else "tls_key_file_permissions",
                   "message":"TLS key file needs a recovery-safe permissions review."}]
    return {
        "schema":1,"sampled_at":1793590000,"authenticated_only":True,
        "root_password":"configured","root_password_persistence":"configured",
        "ssh_password_authentication":"disabled",
        "ssh_root_password_authentication":"disabled",
        "ssh_authorized_keys_present":True,"ssh_direct_interface":"lct",
        "http_redirect":"enabled","tls_private_key_permissions":state,
        "management_address":"192.0.2.1",
        "management_gateway":"192.0.2.20",
        "http_listeners":["0"+".0.0.0:80"],
        "https_listeners":["0"+".0.0.0:443"],
        "warnings":findings
    }

class SecurityTlsBrowserTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        binary=next((shutil.which(n) for n in
                    ("google-chrome-stable","google-chrome","chromium","chromium-browser")
                    if shutil.which(n)),None)
        if sync_playwright is None or not binary:
            if os.getenv("AOTT_REQUIRE_BROWSER")=="1":
                raise AssertionError("Real Chromium/Playwright unavailable")
            raise unittest.SkipTest("Real browser dependencies unavailable")
        cls.runner=sync_playwright().start()
        cls.browser=cls.runner.chromium.launch(
            executable_path=binary,headless=True,
            args=["--no-sandbox","--disable-dev-shm-usage",
                  "--disable-background-networking","--disable-extensions",
                  "--no-first-run","--disable-component-update"])
    @classmethod
    def tearDownClass(cls):
        if getattr(cls,"browser",None):cls.browser.close()
        if getattr(cls,"runner",None):cls.runner.stop()

    def setUp(self):
        self.context=self.browser.new_context(viewport={"width":900,"height":700},
                                              service_workers="block")
        self.page=self.context.new_page()
        self.data=example_response("overexposed")
        self.request_urls=[]
        self.errors=[]
        self.page.on("pageerror",lambda exc:self.errors.append(str(exc)))
        def intercept(route):
            url=route.request.url
            self.request_urls.append(url)
            if url==HOST+"/mock":
                return route.fulfill(status=200,content_type="text/html",
                                     body=page_markup())
            if url==HOST+"/static/8311-v2r1.js":
                return route.fulfill(status=200,content_type="application/javascript",
                                     body=JS.read_text())
            if url==HOST+"/cgi-bin/luci/admin/8311/security_data":
                return route.fulfill(status=200,content_type="application/json",
                                     body=json.dumps(self.data))
            if url==HOST+"/favicon.ico":
                return route.fulfill(status=404,body="")
            raise AssertionError("Unexpected network request")
        self.page.route("**/*",intercept)
        self.page.goto(HOST+"/mock",wait_until="load")

    def tearDown(self):
        self.context.close()

    def test_overexposed_private_key_status_is_visible_without_key_material(self):
        node=self.page.locator("#aott-r5-https-key-permissions")
        node.get_by_text("Too permissive").wait_for()
        self.assertEqual(node.inner_text(),"Too permissive")
        self.assertIn("recovery-safe permissions review",
                      self.page.locator("#aott-r5-security-findings").inner_text())
        self.assertNotIn("uhttpd.key",self.page.locator("body").inner_text())
        self.assertEqual(self.errors,[])
        self.assertTrue(all(u.startswith(HOST+"/") for u in self.request_urls))

    def test_restricted_status_and_unsafe_symlink_warning(self):
        self.page.locator("#aott-r5-https-key-permissions").get_by_text(
            "Too permissive").wait_for()
        self.data=example_response("restricted",False)
        self.page.locator("#aott-r5-security-refresh").click()
        self.page.locator("#aott-r5-https-key-permissions").get_by_text(
            "Restricted to root").wait_for()
        self.data=example_response("unsafe")
        self.page.locator("#aott-r5-security-refresh").click()
        self.page.locator("#aott-r5-https-key-permissions").get_by_text(
            "Unsafe file or ownership").wait_for()
        self.assertIn("Critical finding",
                      self.page.locator("#aott-r5-security-findings").inner_text())
        self.assertEqual(self.errors,[])

if __name__=="__main__":
    unittest.main()
