from pathlib import Path
import json, os, shutil, unittest
from urllib.parse import parse_qs, urlsplit

ROOT=Path(__file__).resolve().parents[1]
JS=ROOT/"overlay/www/luci-static/resources/view/8311.js"
VENDOR=Path(os.getenv("AOTT_VENDOR_ROOTFS",
    "/var/tmp/aott-v3-az-build-20261108/build-A-final/rootfs"))
JQ=VENDOR/"www/luci-static/resources/jquery-3.7.1.min.js"
HOST="https://192.0.2.1"

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    sync_playwright=None

def browser_binary():
    return next((shutil.which(n) for n in (
        "google-chrome-stable","google-chrome","chromium","chromium-browser"
    ) if shutil.which(n)),None)

def profile(path):
    base={
        "schema":1,"path":path,"filename":path.rsplit("/",1)[-1],
        "variant_hint":"generic","profile_kind":"single_uni",
        "conditional_records":0,"hardware_qualified":False,
        "olt_compatibility_proven":False,"contains_subscriber_values":False,
        "notes":[],"defaults":{"vendor_id":"INTC","hw_ver":"00000000000000",
            "equipment_id":"00000000000000000000","pon_slot":"1"},
        "applicability":{"vendor_id":True,"hw_ver":True,
            "cp_hw_ver_sync":True,"equipment_id":True,
            "software_reporting":True,"iphost_identity":True,"pon_slot":True},
        "topology":{"physical_uni_count":1,"physical_uni_numbers":[1],
            "slot_candidates":[1],"slot_editable":True,
            "slot_reason":"single_uni_slot_mapping",
            "ethernet_uni_me11_count":1,"iphost_me134_count":1,
            "veip_me329_count":0,"tcont_me262_count":16,
            "priority_queue_me277_count":136,
            "traffic_scheduler_me278_count":16,
            "vendor_extension_me443_count":4,"me53_count":0},
    }
    if path.endswith("prx300_2U.ini"):
        base["profile_kind"]="multi_uni"
        base["topology"].update(physical_uni_count=2,physical_uni_numbers=[1,2],
            slot_editable=False,slot_reason="multiple_physical_unis",
            ethernet_uni_me11_count=2,priority_queue_me277_count=144)
        base["applicability"]["pon_slot"]=False
        base["defaults"]["pon_slot"]=None
        base["notes"]=["Multiple physical UNI relationships detected; a single global UNI-slot override is unsafe and is disabled."]
    elif path.endswith("prx300_1V.ini"):
        base["profile_kind"]="single_uni_plus_veip"
        base["topology"].update(iphost_me134_count=0,veip_me329_count=1)
        base["applicability"]["iphost_identity"]=False
        base["notes"]=["IP Host Config Data ME 134 is absent; IP-host identity overrides are not applicable to this profile."]
    elif path.endswith("prx300_1V_32tcont.ini"):
        base["variant_hint"]="32tcont";base["profile_kind"]="veip"
        base["topology"].update(physical_uni_count=0,physical_uni_numbers=[],
            slot_candidates=[],slot_editable=False,
            slot_reason="veip_profile_no_physical_uni_slot_mapping",
            iphost_me134_count=1,veip_me329_count=1,tcont_me262_count=32,
            priority_queue_me277_count=264,traffic_scheduler_me278_count=32)
        base["applicability"]["pon_slot"]=False
        base["defaults"]["pon_slot"]=None
    return base

def field(name,value="",kind="input"):
    if kind=="select":
        html=f'<select name="{name}"><option value="0">Disabled</option><option value="1" selected>Enabled</option></select>'
    else:
        html=f'<input name="{name}" value="{value}">'
    return f'<div class="cbi-value"><div class="cbi-value-field">{html}<div class="cbi-value-description"></div></div></div>'

def page_html():
    options=[
        "/etc/mibs/prx300_1U.ini",
        "/etc/mibs/prx300_2U.ini",
        "/etc/mibs/prx300_1V.ini",
        "/etc/mibs/prx300_1V_32tcont.ini",
    ]
    select='<select name="mib_file">'+''.join(
        f'<option value="{p}"{" selected" if p.endswith("prx300_1U.ini") else ""}>{p}</option>'
        for p in options)+'</select>'
    return """<!doctype html><html><body>
<div id="config-message"></div>
<form id="8311-config" action="/admin/8311/save"
 data-mib-profile-url="/admin/8311/mib_profile">
<input type="hidden" name="token" value="csrf-fixture">
<div class="cbi-value"><div class="cbi-value-field">%s
<section id="aott-mib-profile-summary"><div id="aott-mib-profile-status"></div>
<div id="aott-mib-profile-details" hidden></div></section></div></div>
%s%s%s%s%s%s%s%s%s
</form>
<div id="config-review"></div><button id="config-confirm"></button><button id="save-btn"></button>
</body></html>""" % (
        select,
        field("pon_slot","1"),
        field("iphost_mac",":".join(["AA","BB","CC","DD","EE","FF"])),
        field("iphost_hostname","onu"),
        field("iphost_domain","example"),
        field("cp_hw_ver_sync","",kind="select"),
        field("vendor_id",""),
        field("hw_ver",""),
        field("equipment_id",""),
        field("sw_verA",""),
    )

class BrowserMibProfileTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.binary=browser_binary()
        missing=[]
        if not cls.binary: missing.append("Chromium")
        if sync_playwright is None: missing.append("Playwright")
        if not JQ.is_file(): missing.append("vendor jQuery")
        if missing:
            msg="Missing browser dependencies: "+", ".join(missing)
            if os.getenv("AOTT_REQUIRE_BROWSER")=="1": raise AssertionError(msg)
            raise unittest.SkipTest(msg)
        cls.runner=sync_playwright().start()
        cls.browser=cls.runner.chromium.launch(
            executable_path=cls.binary,headless=True,
            args=["--no-sandbox","--disable-dev-shm-usage",
                  "--disable-background-networking","--disable-extensions",
                  "--no-first-run","--disable-component-update"])

    @classmethod
    def tearDownClass(cls):
        if getattr(cls,"browser",None): cls.browser.close()
        if getattr(cls,"runner",None): cls.runner.stop()

    def make_page(self):
        context=self.browser.new_context(ignore_https_errors=True)
        page=context.new_page()
        requests=[]
        def handler(route):
            u=urlsplit(route.request.url)
            if route.request.resource_type=="document" and u.path=="/config":
                return route.fulfill(status=200,content_type="text/html",body=page_html())
            if route.request.method=="POST" and u.path=="/admin/8311/mib_profile":
                body=parse_qs(route.request.post_data or "",keep_blank_values=True)
                requests.append(body)
                selected=body.get("mib_file",[""])[0]
                return route.fulfill(status=200,content_type="application/json",
                    body=json.dumps({"success":True,"profile":profile(selected)}))
            return route.abort()
        page.route("**/*",handler)
        page.goto(HOST+"/config",wait_until="load")
        page.add_script_tag(path=str(JQ))
        page.add_script_tag(path=str(JS))
        return context,page,requests

    def test_real_time_profile_summary_and_slot_prompt(self):
        context,page,requests=self.make_page()
        try:
            page.wait_for_function(
                "() => document.getElementById('aott-mib-profile-status').textContent.includes('prx300_1U.ini')")
            details=page.locator("#aott-mib-profile-details").inner_text()
            self.assertIn("T-CONT ME 262 records",details)
            self.assertIn("16",details)
            self.assertFalse(page.locator('[name="pon_slot"]').is_editable() is False)

            page.locator('[name="mib_file"]').select_option("/etc/mibs/prx300_2U.ini")
            page.wait_for_function(
                "() => document.getElementById('aott-mib-profile-status').textContent.includes('prx300_2U.ini')")
            self.assertIn("2 (1, 2)",page.locator("#aott-mib-profile-details").inner_text())
            clear=page.get_by_role("button",name="Clear incompatible slot override")
            self.assertTrue(clear.is_visible())
            clear.click()
            self.assertEqual(page.locator('[name="pon_slot"]').input_value(),"")
            self.assertTrue(page.locator('[name="pon_slot"]').evaluate("e => e.readOnly"))
            self.assertGreaterEqual(len(requests),2)
        finally:
            context.close()

    def test_iphost_fields_follow_me134_and_32tcont_is_visible(self):
        context,page,_=self.make_page()
        try:
            page.wait_for_function(
                "() => document.getElementById('aott-mib-profile-status').textContent.includes('prx300_1U.ini')")
            page.locator('[name="mib_file"]').select_option("/etc/mibs/prx300_1V.ini")
            page.wait_for_function(
                "() => document.getElementById('aott-mib-profile-status').textContent.includes('prx300_1V.ini')")
            for name in ("iphost_mac","iphost_hostname","iphost_domain"):
                self.assertTrue(page.locator(f'[name="{name}"]').evaluate("e => e.readOnly"))
            self.assertIn("not contain IP Host Config Data ME 134",
                page.locator('[data-mib-rule-for="iphost_hostname"]').inner_text())

            page.locator('[name="mib_file"]').select_option("/etc/mibs/prx300_1V_32tcont.ini")
            page.wait_for_function(
                "() => document.getElementById('aott-mib-profile-status').textContent.includes('prx300_1V_32tcont.ini')")
            text=page.locator("#aott-mib-profile-details").inner_text()
            self.assertIn("32",text)
            self.assertIn("VEIP ME 329 records",text)
        finally:
            context.close()

if __name__=="__main__":
    unittest.main()
