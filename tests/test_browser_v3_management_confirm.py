"""Real Chromium validation of guarded management confirmation UI."""

from pathlib import Path
import os, shutil, unittest
from urllib.parse import parse_qs, urlsplit

ROOT=Path(__file__).resolve().parents[1]
VIEW=ROOT/"overlay/usr/lib/lua/luci/view/8311/management_preflight.htm"
HOST="https://198.51.100.10"

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    sync_playwright=None

def browser_binary():
    return next((shutil.which(n) for n in (
        "google-chrome-stable","google-chrome","chromium","chromium-browser"
    ) if shutil.which(n)),None)

def actual_script():
    source=VIEW.read_text()
    start=source.rfind("<script>")
    end=source.rfind("</script>")
    if start<0 or end<=start:
        raise AssertionError("management preflight script missing")
    script=source[start+8:end]
    if "<%" in script:
        raise AssertionError("template code unexpectedly embedded in JS")
    return script

HTML="""<!doctype html><html><head><meta charset="utf-8"></head><body>
<form id="aott-management-confirm" action="/admin/8311/management_confirm" method="post">
<input type="hidden" name="token" value="csrf-fixture">
<input type="hidden" name="job_id" value="aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa">
<button type="submit">Confirm this management path</button>
</form>
<div id="management-confirm-result" role="status"></div>
</body></html>"""

class BrowserManagementConfirmTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.binary=browser_binary()
        missing=[]
        if not cls.binary: missing.append("Chromium")
        if sync_playwright is None: missing.append("Playwright")
        if missing:
            message="Missing browser dependencies: "+", ".join(missing)
            if os.getenv("AOTT_REQUIRE_BROWSER")=="1":
                raise AssertionError(message)
            raise unittest.SkipTest(message)
        cls.script=actual_script()
        cls.runner=sync_playwright().start()
        cls.browser=cls.runner.chromium.launch(
            executable_path=cls.binary,headless=True,
            args=["--no-sandbox","--disable-dev-shm-usage",
                  "--disable-background-networking","--disable-extensions",
                  "--no-first-run","--disable-component-update"],
        )

    @classmethod
    def tearDownClass(cls):
        if getattr(cls,"browser",None): cls.browser.close()
        if getattr(cls,"runner",None): cls.runner.stop()

    def render(self,success=True):
        context=self.browser.new_context(
            viewport={"width":900,"height":650},
            service_workers="block",ignore_https_errors=True)
        page=context.new_page()
        requests=[]
        def route(req):
            u=urlsplit(req.request.url)
            if req.request.resource_type=="document":
                return req.fulfill(status=200,content_type="text/html",body=HTML)
            if u.path=="/admin/8311/management_confirm" and req.request.method=="POST":
                body=parse_qs(req.request.post_data or "",keep_blank_values=True)
                requests.append(body)
                if success:
                    return req.fulfill(
                        status=200,content_type="application/json",
                        body='{"success":true,"job":{"id":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","state":"running"}}')
                return req.fulfill(
                    status=409,content_type="application/json",
                    body='{"success":false,"error":"synthetic refusal"}')
            return req.abort()
        page.route("**/*",route)
        page.goto(HOST+"/admin/8311/management_preflight",wait_until="load")
        page.add_script_tag(content=self.script)
        return context,page,requests

    def test_success_posts_only_csrf_and_job_id_and_disables_button(self):
        context,page,requests=self.render(True)
        try:
            page.locator("#aott-management-confirm button").click()
            page.wait_for_function(
                "document.getElementById('management-confirm-result').textContent.includes('Management path confirmed')")
            self.assertEqual(len(requests),1)
            self.assertEqual(set(requests[0]),{"token","job_id"})
            self.assertEqual(requests[0]["token"],["csrf-fixture"])
            self.assertEqual(requests[0]["job_id"],["aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"])
            self.assertTrue(page.locator("#aott-management-confirm button").is_disabled())
        finally:
            context.close()

    def test_refusal_keeps_rollback_warning_and_allows_retry(self):
        context,page,requests=self.render(False)
        try:
            page.locator("#aott-management-confirm button").click()
            page.wait_for_function(
                "document.getElementById('management-confirm-result').textContent.includes('allow the existing rollback window')")
            text=page.locator("#management-confirm-result").inner_text()
            self.assertIn("Confirmation failed",text)
            self.assertIn("Do not start another change",text)
            self.assertFalse(page.locator("#aott-management-confirm button").is_disabled())
            self.assertEqual(len(requests),1)
        finally:
            context.close()

if __name__=="__main__":
    unittest.main()
