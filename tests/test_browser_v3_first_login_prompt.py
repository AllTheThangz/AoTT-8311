"""Real Chromium validation of the V3 first-login password advisory modal."""

import os
from pathlib import Path
import shutil
import unittest

ROOT=Path(__file__).resolve().parents[1]
CSS=ROOT/"overlay/www/luci-static/bootstrap/aott-theme.css"

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    sync_playwright=None

def browser_binary():
    return next((shutil.which(n) for n in (
        "google-chrome-stable","google-chrome","chromium","chromium-browser"
    ) if shutil.which(n)),None)

HTML="""<!doctype html>
<html data-aott-theme="dark"><head><meta charset="utf-8"></head><body>
<div class="aott-first-login-overlay" role="presentation">
<section class="aott-first-login-dialog" role="dialog" aria-modal="true"
 aria-labelledby="aott-first-login-title" aria-describedby="aott-first-login-description">
<p class="aott-first-login-eyebrow">First login security check</p>
<h2 id="aott-first-login-title">Change the default administrator password?</h2>
<p id="aott-first-login-description">
This device is using the documented factory login <strong>root / root</strong>.
You may keep it for local development or residential use, but changing it is recommended
before the management interface is reachable from any untrusted network.
</p>
<p class="aott-first-login-note">
Keeping <strong>root / root</strong> is allowed and does not block firmware updates,
staging, trial boots, or normal operation.
</p>
<div class="aott-first-login-actions">
<a id="change" class="btn aott-primary-action" href="/admin/system/admin/password">Change password now</a>
<form method="post" action="/admin/8311/factory_password_ack">
<input type="hidden" name="token" value="fixture">
<button id="keep" class="cbi-button" type="submit">Keep root/root</button>
</form>
</div>
</section>
</div>
</body></html>"""

class FirstLoginPromptBrowserTests(unittest.TestCase):
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

    def render(self,width,height,theme="dark"):
        context=self.browser.new_context(viewport={"width":width,"height":height},
                                         service_workers="block")
        page=context.new_page()
        unexpected=[]
        page.route("**/*",lambda route:(unexpected.append(route.request.url),route.abort()))
        page.set_content(HTML,wait_until="load")
        page.add_style_tag(path=str(CSS))
        page.evaluate("theme => document.documentElement.setAttribute('data-aott-theme',theme)",theme)
        return context,page,unexpected

    def test_modal_and_choices_are_visible_and_focusable(self):
        context,page,requests=self.render(1024,768)
        try:
            self.assertTrue(page.locator('[role="dialog"]').is_visible())
            self.assertEqual(page.locator("#change").get_attribute("href"),
                             "/admin/system/admin/password")
            self.assertEqual(page.locator("form").get_attribute("action"),
                             "/admin/8311/factory_password_ack")
            self.assertTrue(page.locator("#change").is_visible())
            self.assertTrue(page.locator("#keep").is_visible())
            page.locator("#change").focus()
            self.assertEqual(page.evaluate("document.activeElement.id"),"change")
            page.locator("#keep").focus()
            self.assertEqual(page.evaluate("document.activeElement.id"),"keep")
            self.assertEqual(requests,[])
        finally:
            context.close()

    def test_desktop_and_mobile_dialog_stay_inside_viewport(self):
        for width,height in ((1100,800),(390,740)):
            with self.subTest(width=width):
                context,page,_=self.render(width,height)
                try:
                    box=page.locator(".aott-first-login-dialog").bounding_box()
                    self.assertIsNotNone(box)
                    self.assertGreaterEqual(box["x"],0)
                    self.assertGreaterEqual(box["y"],0)
                    self.assertLessEqual(box["x"]+box["width"],width+1)
                    self.assertLessEqual(box["y"]+box["height"],height+1)
                    self.assertFalse(page.evaluate(
                        "document.documentElement.scrollWidth > document.documentElement.clientWidth"))
                finally:
                    context.close()

    def test_light_and_dark_modal_have_distinct_surface_and_text(self):
        colors=[]
        for theme in ("dark","light"):
            context,page,_=self.render(900,700,theme)
            try:
                colors.append(page.locator(".aott-first-login-dialog").evaluate(
                    "el => ({bg:getComputedStyle(el).backgroundColor,fg:getComputedStyle(el).color})"))
            finally:
                context.close()
        self.assertNotEqual(colors[0]["bg"],colors[1]["bg"])
        self.assertNotEqual(colors[0]["fg"],colors[1]["fg"])

if __name__=="__main__":
    unittest.main()
