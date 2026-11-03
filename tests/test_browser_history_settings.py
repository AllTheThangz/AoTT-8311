"""Real Chromium validation of source-only H-018 monitoring settings.

The fixture uses the Lua-generated schema and source defaults. Every browser
request is intercepted; no ONU, router, or settings backend is contacted.
"""
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import unittest
from urllib.parse import urlsplit

ROOT=Path(__file__).resolve().parents[1]
UI=ROOT/"prototypes/history/ui"
HTML=UI/"settings.html"
CSS=UI/"settings.css"
SHARED_CSS=UI/"history.css"
JS=UI/"settings.js"
LUA=ROOT/"tests/h018_ui_seed_fixture.lua"
MODEL=ROOT/"prototypes/history/8311/history_preferences.lua"
HOST="http://aott.test"
PAGE="/h018/settings.html"

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    sync_playwright=None


def browser_binary():
    return next((shutil.which(n) for n in (
        "google-chrome-stable","google-chrome",
        "chromium","chromium-browser") if shutil.which(n)),None)


def source_payload():
    p=subprocess.run(["lua5.1",str(LUA),str(MODEL)],
                     capture_output=True,text=True,cwd=ROOT,timeout=20)
    if p.returncode:
        raise AssertionError(p.stderr)
    lines=[x for x in p.stdout.splitlines()
           if x.startswith("AOTT_H018_SETTINGS_FIXTURE=")]
    if len(lines)!=1:
        raise AssertionError("No single H-018 fixture")
    return json.loads(lines[0].split("=",1)[1])


def rgb(value):
    if value.startswith("#"):
        raw=value[1:]
        return [int(raw[i:i+2],16)/255 for i in (0,2,4)]
    numbers=re.findall(r"\d+(?:\.\d+)?",value)
    if len(numbers)<3:
        raise ValueError("Cannot decode browser color")
    return [float(x)/255 for x in numbers[:3]]


def brightness(value):
    v=rgb(value)
    values=[x/12.92 if x<=0.04045 else ((x+.055)/1.055)**2.4 for x in v]
    return sum(a*b for a,b in zip(values,[.2126,.7152,.0722]))


def contrast(foreground,background):
    high,low=sorted((brightness(foreground),brightness(background)),
                    reverse=True)
    return (high+.05)/(low+.05)


class RealBrowserHistorySettingsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.binary=browser_binary()
        missing=[]
        if not cls.binary:missing.append("Chromium")
        if sync_playwright is None:missing.append("Playwright")
        if not shutil.which("lua5.1"):missing.append("Lua 5.1")
        if missing:
            message="Missing browser dependencies: "+", ".join(missing)
            if os.getenv("AOTT_REQUIRE_BROWSER")=="1":
                raise AssertionError(message)
            raise unittest.SkipTest(message)
        cls.payload=source_payload()
        cls.runner=sync_playwright().start()
        cls.browser=cls.runner.chromium.launch(
            executable_path=cls.binary,headless=True,
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
            viewport={"width":1100,"height":830},
            service_workers="block",accept_downloads=False,
        )
        self.page=self.context.new_page()
        self.requests=[]
        self.errors=[]
        self.page.on("pageerror",lambda e:self.errors.append(str(e)))
        self.page.route("**/*",self.route)
        self.page.goto(HOST+PAGE,wait_until="load",timeout=15000)
        self.page.wait_for_function(
            "window.AoTTHistorySettings && window.AoTTHistorySettings.sourceOnly===true",
            timeout=8000,
        )

    def tearDown(self):
        self.context.close()

    def route(self,route):
        path=urlsplit(route.request.url)
        sources={
            PAGE:("text/html",HTML),
            "/h018/settings.js":("application/javascript",JS),
            "/h018/settings.css":("text/css",CSS),
            "/h018/history.css":("text/css",SHARED_CSS),
        }
        if (path.scheme=="http" and path.netloc=="aott.test" and
                path.path in sources):
            typ,file=sources[path.path]
            return route.fulfill(status=200,content_type=typ,
                                 body=file.read_text(),
                                 headers={"Cache-Control":"no-store"})
        self.requests.append(route.request.url)
        route.abort()

    def load(self):
        return self.page.evaluate(
            "(value)=>window.AoTTHistorySettings.render(value)",
            self.payload)

    def test_page_is_preview_only_and_has_no_background_requests(self):
        self.assertIn("Source-only settings preview",
                      self.page.locator("#settings-notice").inner_text())
        self.assertTrue(self.page.locator("#settings-preview-button").is_disabled())
        self.assertTrue(self.page.locator("#settings-reset-button").is_disabled())
        self.assertEqual(self.requests,[])
        self.assertEqual(self.errors,[])

    def test_all_17_catalogued_controls_render_with_unqualified_locks(self):
        self.assertTrue(self.load())
        self.assertEqual(self.page.locator(".settings-field").count(),17)
        self.assertEqual(self.page.locator("#settings-basic-fields .settings-field").count(),6)
        self.assertEqual(self.page.locator("#settings-advanced-fields .settings-field").count(),11)
        for field in ("sampling_enabled","persist_enabled",
                      "local_alerts_enabled","rx_low_dbm",
                      "heavy_probe_seconds","retention_days",
                      "remote_notifications"):
            with self.subTest(field=field):
                self.assertTrue(self.page.locator("#setting-"+field).is_disabled())
        for field in ("pon_interval_seconds","host_interval_seconds",
                      "ram_sample_limit","ram_event_limit"):
            self.assertTrue(self.page.locator("#setting-"+field).is_enabled())
        self.assertTrue(self.page.locator("#settings-preview-button").is_enabled())
        self.assertEqual(self.requests,[])
        self.assertEqual(self.errors,[])

    def test_safe_preview_and_reset_have_no_save_effect(self):
        self.assertTrue(self.load())
        self.page.locator("#setting-pon_interval_seconds").select_option("120")
        self.page.locator("#setting-ram_sample_limit").fill("360")
        result=self.page.evaluate("window.AoTTHistorySettings.preview()")
        self.assertIsNotNone(result)
        reference=self.payload["source_reference"]
        self.assertEqual(result["worst_case_command_seconds_per_hour"],
                         reference["worst_case_command_seconds_per_hour"])
        self.assertEqual(result["pon_calls_per_hour"],
                         reference["pon_calls_per_hour"])
        self.assertEqual(result["host_calls_per_hour"],
                         reference["host_calls_per_hour"])
        self.assertEqual(result["ram_sample_limit"],
                         reference["ram_sample_limit"])
        self.assertEqual(result["changed_fields"],
                         reference["changed_fields"])
        self.assertTrue(result["no_device_write"])
        self.assertTrue(result["no_flash_write"])
        self.assertTrue(result["no_alert_sent"])
        self.assertIn("No settings saved",
                      self.page.locator("#settings-preview").inner_text())
        self.page.locator("#settings-reset-button").click()
        self.assertEqual(
            self.page.locator("#setting-pon_interval_seconds").input_value(),"60")
        self.assertEqual(
            self.page.locator("#setting-ram_sample_limit").input_value(),"120")
        self.assertIn("No changes were saved",
                      self.page.locator("#settings-preview").inner_text())
        self.assertEqual(self.requests,[])
        self.assertEqual(self.errors,[])

    def test_unsafe_fast_polling_is_rejected(self):
        self.assertTrue(self.load())
        self.page.locator("#setting-pon_interval_seconds").select_option("30")
        self.page.locator("#setting-host_interval_seconds").select_option("30")
        self.assertIsNone(
            self.page.evaluate("window.AoTTHistorySettings.preview()"))
        self.assertEqual(self.payload["source_reference"]["rejected_high_duty_reason"],
                         "probe_budget_exceeds_residential_limit")
        self.assertIn("720-second",self.page.locator("#settings-error").inner_text())
        self.assertIn("rejected",self.page.locator("#settings-preview").inner_text())
        self.assertEqual(self.requests,[])
        self.assertEqual(self.errors,[])

    def test_invalid_and_markup_values_are_never_interpreted_as_html(self):
        self.assertTrue(self.load())
        bad=json.loads(json.dumps(self.payload))
        bad["catalogue"]["fields"][0]["label"]="<img src=x>"
        self.assertTrue(self.page.evaluate(
            "value=>window.AoTTHistorySettings.render(value)",bad))
        self.assertEqual(self.page.locator(".settings-field img").count(),0)
        self.assertIn("<img src=x>",
                      self.page.locator("#settings-basic-fields").inner_text())
        bad=json.loads(json.dumps(self.payload))
        bad["catalogue"]["fields"][0]["id"]="unknown_setting"
        self.assertFalse(self.page.evaluate(
            "value=>window.AoTTHistorySettings.render(value)",bad))
        self.assertTrue(self.page.locator("#settings-preview-button").is_disabled())
        self.assertEqual(self.page.locator(".settings-field").count(),0)
        self.assertEqual(self.requests,[])
        self.assertEqual(self.errors,[])

    def test_advanced_alert_event_controls_can_preview_without_delivery(self):
        self.assertTrue(self.load())
        self.page.locator("#settings-advanced summary").click()
        checkbox=self.page.locator("#setting-alert_gaps")
        self.assertTrue(checkbox.is_checked())
        checkbox.uncheck()
        result=self.page.evaluate("window.AoTTHistorySettings.preview()")
        self.assertIn("alert_gaps",result["changed_fields"])
        self.assertTrue(result["no_alert_sent"])
        self.assertEqual(result["external_notifications"],"not_implemented")
        self.assertEqual(self.requests,[])
        self.assertEqual(self.errors,[])

    def test_dark_light_readability_and_mobile_layout(self):
        self.assertTrue(self.load())
        for theme in ("dark","light","dark"):
            self.page.locator("#settings-theme").select_option(theme)
            palette=self.page.evaluate("""() => {
                const s=getComputedStyle(document.documentElement);
                const keys=['--foreground','--muted','--surface-alt','--rx'];
                return Object.fromEntries(keys.map(k=>[k,s.getPropertyValue(k).trim()]));
            }""")
            with self.subTest(theme=theme):
                self.assertGreaterEqual(
                    contrast(palette["--foreground"],palette["--surface-alt"]),4.5)
                self.assertGreaterEqual(
                    contrast(palette["--muted"],palette["--surface-alt"]),4.5)
                self.assertGreaterEqual(
                    contrast(palette["--rx"],palette["--surface-alt"]),3)
        self.page.set_viewport_size({"width":390,"height":840})
        self.assertEqual(self.page.locator("#settings-basic-fields .settings-field").count(),6)
        self.assertTrue(self.page.locator("#settings-reset-button").is_enabled())
        self.assertEqual(self.requests,[])
        self.assertEqual(self.errors,[])


if __name__=="__main__":
    unittest.main()
