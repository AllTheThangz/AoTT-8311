"""Real Chromium tests of H-016 source-only bounded history preview.

Loads the exact source HTML/CSS/JS, with JSON produced by the real Lua
projection model. Never connects to a physical ONU, router or external URL.
"""
import json
import os
from pathlib import Path
from urllib.parse import urlsplit
import re
import shutil
import subprocess
import unittest

ROOT=Path(__file__).resolve().parents[1]
UI=ROOT/"prototypes/history/ui"
HTML=UI/"history.html"
CSS=UI/"history.css"
JS=UI/"history.js"
FIXTURE=ROOT/"tests/h016_history_export_fixture.lua"
SOURCE=ROOT/"prototypes/history"

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    sync_playwright=None


def chrome():
    return next((shutil.which(cmd) for cmd in
                 ("google-chrome-stable","google-chrome","chromium",
                  "chromium-browser") if shutil.which(cmd)),None)


def make_payloads():
    proc=subprocess.run(
        ["lua5.1",str(FIXTURE),str(SOURCE),"emit_json"],
        capture_output=True,text=True,cwd=ROOT,timeout=20,
    )
    if proc.returncode:
        raise AssertionError(proc.stderr)
    output={}
    for line in proc.stdout.splitlines():
        for name in ("AOTT_H016_JSON_PAYLOAD",
                     "AOTT_H016_SPAN_JSON_PAYLOAD"):
            prefix=name+"="
            if line.startswith(prefix):
                output[name]=json.loads(line[len(prefix):])
    if len(output)!=2:
        raise AssertionError("Expected two genuine Lua export projections")
    return output


def color_rgb(s):
    if s.startswith("#"):
        v=s.lstrip("#")
        return [int(v[n:n+2],16)/255 for n in (0,2,4)]
    nums=re.findall(r"[\d.]+",s)
    if len(nums)<3:
        raise AssertionError("Unrecognized browser color: "+s)
    return [float(num)/255 for num in nums[:3]]


def brightness(color):
    x=color_rgb(color)
    linear=[n/12.92 if n<=0.04045 else ((n+0.055)/1.055)**2.4 for n in x]
    return sum(x*y for x,y in zip(linear,[0.2126,0.7152,0.0722]))


def contrast(a,b):
    hi,lo=sorted((brightness(a),brightness(b)),reverse=True)
    return (hi+0.05)/(lo+0.05)


class SourceHistoryBrowserTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        missing=[]
        cls.binary=chrome()
        if not cls.binary:missing.append("Chrome/Chromium")
        if sync_playwright is None:missing.append("Playwright")
        if not shutil.which("lua5.1"):missing.append("Host Lua 5.1")
        if missing:
            reason="H016 browser dependencies missing: "+", ".join(missing)
            if os.environ.get("AOTT_REQUIRE_BROWSER")=="1":
                raise AssertionError(reason)
            raise unittest.SkipTest(reason)
        cls.payloads=make_payloads()
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
            viewport={"width":1100,"height":850},
            service_workers="block",accept_downloads=True,
        )
        self.page=self.context.new_page()
        self.requests=[]
        self.errors=[]
        self.page.on("pageerror",lambda error:self.errors.append(str(error)))
        self.page.route("**/*",self.route_source_only)
        self.page.goto("http://aott.test/h016/history.html",
                       wait_until="load",timeout=15000)
        self.page.wait_for_function(
            "window.AoTTHistoryView && window.AoTTHistoryView.sourceOnly===true",
            timeout=6000,
        )

    def route_source_only(self,route):
        paths={
            "/h016/history.html": ("text/html",HTML),
            "/h016/history.css": ("text/css",CSS),
            "/h016/history.js": ("application/javascript",JS),
        }
        req=route.request
        uri=urlsplit(req.url)
        if (uri.scheme=="http" and uri.hostname=="aott.test" and
                uri.path in paths):
            mime,source=paths[uri.path]
            return route.fulfill(status=200,content_type=mime,
                                 body=source.read_text(),
                                 headers={"Cache-Control":"no-store"})
        self.requests.append(req.url)
        route.abort()

    def tearDown(self):
        self.context.close()

    def render(self,variant="AOTT_H016_JSON_PAYLOAD"):
        return self.page.evaluate(
            "(value)=>window.AoTTHistoryView.render(value)",
            self.payloads[variant],
        )

    def test_initial_preview_is_inert_and_no_background_requests(self):
        self.assertIn("Source-only preview",
                      self.page.locator("#prototype-notice").inner_text())
        self.assertTrue(self.page.locator("#history-json").is_disabled())
        self.assertTrue(self.page.locator("#history-csv").is_disabled())
        self.assertEqual(self.page.locator("#wan-state").inner_text(),
                         "Not verified")
        self.assertEqual(self.page.locator("#optics-state").inner_text(),
                         "Not collected")
        self.assertEqual(self.requests,[])
        self.assertEqual(self.errors,[])

    def test_actual_lua_projection_and_distinct_statuses(self):
        self.assertTrue(self.render())
        self.assertEqual(self.page.locator("#pon-state").inner_text(),
                         "O5.1 associated")
        self.assertIn("1000 Mbps host speed",
                      self.page.locator("#host-state").inner_text())
        self.assertEqual(self.page.locator("#wan-state").inner_text(),
                         "Not verified")
        self.assertEqual(self.page.locator("#optics-state").inner_text(),
                         "Not collected")
        self.assertIn("full requested time range is not verified",
                      self.page.locator("#coverage-message").inner_text().lower())
        self.assertGreater(self.page.locator(".history-rx-series").count(),0)
        self.assertGreater(self.page.locator(".history-tx-series").count(),0)
        self.assertIn("missing intervals left blank",
                      self.page.locator("#history-chart").get_attribute("aria-label"))
        self.assertIn("Unavailable",
                      self.page.locator("#history-sample-rows").inner_text())
        self.assertNotIn("ISP outage",
                         self.page.locator("#history-event-rows").inner_text())
        self.assertEqual(self.requests,[])
        self.assertEqual(self.errors,[])

    def test_select_five_ranges_does_not_invent_90_day_retention(self):
        self.assertTrue(self.render())
        ranges=("hour","day","week","month","ninety_days")
        for value in ranges:
            with self.subTest(range=value):
                self.page.locator("#history-range").select_option(value)
                self.assertEqual(
                    self.page.locator("#history-range").input_value(),value)
                self.assertIn(
                    "full requested time range is not verified",
                    self.page.locator("#coverage-message").inner_text().lower())
        self.assertLess(
            self.payloads["AOTT_H016_JSON_PAYLOAD"]["windows"]["ninety_days"]
            ["rx"]["coverage_fraction"],0.01)
        self.assertEqual(self.requests,[])
        self.assertEqual(self.errors,[])

    def test_window_switch_restores_straddling_interval_only_in_longer_range(self):
        self.assertTrue(self.render("AOTT_H016_SPAN_JSON_PAYLOAD"))
        self.assertEqual(self.page.locator("#history-range").input_value(),"hour")
        short_table=self.page.locator("#history-sample-rows").inner_text()
        self.assertIn("200.0 s",short_table)
        self.assertNotIn("50.0 s",short_table)
        short_csv=self.page.evaluate("window.AoTTHistoryView.exportCSV()")
        self.assertNotIn('"50"',short_csv)
        row_200=next(s for s in short_csv.splitlines()
                     if s.startswith('"sample","200"'))
        self.assertIn(',"","",',row_200)
        self.page.locator("#history-range").select_option("day")
        long_table=self.page.locator("#history-sample-rows").inner_text()
        self.assertIn("50.0 s",long_table)
        day_csv=self.page.evaluate("window.AoTTHistoryView.exportCSV()")
        self.assertIn('"50"',day_csv)
        self.assertEqual(self.requests,[])
        self.assertEqual(self.errors,[])

    def test_json_csv_export_exact_sanitized_data_and_download_controls(self):
        self.assertTrue(self.render())
        serialized=self.page.evaluate("window.AoTTHistoryView.exportJSON()")
        parsed=json.loads(serialized)
        self.assertEqual(parsed["schema"],1)
        self.assertTrue(parsed["source_only_not_live"])
        self.assertEqual(len(parsed["windows"]),5)
        self.assertLessEqual(len(parsed["samples"]),100)
        self.assertLessEqual(len(parsed["events"]),100)
        self.assertNotIn('"boot":',serialized)
        self.assertNotIn("RxGoodBytes",serialized)
        self.assertNotIn("raw_output",serialized)
        raw_csv=self.page.evaluate("window.AoTTHistoryView.exportCSV()")
        self.assertIn("record_type,at_uptime,source",raw_csv)
        self.assertEqual(len(raw_csv.splitlines()),
                         len(parsed["samples"])+len(parsed["events"])+1)
        with self.page.expect_download() as json_event:
            self.page.locator("#history-json").click()
        self.assertEqual(json_event.value.suggested_filename,
                         "aott-history-hour.json")
        with self.page.expect_download() as csv_event:
            self.page.locator("#history-csv").click()
        self.assertEqual(csv_event.value.suggested_filename,
                         "aott-history-hour.csv")
        self.assertEqual(self.requests,[])
        self.assertEqual(self.errors,[])

    def test_untrusted_projection_is_rejected_without_xss_or_leaked_extra_fields(self):
        self.assertTrue(self.render())
        bad=json.loads(json.dumps(self.payloads["AOTT_H016_JSON_PAYLOAD"]))
        bad["samples"][0]["source"]="=1+1"
        result=self.page.evaluate(
            "value=>window.AoTTHistoryView.render(value)",bad)
        self.assertFalse(result)
        self.assertTrue(self.page.locator("#history-json").is_disabled())
        self.assertEqual(self.page.locator("#history-sample-rows tr").count(),0)
        self.assertEqual(self.page.locator("#history-chart").locator("*").count(),0)
        self.assertEqual(self.page.locator("#wan-state").inner_text(),
                         "Not verified")
        self.assertTrue(self.render())
        extra=json.loads(json.dumps(self.payloads["AOTT_H016_JSON_PAYLOAD"]))
        extra["samples"][0]["unknown_html"]="<img src=x>"
        extra["unknown_private_key"]="do-not-export-this-field"
        self.assertTrue(self.page.evaluate(
            "value=>window.AoTTHistoryView.render(value)",extra))
        cleaned=self.page.evaluate("window.AoTTHistoryView.exportJSON()")
        self.assertNotIn("unknown_html",cleaned)
        self.assertNotIn("unknown_private_key",cleaned)
        self.assertNotIn("do-not-export-this-field",cleaned)
        self.assertEqual(self.requests,[])
        self.assertEqual(self.errors,[])

    def test_dark_light_actual_computed_contrast_and_mobile_layout(self):
        self.assertTrue(self.render())
        for theme in ("dark","light","dark"):
            with self.subTest(theme=theme):
                self.page.locator("#history-theme").select_option(theme)
                variables=self.page.evaluate("""() => {
                    const root=getComputedStyle(document.documentElement);
                    return Object.fromEntries([
                        '--foreground','--muted','--surface-alt',
                        '--rx','--tx','--line'
                    ].map(k=>[k,root.getPropertyValue(k).trim()]));
                }""")
                panel=variables["--surface-alt"]
                self.assertGreaterEqual(
                    contrast(variables["--foreground"],panel),4.5)
                self.assertGreaterEqual(
                    contrast(variables["--muted"],panel),4.5)
                self.assertGreaterEqual(
                    contrast(variables["--rx"],panel),3.0)
                self.assertGreaterEqual(
                    contrast(variables["--tx"],panel),3.0)
                self.assertGreaterEqual(
                    contrast(variables["--line"],panel),3.0)
        self.page.set_viewport_size({"width":420,"height":850})
        self.assertEqual(self.page.locator("#history-range").count(),1)
        self.assertTrue(self.page.locator("#history-json").is_enabled())
        self.assertEqual(self.errors,[])
        self.assertEqual(self.requests,[])


if __name__=="__main__":
    unittest.main()
