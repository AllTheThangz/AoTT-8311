"""Actual Chromium tests for C-011 noncredential PON readback.

Uses shipped config section and 8311.js with synthetic intercepted
responses only. No ONU access or real subscriber identity is present.
"""
import json
import os
from pathlib import Path
import re
import shutil
import unittest
from urllib.parse import urlsplit

ROOT=Path(__file__).resolve().parents[1]
VIEW=ROOT/"overlay/usr/lib/lua/luci/view/8311/config.htm"
JS=ROOT/"overlay/www/luci-static/resources/view/8311.js"
JQUERY=Path("/usr/share/javascript/jquery/jquery.min.js")
HOST="http://aott.test"
PAGE="/cgi-bin/luci/admin/8311/config"
API="/cgi-bin/luci/admin/8311/effective_pon"
FIELDS=("pon_mode","omcc_version","iop_mask","mib_file")

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    sync_playwright=None


def template():
    s=VIEW.read_text()
    m=re.search(r'<section id="aott-pon-effective".*?</section>',s,flags=re.S)
    assert m,"Actual shipped PON readback template missing"
    fragment=m.group().replace(
        "<%=esc(url('admin/8311/effective_pon'))%>",API)
    assert "<%" not in fragment
    return ("<!doctype html><html><head><meta charset='utf-8'></head>"
            "<body>"+fragment+"</body></html>")


def example():
    data={}
    for id in FIELDS:
        data[id]={
            "id":id,"saved_value":None,"configured_value":None,
            "observed_value":None,
            "configured_source":"unavailable",
            "observed_source":"unavailable",
            "saved_to_configured":"unverified",
            "runtime_effect_proven":False,
            "hardware_qualified":False,
        }
    data["pon_mode"].update(
        saved_value="xgspon",configured_value="xgspon",
        configured_source="uci_vendor_configuration",
        saved_to_configured="match",
    )
    data["omcc_version"].update(
        saved_value="0xA3",configured_value="0xA3",
        saved_to_configured="match",
    )
    data["iop_mask"].update(
        saved_value="18",configured_value="20",
        saved_to_configured="mismatch",
    )
    data["mib_file"].update(
        saved_value="prx300_1U.ini",
        configured_value="<img src=x onerror=window.__pon_xss=true>",
        saved_to_configured="mismatch",
    )
    return {
        "success":True,
        "data":{
            "schema":1,"group":"pon_omci_noncredential",
            "no_device_write":True,"no_reboot":True,
            "no_firmware_commits":True,
            "contains_registration_secret":False,
            "source_only_not_hardware_qualified":True,
            "fields":data,
            "registration":{
                "state":51,"label":"O5.1 associated",
                "association_observed":True,
                "proves_internet_connectivity":False,
                "proves_setting_effect":False
            },
            "summary":{
                "configured":4,"saved_match_configured":2,
                "saved_mismatch_configured":2,
                "independently_effective_verified":0
            },
        }
    }


class PonOmciBrowserTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        chrome=next((shutil.which(x) for x in (
            "google-chrome-stable","google-chrome","chromium","chromium-browser")
            if shutil.which(x)),None)
        missing=[]
        if sync_playwright is None:missing.append("Playwright")
        if not chrome:missing.append("Chromium")
        if not JQUERY.is_file():missing.append("JQuery")
        if missing:
            if os.getenv("AOTT_REQUIRE_BROWSER")=="1":
                raise AssertionError("Missing required browser: "+",".join(missing))
            raise unittest.SkipTest(",".join(missing))
        cls.runner=sync_playwright().start()
        cls.browser=cls.runner.chromium.launch(
            headless=True,executable_path=chrome,
            args=["--no-sandbox","--disable-dev-shm-usage",
                  "--disable-background-networking","--disable-extensions",
                  "--no-first-run","--disable-component-update"],
        )

    @classmethod
    def tearDownClass(cls):
        if getattr(cls,"browser",None):cls.browser.close()
        if getattr(cls,"runner",None):cls.runner.stop()

    def setUp(self):
        self.ctx=self.browser.new_context(
            viewport={"width":1024,"height":768},
            service_workers="block",accept_downloads=False,
        )
        self.page=self.ctx.new_page()
        self.calls=[]
        self.unexpected=[]
        self.errors=[]
        self.status=200
        self.data=example()
        self.page.on("pageerror",lambda e:self.errors.append(str(e)))
        self.page.route("**/*",self.interceptor)
        self.page.goto(HOST+PAGE,wait_until="load",timeout=12000)
        self.page.add_script_tag(path=str(JQUERY))
        self.page.add_script_tag(path=str(JS))
        self.page.wait_for_function(
            "typeof refreshPonEffective === 'function'",timeout=8000)

    def tearDown(self):
        self.ctx.close()

    def interceptor(self,route):
        req=route.request
        path=urlsplit(req.url).path
        if req.url.startswith(HOST) and path==PAGE:
            return route.fulfill(
                status=200,content_type="text/html",body=template(),
                headers={"Cache-Control":"no-store"})
        if req.url.startswith(HOST) and path==API:
            self.calls.append((req.method,path))
            return route.fulfill(
                status=self.status,content_type="application/json",
                body=json.dumps(self.data),
                headers={"Cache-Control":"no-store"})
        if req.url.startswith(HOST) and path=="/favicon.ico":
            return route.fulfill(status=404,body="")
        self.unexpected.append((req.method,req.url))
        return route.abort()

    def press(self,needle="comparison complete"):
        self.page.locator("#aott-pon-effective-refresh").click()
        self.page.wait_for_function(
            """needle => document.getElementById('aott-pon-effective-status')
             .textContent.toLowerCase().includes(needle)""",
            arg=needle,timeout=12000)

    def test_only_explicit_admin_get_no_background_poll(self):
        self.assertEqual(self.calls,[])
        self.press()
        self.assertEqual(self.calls,[("GET",API)])
        self.assertEqual(self.unexpected,[])
        self.assertEqual(
            self.page.locator("#aott-pon-effective-results table tr").count(),5)
        self.assertFalse(self.page.locator(
            "#aott-pon-effective-results").evaluate("(node)=>node.hidden"))
        self.assertEqual(self.errors,[])

    def test_pon_o5_not_wan_or_omci_effect(self):
        self.press()
        body=self.page.locator("#aott-pon-effective-results").inner_text()
        self.assertIn("O5.1 associated",body)
        self.assertIn("does not prove ISP Internet connectivity",body)
        self.assertIn("OMCI effect unverified",body)
        self.assertIn("Saved value differs from UCI",body)
        self.assertNotIn("registration ID",body)

    def test_malicious_native_value_is_escaped_without_html_execution(self):
        self.press()
        body=self.page.locator("#aott-pon-effective-results").inner_text()
        self.assertIn("<img src=x onerror=window.__pon_xss=true>",body)
        self.assertEqual(
            self.page.locator("#aott-pon-effective-results img").count(),0)
        self.assertIsNone(self.page.evaluate("window.__pon_xss"))
        self.assertEqual(self.errors,[])

    def test_unavailable_native_state_does_not_infer_disconnection(self):
        # Lua JSON encoders omit nil fields, not necessarily emit null.
        self.data["data"]["registration"].pop("state")
        self.data["data"]["registration"].pop("association_observed")
        self.press()
        body=self.page.locator("#aott-pon-effective-results").inner_text()
        self.assertIn("PON state: unavailable",body)
        self.assertNotIn("Not O5.1",body)

    def test_incomplete_response_fails_closed(self):
        self.press()
        del self.data["data"]["fields"]["mib_file"]
        self.page.locator("#aott-pon-effective-refresh").click()
        self.page.wait_for_function(
            """() => document.getElementById('aott-pon-effective-status')
                .textContent.includes('Readback unavailable')""",timeout=12000)
        self.assertTrue(self.page.locator(
            "#aott-pon-effective-results").evaluate("(node)=>node.hidden"))
        self.assertEqual(
            self.page.locator("#aott-pon-effective-results table").count(),0)
        self.assertEqual(self.unexpected,[])

    def test_native_error_and_foreign_url_rejected(self):
        self.status=503
        self.data={"success":False,"error":"synthetic PON read failure"}
        self.page.locator("#aott-pon-effective-refresh").click()
        self.page.wait_for_function(
            """() => document.getElementById('aott-pon-effective-status')
                .textContent.includes('Readback unavailable')""",timeout=12000)
        self.assertIn("No settings changed",self.page.locator(
            "#aott-pon-effective-status").inner_text())
        self.assertEqual(self.calls,[("GET",API)])
        self.assertEqual(self.unexpected,[])
        self.page.locator("#aott-pon-effective").evaluate(
            "(node) => node.setAttribute('data-effective-url','https://elsewhere.example/x')")
        self.page.locator("#aott-pon-effective-refresh").click()
        self.assertIn("invalid",self.page.locator(
            "#aott-pon-effective-status").inner_text())
        self.assertEqual(self.calls,[("GET",API)])
        self.assertEqual(self.errors,[])

if __name__=="__main__":
    unittest.main()
