"""Real Chromium coverage for guarded V3 PON/OMCI configuration routing."""
from pathlib import Path
import json, os, shutil, unittest
from urllib.parse import parse_qs, urlsplit

ROOT=Path(__file__).resolve().parents[1]
JS=ROOT/"overlay/www/luci-static/resources/view/8311.js"
VENDOR=Path(os.getenv("AOTT_VENDOR_ROOTFS",
    "/var/tmp/aott-v3-rc3-release-20261107/build-A-final/rootfs"))
JQ=VENDOR/"www/luci-static/resources/jquery-3.7.1.min.js"
HOST="https://192.0.2.1"
SECRET="".join(("A1B2","C3D4","E5F6","0718","293A","4B5C"))

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
 data-boot-apply-url="/admin/8311/boot_config_apply"
 data-boot-confirm-url="/admin/8311/boot_config_confirm"
 data-reboot-url="/admin/system/reboot"
 data-pon-apply-url="/admin/8311/pon_config_apply"
 data-pon-status-url="/admin/8311/pon_config_status"
 data-pon-confirm-url="/admin/8311/pon_config_confirm"
 method="post">
<input type="hidden" name="token" value="csrf-fixture">
<input type="hidden" name="complete" value="8311-v1">
<input type="hidden" name="revision" value="{"a"*64}">
<input type="hidden" name="mode" value="preview">
<input name="gpon_sn" value="TEST00000001">
<input name="reg_id_hex" value="{SECRET}">
<input name="hostname" value="fixture-host">
<button id="save-btn" type="submit">Review changes</button>
</form>
<div id="config-review" style="display:none">
  <div id="config-diff"></div>
  <button id="config-confirm" type="button" disabled>Confirm</button>
</div>
</body></html>"""

class BrowserPonConfigRoutingTests(unittest.TestCase):
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

    def setUp(self):
        self.context=self.browser.new_context(
            viewport={"width":1100,"height":800},
            service_workers="block",ignore_https_errors=True)
        self.page=self.context.new_page()
        self.requests=[]
        self.status_reads=0
        self.confirmed=False
        self.page.route("**/*",self.route)
        self.page.goto(HOST+"/config",wait_until="load")
        self.page.add_script_tag(path=str(JQ))
        self.page.add_script_tag(path=str(JS))
        self.page.wait_for_function("typeof saveConfig === 'function'")

    def tearDown(self):
        self.context.close()

    def route(self,route):
        u=urlsplit(route.request.url)
        if route.request.resource_type=="document" and u.path=="/config":
            return route.fulfill(status=200,content_type="text/html",body=html())
        if route.request.method=="POST":
            body=parse_qs(route.request.post_data or "",keep_blank_values=True)
            self.requests.append((u.path,body))
            if u.path=="/admin/8311/save":
                return route.fulfill(status=200,content_type="application/json",
                    body=json.dumps({
                        "success":True,"revision":"a"*64,"route":"pon","routes":["pon"],
                        "diff":[
                            {"id":"gpon_sn","name":"PON serial","before":"old","after":"[hidden]",
                             "applies":"Guarded PON transaction"},
                            {"id":"reg_id_hex","name":"PLOAM","before":"[hidden]","after":"[hidden]",
                             "applies":"Guarded PON transaction"},
                        ],
                    }))
            if u.path=="/admin/8311/pon_config_apply":
                return route.fulfill(status=202,content_type="application/json",
                    body=json.dumps({
                        "success":True,
                        "job":{"id":"b"*32},
                        "rollback_seconds":180,
                        "verification_seconds":120,
                        "requires_explicit_confirmation":True,
                        "olt_per_field_effect_proven":False,
                    }))
            if u.path=="/admin/8311/pon_config_confirm":
                self.confirmed=True
                return route.fulfill(status=200,content_type="application/json",
                    body=json.dumps({"success":True,"job":{"id":"b"*32},
                                     "contains_configuration_values":False}))
        if route.request.method=="GET" and u.path=="/admin/8311/pon_config_status":
            self.status_reads+=1
            if self.confirmed:
                payload={"success":True,"pending":False,
                         "confirmation_available":False,
                         "pon_registered_o5_1":True,"omcid_running":True,
                         "contains_configuration_values":False}
            elif self.status_reads==1:
                payload={"success":True,"pending":True,"job_id":"b"*32,
                         "phase":"armed","confirmation_available":False,
                         "pon_registered_o5_1":False,"omcid_running":True,
                         "olt_per_field_effect_proven":False,
                         "contains_configuration_values":False}
            else:
                payload={"success":True,"pending":True,"job_id":"b"*32,
                         "phase":"trial_running","confirmation_available":True,
                         "pon_registered_o5_1":True,"omcid_running":True,
                         "olt_per_field_effect_proven":False,
                         "contains_configuration_values":False}
            return route.fulfill(status=200,content_type="application/json",
                                 body=json.dumps(payload))
        return route.abort()

    def test_pon_review_uses_guarded_job_waits_for_health_and_confirms(self):
        self.page.evaluate("saveConfig(document.getElementById('8311-config'))")
        self.page.wait_for_function("!document.getElementById('config-confirm').disabled")
        self.page.locator("#config-confirm").click()
        self.page.wait_for_function(
            "() => document.getElementById('config-message').textContent.includes('not O5.1')")
        self.page.wait_for_function(
            "() => Array.from(document.querySelectorAll('#config-message button')).some(b => b.textContent.includes('Confirm PON/OMCI'))",
            timeout=8000)
        message=self.page.locator("#config-message").inner_text()
        self.assertNotIn(SECRET,message)
        self.assertIn("Per-field OLT acceptance is not inferred",message)

        button=self.page.get_by_role("button",name="Confirm PON/OMCI configuration")
        button.click()
        self.page.wait_for_function(
            "() => document.getElementById('config-message').textContent.includes('has finalized')",
            timeout=8000)

        paths=[p for p,_ in self.requests]
        self.assertEqual(paths.count("/admin/8311/save"),1)
        self.assertEqual(paths.count("/admin/8311/pon_config_apply"),1)
        self.assertEqual(paths.count("/admin/8311/pon_config_confirm"),1)
        self.assertNotIn("/admin/8311/management_apply",paths)
        apply_body=next(b for p,b in self.requests if p=="/admin/8311/pon_config_apply")
        self.assertEqual(apply_body["mode"],["apply"])
        self.assertEqual(apply_body["reg_id_hex"],[SECRET])
        confirm_body=next(b for p,b in self.requests if p=="/admin/8311/pon_config_confirm")
        self.assertEqual(set(confirm_body),{"token","job_id"})
        self.assertEqual(confirm_body["job_id"],["b"*32])
        self.assertGreaterEqual(self.status_reads,3)
        self.assertNotIn(SECRET,self.page.locator("#config-message").inner_text())

if __name__=="__main__":
    unittest.main()
