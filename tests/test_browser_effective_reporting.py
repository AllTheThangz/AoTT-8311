"""Real Chromium C-011 redacted OMCI metadata readback.

Uses the actual shipped LuCI configuration template section and full
8311.js. All HTTP responses are synthetic and locally intercepted.
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
ENDPOINT="/cgi-bin/luci/admin/8311/effective_reporting"
FIELDS=("equipment_id","hw_ver","cp_hw_ver_sync","sw_verA","sw_verB",
        "fw_match_b64","fw_match_num","override_active","override_commit",
        "pon_slot")

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    sync_playwright=None


def page_html():
    source=VIEW.read_text()
    match=re.search(r'<section id="aott-reporting-effective".*?</section>',
                    source,flags=re.S)
    assert match,"Actual reporting section absent"
    section=match.group().replace(
        "<%=esc(url('admin/8311/effective_reporting'))%>",ENDPOINT)
    assert "<%" not in section
    return ("<!doctype html><html><head><meta charset='utf-8'>"
            "</head><body>"+section+"</body></html>")


def response():
    fields={}
    for item in FIELDS:
        fields[item]={
            "id":item,
            "source_scope":"aott_prefixed_boot_environment",
            "source_presence":True,
            "source_format":"valid_source_format",
            "reported_image_to_boot_label":"unavailable",
            "reported_bank_not_actual_boot_selector":True,
            "content_redacted":True,
            "raw_value_exported":False,
            "runtime_effect_proven":False,
            "omci_mib_effect_proven":False,
            "olt_received_reported_value_proven":False,
            "actually_flashes_or_commits_firmware":False,
            "survives_reboot_proven":False,
            "hardware_qualified":False,
        }
    fields["sw_verA"]["reported_image_to_boot_label"]="labels_match"
    fields["sw_verB"]["reported_image_to_boot_label"]="labels_differ"
    return {
        "success":True,
        "data":{
            "schema":1,
            "group":"omci_reporting_noncredential",
            "source":"boot_environment_presence_and_format_only",
            "fields":fields,
            "no_device_write":True,
            "no_reboot":True,
            "no_firmware_commit":True,
            "no_mib_edit":True,
            "no_registration_secret_read":True,
            "no_subscriber_identity_exported":True,
            "no_raw_environment_value_exported":True,
            "no_olt_effect_proof":True,
            "actual_boot_bank_verified":False,
            "proves_subscriber_internet":False,
            "source_only_not_hardware_qualified":True,
            "summary":{
                "source_fields":10,"source_present":10,
                "source_format_valid":10,"source_format_invalid":0,
                "source_unavailable":0,
                "image_labels_compared":2,"image_labels_matching":1,
                "reporting_runtime_effects_verified":0,
                "hardware_qualified":0,
            }
        },
    }


class ReportingBrowserTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        browser=next((shutil.which(s) for s in
                      ("google-chrome-stable","google-chrome",
                       "chromium","chromium-browser") if shutil.which(s)),None)
        missing=[]
        if sync_playwright is None:missing.append("Playwright")
        if not browser:missing.append("Chromium")
        if not JQUERY.is_file():missing.append("jQuery")
        if missing:
            if os.environ.get("AOTT_REQUIRE_BROWSER")=="1":
                raise AssertionError("Required Chromium missing: "+",".join(missing))
            raise unittest.SkipTest(",".join(missing))
        cls.runner=sync_playwright().start()
        cls.browser=cls.runner.chromium.launch(
            headless=True,executable_path=browser,
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
            viewport={"width":1050,"height":820},
            service_workers="block",accept_downloads=False)
        self.page=self.context.new_page()
        self.calls=[]
        self.unexpected=[]
        self.errors=[]
        self.code=200
        self.payload=response()
        self.page.on("pageerror",lambda e:self.errors.append(str(e)))
        self.page.route("**/*",self.route)
        self.page.goto(HOST+PAGE,wait_until="load",timeout=13000)
        self.page.add_script_tag(path=str(JQUERY))
        self.page.add_script_tag(path=str(JS))
        self.page.wait_for_function(
            "typeof refreshReportingEffective === 'function'",timeout=8000)

    def tearDown(self):
        self.context.close()

    def route(self,route):
        req=route.request
        path=urlsplit(req.url).path
        if req.url.startswith(HOST) and path==PAGE:
            return route.fulfill(status=200,content_type="text/html",
                body=page_html(),headers={"Cache-Control":"no-store"})
        if req.url.startswith(HOST) and path==ENDPOINT:
            self.calls.append((req.method,path))
            return route.fulfill(status=self.code,
                content_type="application/json",body=json.dumps(self.payload),
                headers={"Cache-Control":"no-store"})
        if req.url.startswith(HOST) and path=="/favicon.ico":
            return route.fulfill(status=404,body="")
        self.unexpected.append((req.method,req.url))
        route.abort()

    def check(self):
        self.page.locator("#aott-reporting-effective-refresh").click()
        self.page.wait_for_function(
            """() => document.getElementById('aott-reporting-effective-status')
                 .textContent.includes('check complete')""",timeout=12000)

    def failed(self):
        self.page.locator("#aott-reporting-effective-refresh").click()
        self.page.wait_for_function(
            """() => document.getElementById('aott-reporting-effective-status')
                 .textContent.includes('Readback unavailable')""",
            timeout=12000)

    def test_manual_get_only_no_background_requests(self):
        self.assertEqual(self.calls,[])
        self.check()
        self.assertEqual(self.calls,[("GET",ENDPOINT)])
        self.assertEqual(self.unexpected,[])
        self.assertEqual(self.errors,[])
        self.assertEqual(self.page.locator(
            "#aott-reporting-effective-results table tr").count(),11)
        self.assertFalse(self.page.locator(
            "#aott-reporting-effective-results").evaluate("(x)=>x.hidden"))

    def test_no_identity_contents_or_olt_firmware_effect_claim(self):
        self.check()
        content=self.page.locator(
            "#aott-reporting-effective-results").inner_text()
        self.assertIn("content redacted",content)
        self.assertIn("Reported label matches boot image label",content)
        self.assertIn("Reported label differs from boot image label",content)
        self.assertIn("no boot bank changed",content.lower())
        self.assertIn("OLT effect unverified",content)
        self.assertIn("never proves",content.lower())
        self.assertNotIn("PON associated",content)

    def test_unsafe_content_never_enters_markup_or_table(self):
        self.payload["data"]["fields"]["equipment_id"]["raw_value"]=(
            "<img src=x onerror=window.__reporting_xss=true>")
        self.payload["data"]["fields"]["sw_verA"]["saved_value"]=(
            "SubscriberSecret_DO_NOT_RENDER")
        self.check()
        panel=self.page.locator("#aott-reporting-effective-results")
        self.assertNotIn("SubscriberSecret",panel.inner_text())
        self.assertNotIn("<img",panel.inner_text())
        self.assertEqual(panel.locator("img").count(),0)
        self.assertIsNone(self.page.evaluate("window.__reporting_xss"))
        self.assertEqual(self.errors,[])

    def test_invalid_format_is_shown_not_interpreted_as_applied(self):
        self.payload["data"]["fields"]["pon_slot"]["source_format"]=(
            "invalid_source_format")
        self.check()
        content=self.page.locator(
            "#aott-reporting-effective-results").inner_text()
        self.assertIn("Present, unsupported format",content)
        self.assertIn("OLT effect unverified",content)

    def test_claim_of_hardware_effect_fails_closed(self):
        self.payload["data"]["fields"]["sw_verA"]["hardware_qualified"]=True
        self.failed()
        self.assertTrue(self.page.locator(
            "#aott-reporting-effective-results").evaluate("(x)=>x.hidden"))
        self.assertEqual(self.page.locator(
            "#aott-reporting-effective-results table").count(),0)

    def test_malformed_or_missing_row_and_http503_fail_closed(self):
        del self.payload["data"]["fields"]["override_active"]
        self.failed()
        self.assertEqual(self.calls,[("GET",ENDPOINT)])
        self.code=503
        self.payload={"success":False,"error":"Synthetic failure"}
        self.failed()
        self.assertIn("No settings changed",
                      self.page.locator(
                        "#aott-reporting-effective-status").inner_text())
        self.assertEqual(self.unexpected,[])
        self.assertEqual(self.errors,[])

    def test_external_endpoint_rejected_without_contact(self):
        self.page.locator("#aott-reporting-effective").evaluate(
            "(x)=>x.setAttribute('data-effective-url','https://external.example/')")
        self.page.locator("#aott-reporting-effective-refresh").click()
        self.assertIn("invalid",self.page.locator(
            "#aott-reporting-effective-status").inner_text())
        self.assertEqual(self.calls,[])
        self.assertEqual(self.unexpected,[])


if __name__=="__main__":
    unittest.main()
