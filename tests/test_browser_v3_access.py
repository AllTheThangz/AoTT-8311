from pathlib import Path
import json, os, shutil, unittest
from urllib.parse import parse_qs, urlsplit

ROOT=Path(__file__).resolve().parents[1]
JS=ROOT/"overlay/www/luci-static/resources/view/8311-access.js"
HOST="https://192.0.2.1"

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    sync_playwright=None

def browser_binary():
    return next((shutil.which(n) for n in (
        "google-chrome-stable","google-chrome","chromium","chromium-browser"
    ) if shutil.which(n)),None)

def page_html(pending=False):
    pending_html=""
    if pending:
        pending_html="""<section id="aott-access-pending" data-job-id="%s">
<button id="aott-access-confirm-pending" type="button">Confirm access settings</button>
<span id="aott-access-confirm-status"></span></section>""" % ("c"*32)
    return """<!doctype html><html><body>
<div id="aott-access-message"></div>
<form id="aott-access-form"
 data-preview-url="/admin/8311/access_preview"
 data-apply-url="/admin/8311/access_apply"
 data-confirm-url="/admin/8311/access_confirm"
 data-status-url="/admin/8311/access_status">
<input type="hidden" name="token" value="csrf-fixture">
<input type="hidden" name="revision" value="%s">
<input name="ssh_enabled" value="1">
<input name="ssh_port" value="22">
<input name="web_http_port" value="80">
<input name="web_https_port" value="8443">
<button id="aott-access-preview" type="submit">Review</button>
<button id="aott-access-apply" type="button" disabled>Apply</button>
</form>
<section id="aott-access-review" hidden><div id="aott-access-diff"></div></section>
%s
</body></html>""" % ("d"*64,pending_html)

class BrowserAccessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.binary=browser_binary()
        missing=[]
        if not cls.binary: missing.append("Chromium")
        if sync_playwright is None: missing.append("Playwright")
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

    def make_page(self,pending=False):
        context=self.browser.new_context(ignore_https_errors=True)
        page=context.new_page()
        requests=[]
        def handler(route):
            u=urlsplit(route.request.url)
            if route.request.resource_type=="document" and u.path=="/access":
                return route.fulfill(status=200,content_type="text/html",
                                     body=page_html(pending))
            if route.request.method=="POST":
                form=parse_qs(route.request.post_data or "",keep_blank_values=True)
                requests.append((u.path,form))
                if u.path=="/admin/8311/access_preview":
                    return route.fulfill(status=200,content_type="application/json",
                        body=json.dumps({
                            "success":True,"revision":"d"*64,
                            "changes_required":True,"confirmation_required":True,
                            "listener_migration_required":False,
                            "diff":[{"id":"web_https_port","before":"443","after":"8443"}],
                        }))
                if u.path=="/admin/8311/access_apply":
                    return route.fulfill(status=202,content_type="application/json",
                        body=json.dumps({
                            "success":True,"confirmation_required":True,
                            "changes_required":True,"rollback_seconds":180,
                            "job":{"id":"c"*32,"state":"running"},
                        }))
                if u.path=="/admin/8311/access_confirm":
                    return route.fulfill(status=200,content_type="application/json",
                        body=json.dumps({"success":True,"job":{"id":"c"*32}}))
            return route.abort()
        page.route("**/*",handler)
        page.goto(HOST+"/access",wait_until="load")
        page.add_script_tag(path=str(JS))
        return context,page,requests

    def test_preview_apply_and_reconnect_link(self):
        context,page,requests=self.make_page()
        try:
            page.locator("#aott-access-preview").click()
            page.wait_for_function("!document.getElementById('aott-access-apply').disabled")
            self.assertFalse(page.locator("#aott-access-review").get_attribute("hidden"))
            self.assertIn("web_https_port",page.locator("#aott-access-diff").inner_text())
            page.locator("#aott-access-apply").click()
            page.wait_for_function(
                "() => document.querySelector('#aott-access-message a') !== null")
            link=page.locator("#aott-access-message a")
            self.assertIn(":8443",link.get_attribute("href"))
            paths=[p for p,_ in requests]
            self.assertEqual(paths.count("/admin/8311/access_preview"),1)
            self.assertEqual(paths.count("/admin/8311/access_apply"),1)
            apply_form=next(b for p,b in requests if p=="/admin/8311/access_apply")
            self.assertEqual(apply_form["token"],["csrf-fixture"])
            self.assertEqual(apply_form["web_https_port"],["8443"])
        finally:
            context.close()

    def test_pending_confirmation_posts_only_job_and_csrf(self):
        context,page,requests=self.make_page(pending=True)
        try:
            page.locator("#aott-access-confirm-pending").click()
            page.wait_for_function(
                "() => document.getElementById('aott-access-confirm-status').textContent.includes('confirmed')")
            body=next(b for p,b in requests if p=="/admin/8311/access_confirm")
            self.assertEqual(set(body),{"token","job_id"})
            self.assertEqual(body["job_id"],["c"*32])
        finally:
            context.close()

if __name__=="__main__":
    unittest.main()
