"""V3r4 real Chromium verification of the unified redacted Configuration view.

All seven API responses are synthetic. No real ONU, router or internet
service is accessed, and no configuration/firmware requests are made.
"""
import copy
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
OVERVIEW=ROOT/"overlay/www/luci-static/resources/view/8311-verification-overview.js"
VENDOR=Path(os.getenv("AOTT_VENDOR_ROOTFS","/missing-vendor-rootfs"))
JQUERY=VENDOR/"www/luci-static/resources/jquery-3.7.1.min.js"
HOST="http://aott.test"
PAGE="/cgi-bin/luci/admin/8311/config"
PREFIX="/cgi-bin/luci/admin/8311/effective_"
IDS={
    "management":("lct_vlan","ipaddr","netmask","gateway","dns_server",
                  "pingd","ping_ip","lct_mac","reverse_arp","https_redirect"),
    "device":("hostname","lang","timezone","ntp_servers","sfp_vendor",
              "sfp_oui","sfp_partno","sfp_rev","sfp_serial","sfp_date","sfp_vendordata"),
    "pon":("pon_mode","omcc_version","iop_mask","mib_file"),
    "identity":("gpon_sn","vendor_id","reg_id_hex","loid","lpwd",
                "iphost_mac","iphost_hostname","iphost_domain","root_pwhash"),
    "reporting":("equipment_id","hw_ver","cp_hw_ver_sync","sw_verA","sw_verB",
                 "fw_match_b64","fw_match_num","override_active","override_commit","pon_slot"),
    "vlan":("fix_vlans","internet_vlan","services_vlan"),
    "hardware":("bootdelay","uart_select","console_en","dying_gasp_en",
                "rx_los","ethtool_speed","failsafe_delay","persist_root"),
}

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    sync_playwright=None


def page_html(unsafe=None):
    source=VIEW.read_text()
    assert "8311-verification-overview.js?v=aott-8311-v3-r4" in source
    groups=["aott-verification-overview"]+[
        "aott-"+name+"-effective" for name in IDS]
    html=[]
    for name in groups:
        match=re.search(r'<section id="'+re.escape(name)+r'".*?</section>',
                        source,flags=re.S)
        assert match,"Missing shipped section: "+name
        fragment=match.group()
        for group in IDS:
            fragment=fragment.replace(
                "<%=esc(url('admin/8311/effective_"+group+"'))%>",
                PREFIX+group)
        assert "<%" not in fragment,fragment[:200]
        if unsafe:
            key,evil=unsafe
            if name=="aott-"+key+"-effective":
                fragment=fragment.replace(PREFIX+key,evil)
        html.append(fragment)
    return ('<!doctype html><html><head><meta charset="utf-8"></head>'
            '<body><div id="config-message"></div>'+
            "".join(html)+'</body></html>')


def synthetic(group):
    fields={}
    for id in IDS[group]:
        row=dict(id=id,runtime_effect_proven=False,hardware_qualified=False,
                 saved_to_configured="unverified",
                 saved_to_observed="unverified",
                 configured_value=None,
                 saved_value="PRIVATE_SOURCE_VALUE_DO_NOT_DISPLAY")
        if group=="identity":
            row.update(source_status="valid_saved_override",
                       content_redacted=True,raw_value_exported=False,
                       value_hash_exported=False,
                       authentication_success_proven=False)
        if group=="reporting":
            row.update(source_format="valid_source_format",
                       content_redacted=True,raw_value_exported=False,
                       olt_received_reported_value_proven=False)
        if group=="vlan":
            row["saved_to_last_recorded"]="unverified"
        fields[id]=row
    d=dict(schema=1,fields=fields,summary={},no_device_write=True,
           source_only_not_hardware_qualified=True)
    if group=="management":
        d["no_hidden_hardware_qualification"]=True
    if group in ("pon","vlan"):
        d["contains_registration_secret"]=False
    if group=="hardware":
        d["contains_credential_material"]=False
    if group=="identity":
        d.update(no_identity_exported=True,
                 no_credential_hash_exported=True,
                 no_raw_environment_exported=True,
                 no_olt_or_login_authentication_claim=True)
    if group=="reporting":
        d.update(no_registration_secret_read=True,
                 no_subscriber_identity_exported=True,
                 no_raw_environment_value_exported=True,
                 no_olt_effect_proof=True)
    return dict(success=True,data=d)


class ConfigVerificationOverviewBrowserTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        binary=next((shutil.which(n) for n in
                     ("google-chrome-stable","google-chrome","chromium",
                      "chromium-browser") if shutil.which(n)),None)
        missing=[]
        if not binary: missing.append("Chromium")
        if sync_playwright is None: missing.append("Playwright")
        if not JQUERY.is_file(): missing.append("vendor jQuery")
        if missing:
            msg="Missing browser dependencies: "+", ".join(missing)
            if os.getenv("AOTT_REQUIRE_BROWSER")=="1": raise AssertionError(msg)
            raise unittest.SkipTest(msg)
        cls.runner=sync_playwright().start()
        cls.browser=cls.runner.chromium.launch(
            executable_path=binary,headless=True,args=[
                "--no-sandbox","--disable-dev-shm-usage",
                "--disable-background-networking","--disable-extensions",
                "--no-first-run","--disable-component-update"])

    @classmethod
    def tearDownClass(cls):
        if getattr(cls,"browser",None): cls.browser.close()
        if getattr(cls,"runner",None): cls.runner.stop()

    def setUp(self):
        self.context=self.browser.new_context(
            service_workers="block",accept_downloads=False)
        self.page=self.context.new_page()
        self.calls=[]
        self.unexpected=[]
        self.errors=[]
        self.status_codes={group:200 for group in IDS}
        self.records={group:synthetic(group) for group in IDS}
        self.unsafe=None
        self.page.on("pageerror",lambda error:self.errors.append(str(error)))
        self.page.route("**/*",self.route)

    def tearDown(self):
        self.context.close()

    def route(self,route):
        req=route.request
        url=urlsplit(req.url)
        if req.url.startswith(HOST) and url.path==PAGE:
            return route.fulfill(
                status=200,content_type="text/html",
                body=page_html(unsafe=self.unsafe))
        self.calls.append((req.method,req.url))
        if req.url.startswith(HOST) and url.path.startswith(PREFIX):
            group=url.path[len(PREFIX):]
            if group in IDS:
                return route.fulfill(
                    status=self.status_codes[group],
                    content_type="application/json",
                    body=json.dumps(self.records[group]),
                    headers={"Cache-Control":"no-store"})
        if req.url.startswith(HOST) and url.path=="/favicon.ico":
            return route.fulfill(status=404,body="")
        self.unexpected.append(req.url)
        return route.abort()

    def load(self):
        self.page.goto(HOST+PAGE,wait_until="load")
        self.page.add_script_tag(path=str(JQUERY))
        self.page.add_script_tag(path=str(JS))
        self.page.add_script_tag(path=str(OVERVIEW))
        self.page.wait_for_function(
            "() => !!document.getElementById('aott-verification-refresh')")

    def click(self,needle):
        self.page.locator("#aott-verification-refresh").click()
        self.page.wait_for_function(
            "(needle) => document.getElementById('aott-verification-status')"
            ".textContent.includes(needle)",arg=needle,timeout=20000)
        self.assertEqual(self.errors,[])
        self.assertFalse(self.page.locator("#aott-verification-refresh").is_disabled())

    def test_complete_55_field_readback_is_manual_only_and_redacted(self):
        self.load()
        self.assertEqual(self.calls,[],"No automatically scheduled probing")
        self.click("All seven")
        self.assertEqual(len(self.calls),7)
        self.assertTrue(all(m=="GET" for m,_ in self.calls))
        self.assertEqual(set(urlsplit(x).path for _,x in self.calls),
                         {PREFIX+g for g in IDS})
        self.page.locator("#aott-verification-results details").first.evaluate(
            "(node) => {node.open=true;}")
        self.page.locator("#aott-verification-results details").nth(3).evaluate(
            "(node) => {node.open=true;}")
        txt=self.page.locator("#aott-verification-results").inner_text()
        self.assertIn("7/7 checks completed; 55/55 source fields read",txt)
        self.assertIn("0 runtime observations",txt)
        self.assertIn("Not independently observed",txt)
        self.assertIn("Redacted source only",txt)
        self.assertNotIn("PRIVATE_SOURCE_VALUE_DO_NOT_DISPLAY",txt)
        self.assertNotIn("<img",txt)
        self.assertEqual(self.page.locator(
            "#aott-verification-results details").count(),7)
        self.assertEqual(self.unexpected,[])

    def test_observed_runtime_vs_saved_drift_is_distinct(self):
        self.records["management"]["data"]["fields"]["ipaddr"].update(
            runtime_effect_proven=True,saved_to_observed="match",
            saved_to_configured="match")
        self.records["device"]["data"]["fields"]["hostname"].update(
            runtime_effect_proven=True,saved_to_observed="mismatch")
        self.records["vlan"]["data"]["fields"]["services_vlan"].update(
            saved_to_last_recorded="mismatch")
        self.load()
        self.click("All seven")
        self.page.locator("#aott-verification-results details").nth(1).evaluate(
            "(node) => {node.open=true;}")
        self.page.locator("#aott-verification-results details").nth(5).evaluate(
            "(node) => {node.open=true;}")
        txt=self.page.locator("#aott-verification-results").inner_text()
        self.assertIn("2 runtime observations",txt)
        self.assertIn("1 saved/configured differences",txt)
        self.assertIn("Historical reconciliation differs",txt)
        self.assertIn("Observed; differs from saved",txt)

    def test_partial_probe_failure_does_not_count_unknown_as_zero(self):
        self.status_codes["pon"]=503
        self.records["identity"]["data"]["fields"]["gpon_sn"]["hardware_qualified"]=True
        self.load()
        self.click("Partial readback")
        txt=self.page.locator("#aott-verification-results").inner_text()
        self.assertIn("5/7 checks completed; 42/55 source fields read",txt)
        self.assertIn("Not verified",txt)
        self.assertIn("Unknown",txt)
        self.assertNotIn("PRIVATE_SOURCE_VALUE_DO_NOT_DISPLAY",txt)
        self.assertEqual(len(self.calls),7)

    def test_endpoint_rewrite_is_refused_before_request(self):
        self.unsafe=("vlan","//foreign.example/steal")
        self.load()
        self.click("Partial readback")
        self.assertEqual(len(self.calls),6)
        self.assertNotIn(PREFIX+"vlan",[urlsplit(x).path for _,x in self.calls])
        self.assertEqual(self.unexpected,[])

    def test_identity_claim_and_untrusted_text_are_not_rendered(self):
        self.records["identity"]["data"]["fields"]["gpon_sn"].update(
            source_status="unknown-format",
            saved_value="<img src=x onerror=window.__aott_xss=true>")
        self.records["reporting"]["data"]["fields"]["hw_ver"].update(
            source_format="unavailable",
            saved_value="VERYPRIVATEVERSIONDO_NOT_COPY")
        self.load()
        self.click("Partial readback")
        txt=self.page.locator("#aott-verification-results").inner_text()
        self.assertNotIn("VERYPRIVATEVERSIONDO_NOT_COPY",txt)
        self.assertNotIn("unknown-format",txt)
        self.assertNotIn("<img",txt)
        self.assertEqual(self.page.evaluate("window.__aott_xss===true"),False)
        self.assertEqual(len(self.calls),7)


if __name__=="__main__":
    unittest.main()
