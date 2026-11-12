"""Chromium validation of shipped V3r4 optical History display.

The real LuCI History HTML and JavaScript are loaded with a synthetic
Lua-generated optical projection. All network requests are intercepted.
"""
import copy
import csv
import io
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import unittest
from urllib.parse import urlsplit

ROOT=Path(__file__).resolve().parents[1]
HTML=ROOT/"overlay/usr/lib/lua/luci/view/8311/history.htm"
CORE=ROOT/"overlay/www/luci-static/resources/view/aott-history.js"
OPT=ROOT/"overlay/www/luci-static/resources/view/aott-history-optics.js"
FIX=ROOT/"tests/v3r4_optical_history_fixture.lua"
HOST="http://aott.test"
PAGE="/cgi-bin/luci/admin/8311/history"
ENDPOINT="/cgi-bin/luci/admin/8311/history_data"

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    sync_playwright=None


def payload():
    p=subprocess.run(["lua5.1",str(FIX),str(ROOT/"overlay/usr/lib/lua"),
                      "emit_json"],cwd=ROOT,capture_output=True,text=True,timeout=20)
    if p.returncode:raise AssertionError(p.stderr)
    key="AOTT_V3R4_OPTICAL_JSON="
    lines=[s[len(key):] for s in p.stdout.splitlines() if s.startswith(key)]
    if len(lines)!=1:raise AssertionError("Missing Lua optical projection")
    return json.loads(lines[0])


def page_html():
    src=HTML.read_text()
    assert "aott-history-optics.js?v=aott-8311-v3r4-optical2" in src
    match=re.search(r'<main class="aott-history".*?</main>',src,re.S)
    assert match
    html=match.group().replace(
        "<%=url('admin/8311/history_data')%>",ENDPOINT)
    assert "<%" not in html
    return "<!doctype html><html><body>"+html+"</body></html>"


class OpticalHistoryBrowserTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        executable=next((shutil.which(name) for name in (
            "google-chrome-stable","google-chrome",
            "chromium","chromium-browser") if shutil.which(name)),None)
        missing=[]
        if not executable:missing.append("Chromium")
        if not shutil.which("lua5.1"):missing.append("Lua 5.1")
        if sync_playwright is None:missing.append("Playwright")
        if missing:
            reason="Missing dependencies: "+", ".join(missing)
            if os.getenv("AOTT_REQUIRE_BROWSER")=="1":raise AssertionError(reason)
            raise unittest.SkipTest(reason)
        cls.payload=payload()
        cls.runner=sync_playwright().start()
        cls.browser=cls.runner.chromium.launch(
            executable_path=executable,headless=True,
            args=["--no-sandbox","--disable-dev-shm-usage",
                  "--disable-background-networking","--disable-extensions",
                  "--no-first-run","--disable-component-update"])

    @classmethod
    def tearDownClass(cls):
        if getattr(cls,"browser",None):cls.browser.close()
        if getattr(cls,"runner",None):cls.runner.stop()

    def setUp(self):
        self.context=self.browser.new_context(
            service_workers="block",accept_downloads=False)
        self.page=self.context.new_page()
        self.data=copy.deepcopy(self.payload)
        self.calls=[];self.errors=[];self.unexpected=[]
        self.page.on("pageerror",lambda e:self.errors.append(str(e)))
        self.page.route("**/*",self.route)
        self.page.goto(HOST+PAGE,wait_until="load")
        self.page.add_script_tag(path=str(CORE))
        self.page.add_script_tag(path=str(OPT))
        self.page.wait_for_function(
            "() => window.AoTTHistoryView && window.AoTTOpticalHistory")
        self.page.evaluate("(data)=>window.AoTTHistoryView.render(data)",self.data)

    def tearDown(self):
        self.context.close()

    def route(self,route):
        req=route.request;u=urlsplit(req.url)
        if req.url.startswith(HOST) and u.path==PAGE:
            return route.fulfill(status=200,content_type="text/html",
                                 body=page_html())
        if req.url.startswith(HOST) and u.path==ENDPOINT:
            self.calls.append((req.method,req.url))
            return route.fulfill(status=200,content_type="application/json",
                                 body=json.dumps(self.data))
        if req.url.startswith(HOST) and u.path=="/favicon.ico":
            return route.fulfill(status=404,body="")
        self.unexpected.append(req.url)
        route.abort()

    def test_optical_values_trends_table_and_bounded_csv(self):
        self.assertEqual(self.page.locator("#optical-rx").inner_text(),"-13.92 dBm")
        self.assertEqual(self.page.locator("#optical-tx").inner_text(),"6.13 dBm")
        self.assertEqual(self.page.locator("#optical-rx-low").inner_text(),"-14.10 dBm")
        self.assertEqual(self.page.locator("#optical-temp-high").inner_text(),"43.50 °C")
        self.assertIn("3 retained optical sample",
                      self.page.locator("#optics-state").inner_text())
        self.assertEqual(self.page.locator("#history-optical-rows tr").count(),4)
        self.assertGreater(self.page.locator(
            "#history-optical-rx-chart circle").count(),0)
        self.assertGreater(self.page.locator(
            "#history-optical-temp-chart circle").count(),0)
        out=json.loads(self.page.evaluate("window.AoTTHistoryView.exportJSON()"))
        self.assertFalse(out["optics_history_unavailable"])
        self.assertEqual(out["samples"][1]["optic_temp_c"],43.5)
        csvbody=self.page.evaluate("window.AoTTHistoryView.exportCSV()")
        csvrows=list(csv.reader(io.StringIO(csvbody)))
        self.assertEqual(len(csvrows[0]),24)
        self.assertTrue(all(len(row)==24 for row in csvrows))
        self.assertIn("rx_power_dbm",csvrows[0])
        self.assertIn("module_voltage_v",csvrows[0])
        self.assertEqual(self.page.locator("#wan-state").inner_text(),"Not verified")
        self.assertEqual(self.unexpected,[])
        self.assertEqual(self.errors,[])

    def test_missing_optic_samples_show_unavailable_not_zero(self):
        html=self.page.locator("#history-optical-rows tr").nth(1).inner_text()
        self.assertIn("Unavailable",html)
        self.assertNotIn("0.00 dBm",html)
        self.page.locator("#history-range").select_option("week")
        self.assertEqual(self.page.locator("#optical-rx").inner_text(),"-13.92 dBm")
        self.assertEqual(self.errors,[])

    def test_conflicting_claim_invalid_number_and_secret_are_rejected(self):
        bad=copy.deepcopy(self.payload)
        bad["optics_history_unavailable"]=True
        self.assertFalse(self.page.evaluate(
            "data=>window.AoTTHistoryView.render(data)",bad))
        self.assertEqual(self.page.locator("#optical-rx").inner_text(),"Unavailable")
        bad=copy.deepcopy(self.payload)
        bad["samples"][0]["rx_power_dbm"]=-100
        self.assertFalse(self.page.evaluate(
            "data=>window.AoTTHistoryView.render(data)",bad))
        bad=copy.deepcopy(self.payload)
        bad["samples"][0]["private_eeprom"]="DO_NOT_EXPORT"
        bad["samples"][0]["loid"]="<img src=x onerror='window.__xss=true'>"
        self.assertTrue(self.page.evaluate(
            "data=>window.AoTTHistoryView.render(data)",bad))
        text=self.page.evaluate("window.AoTTHistoryView.exportJSON()")
        self.assertNotIn("DO_NOT_EXPORT",text)
        self.assertNotIn("private_eeprom",text)
        self.assertNotIn("loid",text)
        self.assertFalse(self.page.evaluate("window.__xss===true"))
        self.assertEqual(self.errors,[])

    def test_no_polling_after_load_and_no_write_requests(self):
        self.assertLessEqual(len(self.calls),1)
        self.assertTrue(all(method=="GET" for method,_ in self.calls))
        self.assertEqual(self.unexpected,[])
        self.assertEqual(self.errors,[])


if __name__=="__main__":
    unittest.main()
