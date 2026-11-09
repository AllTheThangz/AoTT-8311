"""Real Chromium coverage for guarded V3 boot-configuration routing."""
from pathlib import Path
import json, os, shutil, unittest
from urllib.parse import parse_qs, urlsplit

ROOT=Path(__file__).resolve().parents[1]
JS=ROOT/"overlay/www/luci-static/resources/view/8311.js"
VENDOR=Path(os.getenv("AOTT_VENDOR_ROOTFS",
    "/var/tmp/aott-v3-rc3-release-20261107/build-A-final/rootfs"))
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

def base_form(extra=""):
    return f"""<form id="8311-config" action="/admin/8311/save"
 data-management-apply-url="/admin/8311/management_apply"
 data-management-preflight-url="/admin/8311/management_preflight"
 data-boot-apply-url="/admin/8311/boot_config_apply"
 data-boot-confirm-url="/admin/8311/boot_config_confirm"
 data-reboot-url="/admin/system/reboot"
 data-pon-apply-url="/admin/8311/pon_config_apply"
 data-pon-status-url="/admin/8311/pon_config_status"
 data-pon-confirm-url="/admin/8311/pon_config_confirm" method="post">
<input type="hidden" name="token" value="csrf-fixture">
<input type="hidden" name="complete" value="8311-v1">
<input type="hidden" name="revision" value="{"d"*64}">
<input type="hidden" name="mode" value="preview">
<input name="bootdelay" value="1">
<input name="hostname" value="fixture-host">
<button id="save-btn" type="submit">Review</button>
</form>{extra}"""

def review_html():
    return """<!doctype html><html><body><div id="config-message"></div>"""+base_form()+"""
<div id="config-review" style="display:none"><div id="config-diff"></div>
<button id="config-confirm" type="button" disabled>Confirm</button></div>
</body></html>"""

def pending_html():
    extra=f"""<section id="aott-boot-config-trial" data-job-id="{'c'*32}" data-phase="trial_running">
<button id="aott-boot-config-confirm" type="button">Confirm this boot configuration</button>
<span id="aott-boot-config-confirm-status"></span></section>"""
    return "<!doctype html><html><body><div id='config-message'></div>"+base_form(extra)+"<div id='config-review'></div></body></html>"

class BrowserBootConfigRoutingTests(unittest.TestCase):
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

    def context_page(self,body):
        context=self.browser.new_context(ignore_https_errors=True)
        page=context.new_page()
        requests=[]
        def route_handler(route):
            u=urlsplit(route.request.url)
            if route.request.resource_type=="document" and u.path=="/config":
                return route.fulfill(status=200,content_type="text/html",body=body)
            if route.request.method=="POST":
                form=parse_qs(route.request.post_data or "",keep_blank_values=True)
                requests.append((u.path,form))
                if u.path=="/admin/8311/save":
                    return route.fulfill(status=200,content_type="application/json",
                        body=json.dumps({
                            "success":True,"revision":"d"*64,
                            "route":"boot","routes":["boot"],
                            "diff":[{"id":"bootdelay","name":"Boot delay",
                                     "before":"3","after":"1",
                                     "applies":"Guarded one-boot trial"}],
                        }))
                if u.path=="/admin/8311/boot_config_apply":
                    return route.fulfill(status=200,content_type="application/json",
                        body=json.dumps({
                            "success":True,"status":"BOOT_CONFIG_TRIAL_STAGED",
                            "job_id":"c"*32,"fields":1,"reboot_required":True,
                            "confirmation_required":True,"timeout_seconds":180,
                            "contains_configuration_values":False,
                        }))
                if u.path=="/admin/8311/boot_config_confirm":
                    return route.fulfill(status=200,content_type="application/json",
                        body=json.dumps({
                            "success":True,"status":"BOOT_CONFIG_TRIAL_CONFIRMED",
                            "confirmation_required":False,
                            "contains_configuration_values":False,
                        }))
            return route.abort()
        page.route("**/*",route_handler)
        page.goto(HOST+"/config",wait_until="load")
        page.add_script_tag(path=str(JQ))
        page.add_script_tag(path=str(JS))
        page.wait_for_function("typeof saveConfig === 'function'")
        return context,page,requests

    def test_boot_review_stages_one_boot_trial_not_generic_apply(self):
        context,page,requests=self.context_page(review_html())
        try:
            page.evaluate("saveConfig(document.getElementById('8311-config'))")
            page.wait_for_function("!document.getElementById('config-confirm').disabled")
            page.locator("#config-confirm").click()
            page.wait_for_function(
                "() => document.querySelector('#config-message a') && document.querySelector('#config-message a').textContent.includes('Reboot once')")
            paths=[p for p,_ in requests]
            self.assertEqual(paths.count("/admin/8311/save"),1)
            self.assertEqual(paths.count("/admin/8311/boot_config_apply"),1)
            self.assertNotIn("/admin/8311/pon_config_apply",paths)
            body=next(b for p,b in requests if p=="/admin/8311/boot_config_apply")
            self.assertEqual(body["mode"],["apply"])
            self.assertEqual(body["bootdelay"],["1"])
            self.assertEqual(page.locator("#config-message a").get_attribute("href"),
                             "/admin/system/reboot")
            self.assertIn("previous boot settings and boot command",
                          page.locator("#config-message").inner_text())
        finally:
            context.close()

    def test_postboot_confirmation_posts_only_job_id_and_csrf(self):
        context,page,requests=self.context_page(pending_html())
        try:
            page.locator("#aott-boot-config-confirm").click()
            page.wait_for_function(
                "() => document.getElementById('aott-boot-config-confirm-status').textContent.includes('confirmed')",
                timeout=5000)
            body=next(b for p,b in requests if p=="/admin/8311/boot_config_confirm")
            self.assertEqual(set(body),{"token","job_id"})
            self.assertEqual(body["job_id"],["c"*32])
        finally:
            context.close()

if __name__=="__main__":
    unittest.main()
