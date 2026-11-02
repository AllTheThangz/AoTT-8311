"""Real Chromium tests for the C-011 ISP VLAN manual read-only view.

Renders shipped LuCI section and JS with all network calls intercepted.
All VLAN values are synthetic, no subscriber identity or real ONU access.
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
JS=ROOT/"overlay/www/luci-static/resources/view/8311.js"
JQUERY=Path("/usr/share/javascript/jquery/jquery.min.js")
HOST="http://aott.test"
PAGE="/cgi-bin/luci/admin/8311/config"
API="/cgi-bin/luci/admin/8311/effective_vlan"
FIELDS=("fix_vlans","internet_vlan","services_vlan")

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    sync_playwright=None


def content():
    raw=TEMPLATE.read_text()
    selection=re.search(
        r'<section id="aott-vlan-effective".*?</section>',
        raw,flags=re.S)
    assert selection,"Actual LuCI VLAN section missing"
    fragment=selection.group().replace(
        "<%=esc(url('admin/8311/effective_vlan'))%>",API)
    assert "<%" not in fragment
    return ('<!doctype html><html><head><meta charset="utf-8"></head>'
            '<body>'+fragment+'</body></html>')


def response():
    fields={}
    for name in FIELDS:
        fields[name]={
            "id":name,"saved_value":None,"source_default":None,
            "last_recorded_value":None,
            "saved_to_last_recorded":"unverified",
            "last_recorded_source":"unavailable",
            "observed_effective_value":None,
            "runtime_effect_proven":False,
            "hardware_qualified":False,
        }
    fields["fix_vlans"].update(saved_value="1",source_default="1")
    fields["internet_vlan"].update(
        saved_value="200",source_default="0",
        last_recorded_value="200",
        saved_to_last_recorded="match",
    )
    fields["services_vlan"].update(
        saved_value="36",
        last_recorded_value="35",
        saved_to_last_recorded="mismatch",
    )
    return {"success":True,"data":{
        "schema":1,"group":"isp_vlan","no_device_write":True,
        "no_reboot":True,"no_firmware_commit":True,
        "contains_registration_secret":False,
        "source_only_not_hardware_qualified":True,
        "fields":fields,
        "daemon":{"running":True,"proves_translation_active":False},
        "last_reconciliation":{
            "present":True,"topology_matches_record":True,
            "topology_match_proves_rules_current":False,
            "current_traffic_control_rules_verified":False,
        },
        "kernel_tc":{"read_attempted":False,"full_owned_rules_match":False,
                     "verified_rules_count":0,
                     "strict_expected_count":8,
                     "rules_scope":"builtin_owned_selectors_only",
                     "proves_hardware_offload":False,
                     "proves_subscriber_internet":False,
                     "proves_all_traffic_rules_correct":False},
        "summary":{"saved_fields_valid":3,"recorded_fields":2,
                   "saved_match_recorded":1,"saved_drift_from_recorded":1,
                   "live_tc_rules_verified":0},
        "internet_path_verified":False,
    }}


class VlanBrowserTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        browser=next((shutil.which(v) for v in (
            "google-chrome-stable","google-chrome","chromium","chromium-browser"
        ) if shutil.which(v)),None)
        missing=[]
        if sync_playwright is None:missing.append("Playwright")
        if not browser:missing.append("Chromium")
        if not JQUERY.is_file():missing.append("jQuery")
        if missing:
            if os.getenv("AOTT_REQUIRE_BROWSER")=="1":
                raise AssertionError("Missing browser fixtures: "+",".join(missing))
            raise unittest.SkipTest(",".join(missing))
        cls.runner=sync_playwright().start()
        cls.browser=cls.runner.chromium.launch(
            executable_path=browser,headless=True,
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
            viewport={"width":1040,"height":760},
            service_workers="block",accept_downloads=False)
        self.page=self.context.new_page()
        self.calls=[]
        self.unexpected=[]
        self.errors=[]
        self.data=response()
        self.http_status=200
        self.page.on("pageerror",lambda err:self.errors.append(str(err)))
        self.page.route("**/*",self.route)
        self.page.goto(HOST+PAGE,wait_until="load",timeout=13000)
        self.page.add_script_tag(path=str(JQUERY))
        self.page.add_script_tag(path=str(JS))
        self.page.wait_for_function(
            "typeof refreshVlanEffective === 'function'",timeout=9000)

    def tearDown(self):
        self.context.close()

    def route(self,route):
        req=route.request
        path=urlsplit(req.url).path
        if req.url.startswith(HOST) and path==PAGE:
            return route.fulfill(
                status=200,content_type="text/html",body=content(),
                headers={"Cache-Control":"no-store"})
        if req.url.startswith(HOST) and path==API:
            self.calls.append((req.method,path))
            return route.fulfill(
                status=self.http_status,content_type="application/json",
                body=json.dumps(self.data),
                headers={"Cache-Control":"no-store"})
        if req.url.startswith(HOST) and path=="/favicon.ico":
            return route.fulfill(status=404,body="")
        self.unexpected.append((req.method,req.url))
        return route.abort()

    def click(self,needle="comparison complete"):
        self.page.locator("#aott-vlan-effective-refresh").click()
        self.page.wait_for_function(
            """needle => document.getElementById('aott-vlan-effective-status')
                .textContent.toLowerCase().includes(needle)""",
            arg=needle,timeout=12000)

    def test_manual_authenticated_get_and_no_background_activity(self):
        self.assertEqual(self.calls,[])
        self.click()
        self.assertEqual(self.calls,[("GET",API)])
        self.assertEqual(self.unexpected,[])
        self.assertEqual(
            self.page.locator("#aott-vlan-effective-results table tr").count(),4)
        self.assertFalse(self.page.locator(
            "#aott-vlan-effective-results").evaluate("(el)=>el.hidden"))
        self.assertEqual(self.errors,[])

    def test_reconciled_hash_does_not_prove_live_tc_or_internet(self):
        self.click()
        body=self.page.locator("#aott-vlan-effective-results").inner_text()
        self.assertIn("Live traffic-control rules not independently verified",body)
        self.assertIn("last recorded topology",body)
        self.assertIn("An unchanged topology or daemon alone proves nothing",body)
        self.assertIn("Saved override differs from historical record",body)
        self.assertNotIn("Internet verified",body)

    def test_untrusted_configuration_is_escaped_plain_text(self):
        self.data["data"]["fields"]["services_vlan"]["last_recorded_value"]=(
            "<img src=x onerror=window.__vlan_xss=true>")
        self.click()
        text=self.page.locator("#aott-vlan-effective-results").inner_text()
        self.assertIn("<img src=x onerror=window.__vlan_xss=true>",text)
        self.assertEqual(self.page.locator(
            "#aott-vlan-effective-results img").count(),0)
        self.assertIsNone(self.page.evaluate("window.__vlan_xss"))
        self.assertEqual(self.errors,[])

    def test_no_receipt_and_unknown_daemon_are_not_false_success(self):
        report=self.data["data"]
        report["last_reconciliation"]={
            "present":False,
            "topology_match_proves_rules_current":False,
            "current_traffic_control_rules_verified":False
        }
        report["daemon"]={"proves_translation_active":False}
        for name in FIELDS:
            report["fields"][name].pop("last_recorded_value",None)
        self.click()
        body=self.page.locator("#aott-vlan-effective-results").inner_text()
        self.assertIn("Last validated native receipt: absent or unverified",body)
        self.assertIn("VLAN daemon: unknown",body)
        self.assertIn("Topology comparison: not verified",body)

    def test_incomplete_response_and_http_failure_fail_closed(self):
        self.click()
        self.data["data"]["fields"].pop("internet_vlan")
        self.page.locator("#aott-vlan-effective-refresh").click()
        self.page.wait_for_function(
            """() => document.getElementById('aott-vlan-effective-status')
                .textContent.includes('Readback unavailable')""",
            timeout=12000)
        self.assertTrue(self.page.locator(
            "#aott-vlan-effective-results").evaluate("(el)=>el.hidden"))
        self.assertEqual(
            self.page.locator("#aott-vlan-effective-results table").count(),0)
        self.http_status=503
        self.data={"success":False,"error":"Synthetic unavailable source"}
        self.page.locator("#aott-vlan-effective-refresh").click()
        self.page.wait_for_function(
            """() => document.getElementById('aott-vlan-effective-status')
                .textContent.includes('Readback unavailable')""",
            timeout=12000)
        self.assertIn("No settings changed",self.page.locator(
            "#aott-vlan-effective-status").inner_text())
        self.assertEqual(self.unexpected,[])

    def test_positive_scoped_tc_readback_does_not_claim_isp_health(self):
        report=self.data["data"]
        report["kernel_tc"].update(
            read_attempted=True,full_owned_rules_match=True,
            verified_rules_count=8,
        )
        report["last_reconciliation"]["current_traffic_control_rules_verified"]=True
        for key,value in (("internet_vlan","200"),("services_vlan","35")):
            report["fields"][key].update(
                runtime_effect_proven=True,
                observed_effective_value=value,
                observed_source="independent_kernel_tc_flower_readback",
            )
        self.click()
        body=self.page.locator("#aott-vlan-effective-results").inner_text()
        self.assertIn("Installed built-in kernel TC selectors match",body)
        self.assertIn("selected built-in kernel rules independently matched",body)
        self.assertIn("Even a selected-rule match does not prove all rules",body)
        self.assertIn("Internet connectivity",body)
        self.assertEqual(self.calls,[("GET",API)])

    def test_inconsistent_claim_of_live_tc_proof_fails_closed(self):
        self.data["data"]["fields"]["internet_vlan"].update(
            runtime_effect_proven=True,
            observed_effective_value="200",
            observed_source="independent_kernel_tc_flower_readback",
        )
        # No complete native TC proof in the envelope.
        self.page.locator("#aott-vlan-effective-refresh").click()
        self.page.wait_for_function(
            """() => document.getElementById('aott-vlan-effective-status')
                .textContent.includes('Readback unavailable')""",
            timeout=12000)
        self.assertTrue(self.page.locator(
            "#aott-vlan-effective-results").evaluate("(el)=>el.hidden"))
        self.assertEqual(self.calls,[("GET",API)])
        self.assertEqual(self.unexpected,[])

    def test_verifier_attempt_failure_remains_unverified(self):
        self.data["data"]["kernel_tc"].update(read_attempted=True,
                  full_owned_rules_match=False,verified_rules_count=0)
        self.click()
        body=self.page.locator("#aott-vlan-effective-results").inner_text()
        self.assertIn("attempted but no complete match",body)
        self.assertNotIn("Installed built-in kernel TC selectors match",body)
        self.assertEqual(self.errors,[])

    def test_external_url_rejected_before_any_request(self):
        self.page.locator("#aott-vlan-effective").evaluate(
            "(el)=>el.setAttribute('data-effective-url','https://elsewhere.example')")
        self.page.locator("#aott-vlan-effective-refresh").click()
        self.assertIn("invalid",self.page.locator(
            "#aott-vlan-effective-status").inner_text())
        self.assertEqual(self.calls,[])
        self.assertEqual(self.unexpected,[])


if __name__=="__main__":
    unittest.main()
