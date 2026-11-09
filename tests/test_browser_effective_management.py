"""Real Chromium tests for the C-011 authenticated, manual read-only view.

Renders the exact C-011 section from the shipped LuCI configuration
template and executes the actual full 8311.js. All network requests are
intercepted. Nothing reaches a device or external monitoring service.
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
ENDPOINT="/cgi-bin/luci/admin/8311/effective_management"
FIELDS=("lct_vlan","ipaddr","netmask","gateway","dns_server","pingd",
        "ping_ip","lct_mac","reverse_arp","https_redirect")

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    sync_playwright=None


def markup():
    source=VIEW.read_text()
    match=re.search(
        r'<section id="aott-management-effective".*?</section>',
        source,flags=re.S,
    )
    assert match, "Actual running-management template section missing"
    section=match.group()
    section=section.replace(
        "<%=esc(url('admin/8311/effective_management'))%>",
        ENDPOINT,
    )
    assert "<%" not in section
    return ('<!doctype html><html><head><meta charset="utf-8"></head>'
            '<body>'+section+'</body></html>')


def response():
    rows={}
    for field in FIELDS:
        rows[field]={
            "id":field,
            "saved_value":None,
            "configured_value":None,
            "observed_value":None,
            "configured_source":"unavailable",
            "observed_source":"unavailable",
            "saved_to_observed":"unverified",
            "runtime_effect_proven":False,
            "hardware_qualified":False,
        }
    ip=".".join(["192","0","2","15"])
    rows["ipaddr"].update(saved_value=ip,configured_value=ip,
                          observed_value=ip,
                          configured_source="uci_lct",
                          observed_source="kernel_ipv4_interface",
                          saved_to_observed="match",
                          runtime_effect_proven=True)
    rows["dns_server"].update(
        configured_value="<img src=x onerror=window.__aott_xss=true>",
        configured_source="uci_lct",
    )
    rows["https_redirect"].update(
        saved_value="1",configured_value="1",configured_source="uci_uhttpd",
        observed_value="1",observed_source="independent_http_response",
        saved_to_observed="match",runtime_effect_proven=True,
    )
    return {
        "success":True,
        "data":{"schema":1,
                "source":"read_only_management_observation",
                "management_section":"lct",
                "management_interface":"eth0_0_1_lct",
                "selection_reason":"kernel_address_detected",
                "no_device_write":True,
                "no_reboot":True,
                "no_hidden_hardware_qualification":True,
                "fields":rows,
                "summary":{"kernel_observed":2,"configured_only":1,
                           "unverified":6,
                           "effective_and_saved_match":2,
                           "drift_from_saved":0}}
    }


class EffectiveManagementBrowserTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        binary=next((shutil.which(n) for n in
                     ("google-chrome-stable","google-chrome",
                      "chromium","chromium-browser") if shutil.which(n)),None)
        missing=[]
        if sync_playwright is None:missing.append("Playwright")
        if binary is None:missing.append("Chrome")
        if not JQUERY.is_file():missing.append("jQuery fixture")
        if missing:
            if os.getenv("AOTT_REQUIRE_BROWSER")=="1":
                raise AssertionError("Missing headless dependencies: "+",".join(missing))
            raise unittest.SkipTest(",".join(missing))
        cls.runner=sync_playwright().start()
        cls.browser=cls.runner.chromium.launch(
            executable_path=binary,headless=True,
            args=["--no-sandbox","--disable-dev-shm-usage",
                  "--disable-background-networking","--disable-extensions",
                  "--no-first-run","--disable-component-update"],
        )

    @classmethod
    def tearDownClass(cls):
        if getattr(cls,"browser",None):cls.browser.close()
        if getattr(cls,"runner",None):cls.runner.stop()

    def setUp(self):
        self.context=self.browser.new_context(
            viewport={"width":1024,"height":768},
            service_workers="block",accept_downloads=False,
        )
        self.page=self.context.new_page()
        self.bad_requests=[]
        self.requests=[]
        self.errors=[]
        self.status=200
        self.payload=response()
        self.page.on("pageerror",lambda e:self.errors.append(str(e)))
        self.page.route("**/*",self.route)
        self.page.goto(HOST+PAGE,wait_until="load",timeout=15000)
        self.page.add_script_tag(path=str(JQUERY))
        self.page.add_script_tag(path=str(JS))
        self.page.wait_for_function(
            "typeof refreshManagementEffective === 'function'",
            timeout=8000,
        )

    def tearDown(self):
        self.context.close()

    def route(self,route):
        req=route.request
        path=urlsplit(req.url).path
        if req.url.startswith(HOST) and path==PAGE:
            return route.fulfill(status=200,content_type="text/html",
                                 body=markup(),headers={"Cache-Control":"no-store"})
        if req.url.startswith(HOST) and path==ENDPOINT:
            self.requests.append((req.method,path))
            return route.fulfill(status=self.status,content_type="application/json",
                                 body=json.dumps(self.payload),
                                 headers={"Cache-Control":"no-store"})
        if req.url.startswith(HOST) and path=="/favicon.ico":
            return route.fulfill(status=404,body="")
        self.bad_requests.append((req.method,req.url))
        return route.abort()

    def click_and_wait(self,needle="comparison complete"):
        self.page.locator("#aott-management-effective-refresh").click()
        self.page.wait_for_function(
            """needle => document.getElementById(
                'aott-management-effective-status').textContent
                    .toLowerCase().includes(needle)""",
            arg=needle,timeout=12000,
        )

    def test_no_background_poll_or_any_mutating_request(self):
        self.assertEqual(self.requests,[])
        self.assertEqual(self.bad_requests,[])
        self.click_and_wait()
        self.assertEqual(self.requests,[("GET",ENDPOINT)])
        self.assertEqual(self.bad_requests,[])
        self.assertEqual(
            self.page.locator("#aott-management-effective-results table tr").count(),
            11)
        self.assertFalse(
            self.page.locator("#aott-management-effective-results").evaluate(
                "(el)=>el.hidden"))
        self.assertEqual(self.errors,[])

    def test_kernel_observed_is_distinguished_from_only_configured(self):
        self.click_and_wait()
        body=self.page.locator("#aott-management-effective-results").inner_text()
        self.assertIn("Running value observed; matches saved",body)
        self.assertIn("Configuration found; running effect unverified",body)
        self.assertIn("Not independently verified",body)
        self.assertIn("Independently observed fields: 2",body)
        self.assertIn("eth0_0_1_lct",body)
        self.assertIn("HTTP to HTTPS redirect",body)

    def test_html_in_an_api_value_is_plain_text(self):
        self.click_and_wait()
        self.assertIn("<img src=x onerror=window.__aott_xss=true>",
                      self.page.locator("#aott-management-effective-results").inner_text())
        self.assertEqual(self.page.locator(
            "#aott-management-effective-results img").count(),0)
        self.assertIsNone(self.page.evaluate("window.__aott_xss"))
        self.assertEqual(self.errors,[])

    def test_incomplete_response_fails_closed_and_discards_partial_table(self):
        self.click_and_wait()
        del self.payload["data"]["fields"]["gateway"]
        self.page.locator("#aott-management-effective-refresh").click()
        self.page.wait_for_function(
            """() => document.getElementById(
                'aott-management-effective-status').textContent
                .includes('Readback unavailable')""",timeout=12000)
        self.assertTrue(self.page.locator(
            "#aott-management-effective-results").evaluate("(el)=>el.hidden"))
        self.assertEqual(self.page.locator(
            "#aott-management-effective-results table").count(),0)
        self.assertEqual(self.bad_requests,[])

    def test_server_error_does_not_claim_success_or_change_settings(self):
        self.status=503
        self.payload={"success":False,"error":"synthetic inaccessible runtime"}
        self.page.locator("#aott-management-effective-refresh").click()
        self.page.wait_for_function(
            """() => document.getElementById(
                'aott-management-effective-status').textContent
                .includes('Readback unavailable')""",timeout=12000)
        self.assertIn("No settings changed",
                      self.page.locator("#aott-management-effective-status").inner_text())
        self.assertEqual(self.requests,[("GET",ENDPOINT)])
        self.assertEqual(self.bad_requests,[])
        self.assertEqual(self.errors,[])

    def test_external_endpoint_rejected_before_any_request(self):
        self.page.locator("#aott-management-effective").evaluate(
            "(el)=>el.setAttribute('data-effective-url','https://bad.example/collect')")
        self.page.locator("#aott-management-effective-refresh").click()
        self.assertIn("invalid",self.page.locator(
            "#aott-management-effective-status").inner_text())
        self.assertEqual(self.requests,[])
        self.assertEqual(self.bad_requests,[])


if __name__=="__main__":
    unittest.main()
