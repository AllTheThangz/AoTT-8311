"""Actual Chromium test for C-011 manual device and virtual SFP readback.

The shipped LuCI section and 8311.js are rendered unmodified, except
for resolving the LuCI URL tag to a synthetic local endpoint. All network
requests are intercepted. No customer/stick/network data are used.
"""
import json
import os
from pathlib import Path
import re
import shutil
import unittest
from urllib.parse import urlsplit

ROOT=Path(__file__).resolve().parents[1]
TEMPLATE=ROOT/"overlay/usr/lib/lua/luci/view/8311/config.htm"
SCRIPT=ROOT/"overlay/www/luci-static/resources/view/8311.js"
JQUERY=Path("/usr/share/javascript/jquery/jquery.min.js")
HOST="http://aott.test"
PAGE="/cgi-bin/luci/admin/8311/config"
API="/cgi-bin/luci/admin/8311/effective_device"
FIELDS=(
 "hostname","lang","timezone","ntp_servers",
 "sfp_vendor","sfp_oui","sfp_partno","sfp_rev",
 "sfp_serial","sfp_date","sfp_vendordata",
)

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    sync_playwright=None


def html():
    source=TEMPLATE.read_text()
    m=re.search(r'<section id="aott-device-effective".*?</section>',
                source,flags=re.S)
    assert m,"Shipped read-only device section missing"
    section=m.group()
    section=section.replace(
        "<%=esc(url('admin/8311/effective_device'))%>",API)
    assert "<%" not in section
    return ('<!doctype html><html><head><meta charset="utf-8">'
            '</head><body>'+section+'</body></html>')


def payload():
    fields={}
    for key in FIELDS:
        fields[key]={
            "id":key,"saved_value":None,"configured_value":None,
            "observed_value":None,"configured_source":"unavailable",
            "observed_source":"unavailable",
            "saved_to_observed":"unverified","runtime_effect_proven":False,
            "hardware_qualified":False,
        }
    fields["hostname"].update(
        saved_value="house-onu",configured_value="house-onu",
        observed_value="house-onu",
        observed_source="kernel_proc_hostname",
        saved_to_observed="match",runtime_effect_proven=True,
    )
    fields["lang"].update(
        saved_value="en",configured_value="en",observed_value="en",
        observed_source="active_luci_request_language",
        saved_to_observed="match",runtime_effect_proven=True,
    )
    fields["timezone"].update(
        saved_value="UTC",configured_value="UTC",observed_value="UTC",
        observed_source="tmp_localtime_zoneinfo_target",
        saved_to_observed="match",runtime_effect_proven=True,
    )
    fields["ntp_servers"].update(
        saved_value="ntp1.example ntp2.example",
        configured_value="ntp1.example ntp2.example",
        configured_source="uci_system_ntp_server_list",
        observed_value="ntp1.example ntp2.example",
        observed_source="active_ntpd_process_arguments",
        saved_to_observed="match",runtime_effect_proven=True,
    )
    fields["sfp_vendor"].update(
        configured_value="<img src=x onerror=window.__sfp_injected=true>",
        configured_source="uci_virtual_sfp_eeprom",
    )
    fields["sfp_serial"].update(configured_value="TESTSERIAL0001",
                                configured_source="uci_virtual_sfp_eeprom")
    return {"success":True,"data":{
        "schema":1,"source":"read_only_device_and_virtual_sfp",
        "no_device_write":True,"no_reboot":True,
        "no_firmware_commits":True,
        "source_only_not_hardware_qualified":True,
        "fields":fields,
        "summary":{"observed_runtime":4,"configured_only":2,"unverified":5}
    }}


class ReadOnlyDeviceBrowserTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        binary=next((shutil.which(x) for x in (
            "google-chrome-stable","google-chrome","chromium","chromium-browser"
        ) if shutil.which(x)),None)
        absent=[]
        if sync_playwright is None:absent.append("Playwright")
        if not binary:absent.append("Chromium")
        if not JQUERY.is_file():absent.append("jQuery")
        if absent:
            if os.getenv("AOTT_REQUIRE_BROWSER")=="1":
                raise AssertionError("Browser dependencies missing: "+",".join(absent))
            raise unittest.SkipTest(",".join(absent))
        cls.runner=sync_playwright().start()
        cls.browser=cls.runner.chromium.launch(
            headless=True,executable_path=binary,
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
            viewport={"width":1050,"height":780},
            service_workers="block",accept_downloads=False,
        )
        self.page=self.context.new_page()
        self.requests=[]
        self.unexpected=[]
        self.js_errors=[]
        self.http_status=200
        self.data=payload()
        self.page.on("pageerror",lambda error:self.js_errors.append(str(error)))
        self.page.route("**/*",self.route)
        self.page.goto(HOST+PAGE,wait_until="load",timeout=13000)
        self.page.add_script_tag(path=str(JQUERY))
        self.page.add_script_tag(path=str(SCRIPT))
        self.page.wait_for_function("typeof refreshDeviceEffective === 'function'",
                                    timeout=10000)

    def tearDown(self):
        self.context.close()

    def route(self,route):
        request=route.request
        path=urlsplit(request.url).path
        if request.url.startswith(HOST) and path==PAGE:
            return route.fulfill(status=200,content_type="text/html",
                                 body=html(),
                                 headers={"Cache-Control":"no-store"})
        if request.url.startswith(HOST) and path==API:
            self.requests.append((request.method,path))
            return route.fulfill(
                status=self.http_status,content_type="application/json",
                body=json.dumps(self.data),
                headers={"Cache-Control":"no-store"})
        if request.url.startswith(HOST) and path=="/favicon.ico":
            return route.fulfill(status=404,body="")
        self.unexpected.append((request.method,request.url))
        return route.abort()

    def click_and_wait(self,needle="comparison complete"):
        self.page.locator("#aott-device-effective-refresh").click()
        self.page.wait_for_function(
            """needle => document.getElementById(
               'aott-device-effective-status').textContent
               .toLowerCase().includes(needle)""",
            arg=needle,timeout=12000)

    def test_manual_only_get_no_mutating_or_background_requests(self):
        self.assertEqual(self.requests,[])
        self.click_and_wait()
        self.assertEqual(self.requests,[("GET",API)])
        self.assertEqual(self.unexpected,[])
        self.assertEqual(self.page.locator(
            "#aott-device-effective-results table tr").count(),12)
        self.assertFalse(self.page.locator(
            "#aott-device-effective-results").evaluate("(el)=>el.hidden"))
        self.assertEqual(self.js_errors,[])

    def test_lower_risk_runtime_consumers_are_distinct_from_sfp_and_ntp_sync(self):
        self.click_and_wait()
        body=self.page.locator("#aott-device-effective-results").inner_text()
        self.assertIn("Running kernel hostname matches saved",body)
        self.assertIn("This authenticated LuCI request language matches saved",body)
        self.assertIn("Active local-time zoneinfo target matches saved",body)
        self.assertIn("Active ntpd peer arguments matches saved",body)
        self.assertIn("clock synchronization is not inferred",body)
        self.assertIn("Virtual EEPROM configured; host presentation unverified",body)
        self.assertIn("Fields with independent running-consumer evidence: 4",body)
        self.assertIn("virtual SFP host presentation are not inferred",body)
        self.assertEqual(self.requests,[("GET",API)])

    def test_untrusted_source_value_escaped(self):
        self.click_and_wait()
        body=self.page.locator("#aott-device-effective-results").inner_text()
        self.assertIn("<img src=x onerror=window.__sfp_injected=true>",body)
        self.assertEqual(self.page.locator(
            "#aott-device-effective-results img").count(),0)
        self.assertIsNone(self.page.evaluate("window.__sfp_injected"))
        self.assertEqual(self.js_errors,[])

    def test_invalid_or_incomplete_response_does_not_leave_old_table(self):
        self.click_and_wait()
        del self.data["data"]["fields"]["sfp_partno"]
        self.page.locator("#aott-device-effective-refresh").click()
        self.page.wait_for_function(
            """() => document.getElementById(
                'aott-device-effective-status').textContent
                .includes('Readback unavailable')""",timeout=12000)
        self.assertTrue(self.page.locator(
            "#aott-device-effective-results").evaluate("(el)=>el.hidden"))
        self.assertEqual(self.page.locator(
            "#aott-device-effective-results table").count(),0)
        self.assertEqual(self.unexpected,[])

    def test_503_failure_never_claims_applied_settings(self):
        self.http_status=503
        self.data={"success":False,"error":"synthetic unavailable backend"}
        self.page.locator("#aott-device-effective-refresh").click()
        self.page.wait_for_function(
            """() => document.getElementById(
                'aott-device-effective-status').textContent
                .includes('Readback unavailable')""",timeout=12000)
        self.assertIn("No settings changed",self.page.locator(
            "#aott-device-effective-status").inner_text())
        self.assertEqual(self.requests,[("GET",API)])
        self.assertEqual(self.js_errors,[])

    def test_untrusted_url_refused(self):
        self.page.locator("#aott-device-effective").evaluate(
            "(el) => el.setAttribute('data-effective-url','https://outside.example/')")
        self.page.locator("#aott-device-effective-refresh").click()
        self.assertIn("invalid",self.page.locator(
            "#aott-device-effective-status").inner_text())
        self.assertEqual(self.requests,[])
        self.assertEqual(self.unexpected,[])


if __name__=="__main__":
    unittest.main()
