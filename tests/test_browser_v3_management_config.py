"""Real Chromium coverage for V3 Configuration-page management routing."""

from pathlib import Path
import json
import os
import shutil
import unittest
from urllib.parse import parse_qs, urlsplit

ROOT=Path(__file__).resolve().parents[1]
JS=ROOT/"overlay/www/luci-static/resources/view/8311.js"
VENDOR=Path(os.getenv("AOTT_VENDOR_ROOTFS",
                       "/var/tmp/aott-v3-rc3-release-20261107/build-A-final/rootfs"))
JQ=VENDOR/"www/luci-static/resources/jquery-3.7.1.min.js"
SAVED_HOST=".".join(("192","0","2","1"))
NEW_IP=".".join(("198","51","100","10"))
MASK=".".join(("255","255","255","0"))
GATEWAY=".".join(("198","51","100","1"))
DNS=".".join(("198","51","100","53"))
MAC=":".join(("02","00","00","00","00","10"))
HOST="https://"+SAVED_HOST

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    sync_playwright=None

def browser_binary():
    return next((shutil.which(n) for n in (
        "google-chrome-stable","google-chrome","chromium","chromium-browser"
    ) if shutil.which(n)),None)

def html():
    return f"""<!doctype html><html><head><meta charset="utf-8"></head><body>
<div id="config-message"></div>
<form id="8311-config" action="/admin/8311/save"
 data-management-apply-url="/admin/8311/management_apply"
 data-management-preflight-url="/admin/8311/management_preflight"
 method="post">
<input type="hidden" name="token" value="csrf-fixture">
<input type="hidden" name="complete" value="8311-v1">
<input type="hidden" name="revision" value="rev1">
<input type="hidden" name="mode" value="preview">
<input name="lct_vlan" value="321">
<input name="ipaddr" value="{NEW_IP}">
<input name="netmask" value="{MASK}">
<input name="gateway" value="{GATEWAY}">
<input name="dns_server" value="{DNS}">
<input name="lct_mac" value="{MAC}">
<input name="hostname" value="fixture-host">
<button id="save-btn" type="submit">Review changes</button>
</form>
<div id="config-review" style="display:none">
  <div id="config-diff"></div>
  <button id="config-confirm" type="button" disabled>Confirm</button>
</div>
</body></html>"""

class BrowserManagementConfigRoutingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.binary=browser_binary()
        missing=[]
        if not cls.binary: missing.append("Chromium")
        if sync_playwright is None: missing.append("Playwright")
        if not JQ.is_file(): missing.append("vendor jQuery")
        if missing:
            message="Missing browser dependencies: "+", ".join(missing)
            if os.getenv("AOTT_REQUIRE_BROWSER")=="1":
                raise AssertionError(message)
            raise unittest.SkipTest(message)
        cls.runner=sync_playwright().start()
        cls.browser=cls.runner.chromium.launch(
            executable_path=cls.binary,headless=True,
            args=["--no-sandbox","--disable-dev-shm-usage",
                  "--disable-background-networking","--disable-extensions",
                  "--no-first-run","--disable-component-update"],
        )

    @classmethod
    def tearDownClass(cls):
        if getattr(cls,"browser",None): cls.browser.close()
        if getattr(cls,"runner",None): cls.runner.stop()

    def setUp(self):
        self.context=self.browser.new_context(
            viewport={"width":1100,"height":800},
            service_workers="block",ignore_https_errors=True)
        self.page=self.context.new_page()
        self.requests=[]
        self.preview_diff=[]
        self.preview_route='live'
        self.page.route("**/*",self.route)
        self.page.goto(HOST+"/config",wait_until="load")
        self.page.add_script_tag(path=str(JQ))
        self.page.add_script_tag(path=str(JS))
        self.page.wait_for_function("typeof saveConfig === 'function'")

    def tearDown(self):
        self.context.close()

    def route(self,route):
        url=urlsplit(route.request.url)
        if route.request.resource_type=="document" and url.path=="/config":
            return route.fulfill(status=200,content_type="text/html",body=html())
        if route.request.method=="POST":
            body=parse_qs(route.request.post_data or "",keep_blank_values=True)
            self.requests.append((url.path,body))
            if url.path=="/admin/8311/save":
                mode=(body.get("mode") or [""])[0]
                if mode=="preview":
                    return route.fulfill(
                        status=200,content_type="application/json",
                        body=json.dumps({
                            "success":True,"revision":"rev1",
                            "diff":self.preview_diff,
                            "route":self.preview_route,
                            "routes":[self.preview_route] if self.preview_route!="none" else [],
                        }))
                return route.fulfill(
                    status=200,content_type="application/json",
                    body='{"success":true,"verified":["hostname"]}')
            if url.path=="/admin/8311/management_apply":
                return route.fulfill(
                    status=202,content_type="application/json",
                    body='{"success":true,"job":{"id":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"},"rollback_seconds":300}')
        return route.abort()

    def review_and_confirm(self):
        self.page.evaluate("saveConfig(document.getElementById('8311-config'))")
        self.page.wait_for_function(
            "!document.getElementById('config-confirm').disabled")
        self.page.locator("#config-confirm").click()

    def test_management_only_diff_uses_guarded_transaction_and_reconnect_link(self):
        self.preview_route="management"
        self.preview_diff=[
            {"id":"lct_vlan","name":"Management VLAN","before":"0","after":"321",
             "applies":"Guarded live management transaction"},
            {"id":"ipaddr","name":"Management IPv4","before":"old","after":"new",
             "applies":"Guarded live management transaction"},
        ]
        self.review_and_confirm()
        self.page.wait_for_function(
            "document.querySelector('#config-message a') !== null")
        paths=[path for path,_ in self.requests]
        self.assertEqual(paths.count("/admin/8311/save"),1)
        self.assertEqual(paths.count("/admin/8311/management_apply"),1)
        management=next(body for path,body in self.requests
                        if path=="/admin/8311/management_apply")
        self.assertEqual(set(management),{
            "token","vlan","ipaddr","netmask","gateway","dns_server","lct_mac"})
        self.assertEqual(management["vlan"],["321"])
        self.assertEqual(management["ipaddr"],[NEW_IP])
        self.assertEqual(management["dns_server"],[DNS])
        self.assertEqual(management["lct_mac"],[MAC])
        message=self.page.locator("#config-message").inner_text()
        self.assertIn("automatically restore",message)
        self.assertIn("300 seconds",message)
        self.assertIn("do not submit another change",message)
        self.assertEqual(
            self.page.locator("#config-message a").get_attribute("href"),
            "https://"+NEW_IP+"/admin/8311/management_preflight")

    def test_nonmanagement_diff_stays_on_normal_apply_path(self):
        self.preview_route="live"
        self.preview_diff=[
            {"id":"hostname","name":"Device hostname","before":"old","after":"fixture-host",
             "applies":"Immediately after save"},
        ]
        self.review_and_confirm()
        self.page.wait_for_function(
            "document.getElementById('config-message').textContent.includes('saved and read back')")
        paths=[path for path,_ in self.requests]
        self.assertEqual(paths.count("/admin/8311/save"),2)
        self.assertNotIn("/admin/8311/management_apply",paths)
        apply_body=self.requests[-1][1]
        self.assertEqual(apply_body["mode"],["apply"])
        self.assertEqual(apply_body["hostname"],["fixture-host"])

if __name__=="__main__":
    unittest.main()
