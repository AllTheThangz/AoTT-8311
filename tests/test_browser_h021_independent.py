"""H-021: real Chromium rendering of independent-cadence Lua history.

Uses the genuine source-only Lua-generated bounded JSON and static H-016
HTML/CSS/JS. Every outbound network request is blocked.
"""
import json
import os
from pathlib import Path
import shutil
import subprocess
import unittest
from urllib.parse import urlsplit

ROOT=Path(__file__).resolve().parents[1]
UI=ROOT/"prototypes/history/ui"
LUA=ROOT/"tests/h021_independent_cadence_fixture.lua"
LIB=ROOT/"prototypes/history"
OVERLAY=ROOT/"overlay/usr/lib/lua"

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    sync_playwright=None


def browser_binary():
    return next((shutil.which(x) for x in (
        "google-chrome-stable","google-chrome",
        "chromium","chromium-browser") if shutil.which(x)),None)


def source_payload():
    p=subprocess.run(
        ["lua5.1",str(LUA),str(LIB),str(OVERLAY),"emit_json"],
        cwd=ROOT,capture_output=True,text=True,timeout=25,
    )
    if p.returncode:
        raise AssertionError(p.stderr)
    lines=[x.split("=",1)[1] for x in p.stdout.splitlines()
           if x.startswith("AOTT_H021_SELECTED_JSON=")]
    if len(lines)!=1:
        raise AssertionError("Missing real Lua H-021 source projection")
    return json.loads(lines[0])


class IndependentSamplingBrowserTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        missing=[]
        binary=browser_binary()
        if not binary:missing.append("Chromium")
        if sync_playwright is None:missing.append("Playwright")
        if not shutil.which("lua5.1"):missing.append("Lua 5.1")
        if missing:
            msg="Missing dependencies: "+", ".join(missing)
            if os.getenv("AOTT_REQUIRE_BROWSER")=="1":
                raise AssertionError(msg)
            raise unittest.SkipTest(msg)
        cls.payload=source_payload()
        cls.runner=sync_playwright().start()
        cls.browser=cls.runner.chromium.launch(
            headless=True,executable_path=binary,
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
            viewport={"width":1050,"height":850},
            service_workers="block",accept_downloads=False,
        )
        self.page=self.context.new_page()
        self.errors=[]
        self.network=[]
        self.page.on("pageerror",lambda e:self.errors.append(str(e)))
        self.page.route("**/*",self.block)
        self.page.goto("http://aott.test/h021/history.html",
                       wait_until="load",timeout=15000)
        self.page.wait_for_function(
            "window.AoTTHistoryView && window.AoTTHistoryView.sourceOnly===true",
            timeout=8000,
        )

    def tearDown(self):
        self.context.close()

    def block(self,route):
        url=urlsplit(route.request.url)
        files={
            "/h021/history.html":("text/html",UI/"history.html"),
            "/h021/history.css":("text/css",UI/"history.css"),
            "/h021/history.js":("application/javascript",UI/"history.js"),
        }
        if url.scheme=="http" and url.netloc=="aott.test" and url.path in files:
            mime,path=files[url.path]
            return route.fulfill(status=200,content_type=mime,
                                 body=path.read_text(),
                                 headers={"Cache-Control":"no-store"})
        self.network.append(route.request.url)
        route.abort()

    def test_host_only_tick_is_not_misreported_as_pon_failure(self):
        self.assertEqual(self.payload["samples"][-1]["pon_observation"],
                         "not_sampled")
        self.assertEqual(self.payload["samples"][-1]["host_link_observation"],
                         "observed")
        self.assertTrue(self.page.evaluate(
            "payload=>window.AoTTHistoryView.render(payload)",
            self.payload,
        ))
        self.assertEqual(
            self.page.locator("#pon-state").inner_text(),
            "Not sampled this interval",
        )
        self.assertIn("10000 Mbps host speed",
                      self.page.locator("#host-state").inner_text())
        self.assertEqual(self.page.locator("#wan-state").inner_text(),
                         "Not verified")
        self.assertIn("Not sampled",
                      self.page.locator("#history-sample-rows").inner_text())
        self.assertNotIn("ISP outage",
                         self.page.locator("#history-event-rows").inner_text())
        self.assertGreaterEqual(
            self.page.locator(".history-rx-series").count()+
            self.page.locator(".history-rx-point").count(),1,
        )
        self.assertEqual(self.errors,[])
        self.assertEqual(self.network,[])

    def test_json_csv_preserve_not_sampled_and_real_rate_intervals(self):
        self.assertTrue(self.page.evaluate(
            "payload=>window.AoTTHistoryView.render(payload)",
            self.payload,
        ))
        raw=self.page.evaluate("window.AoTTHistoryView.exportJSON()")
        output=json.loads(raw)
        self.assertEqual(output["samples"][-1]["pon_observation"],
                         "not_sampled")
        self.assertFalse(output["actual_isp_uptime_unverified"] is False)
        self.assertEqual(output["samples"][-1]["elapsed_seconds"],120)
        self.assertGreater(output["samples"][-1]["rx_mbps"],0)
        self.assertNotIn("boot",output["samples"][-1])
        csv=self.page.evaluate("window.AoTTHistoryView.exportCSV()")
        self.assertIn('"sample"',csv)
        self.assertNotIn("RxGoodBytes",csv)
        self.assertEqual(self.network,[])
        self.assertEqual(self.errors,[])


if __name__=="__main__":
    unittest.main()
