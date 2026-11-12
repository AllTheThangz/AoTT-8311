"""Chromium tests for the actual installed V3r4 RAM-only Ethernet error UI.

Exercises LuCI's real history.htm section and aott-history.js with Lua
generated, strictly validated data. All requests are intercepted locally.
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
TEMPLATE=ROOT/"overlay/usr/lib/lua/luci/view/8311/history.htm"
SCRIPT=ROOT/"overlay/www/luci-static/resources/view/aott-history.js"
FIXTURE=ROOT/"tests/v3r4_history_integrity_fixture.lua"
HOST="http://aott.test"
PAGE="/cgi-bin/luci/admin/8311/history"
ENDPOINT="/cgi-bin/luci/admin/8311/history_data"

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    sync_playwright=None


def sample_payload():
    p=subprocess.run(
        ["lua5.1",str(FIXTURE),str(ROOT/"overlay/usr/lib/lua"),"emit_json"],
        capture_output=True,text=True,timeout=20,cwd=ROOT
    )
    if p.returncode:raise AssertionError(p.stderr)
    key="AOTT_V3R4_INTEGRITY_JSON="
    lines=[s[len(key):] for s in p.stdout.splitlines() if s.startswith(key)]
    assert len(lines)==1
    data=json.loads(lines[0])
    assert len(data["samples"])==3
    return data


def page_html():
    source=TEMPLATE.read_text()
    match=re.search(r'<main class="aott-history".*?</main>',source,re.S)
    assert match
    body=match.group().replace(
        "<%=url('admin/8311/history_data')%>",ENDPOINT)
    assert "<%" not in body
    return "<!doctype html><html><body>"+body+"</body></html>"


class V3R4HistoryIntegrityBrowserTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        browser=next((shutil.which(n) for n in
                      ("google-chrome-stable","google-chrome",
                       "chromium","chromium-browser") if shutil.which(n)),None)
        needed=[]
        if not browser:needed.append("Chromium")
        if not shutil.which("lua5.1"):needed.append("Lua 5.1")
        if sync_playwright is None:needed.append("Playwright")
        if needed:
            reason="Missing browser dependencies: "+", ".join(needed)
            if os.getenv("AOTT_REQUIRE_BROWSER")=="1":raise AssertionError(reason)
            raise unittest.SkipTest(reason)
        cls.data=sample_payload()
        cls.runner=sync_playwright().start()
        cls.browser=cls.runner.chromium.launch(
            executable_path=browser,headless=True,
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
        self.payload=copy.deepcopy(self.data)
        self.calls=[]
        self.unexpected=[]
        self.errors=[]
        self.page.on("pageerror",lambda e:self.errors.append(str(e)))
        self.page.route("**/*",self.route)
        self.page.goto(HOST+PAGE,wait_until="load")
        self.page.add_script_tag(path=str(SCRIPT))
        self.page.wait_for_function("window.AoTTHistoryView && window.AoTTHistoryView.localRuntime===true")
        self.page.wait_for_function("document.getElementById('history-rx-fcs').textContent !== 'Unavailable'",
                                    timeout=10000)

    def tearDown(self):
        self.context.close()

    def route(self,route):
        req=route.request;u=urlsplit(req.url)
        if req.url.startswith(HOST) and u.path==PAGE:
            return route.fulfill(status=200,content_type="text/html",body=page_html())
        if req.url.startswith(HOST) and u.path==ENDPOINT:
            self.calls.append((req.method,req.url))
            return route.fulfill(status=200,content_type="application/json",
                                 body=json.dumps(self.payload))
        if req.url.startswith(HOST) and u.path=="/favicon.ico":
            return route.fulfill(status=404,body="")
        self.unexpected.append(req.url);route.abort()

    def test_actual_saved_interval_deltas_and_csv(self):
        self.assertEqual(self.page.locator("#history-rx-fcs").inner_text(),"3")
        self.assertEqual(self.page.locator("#history-rx-overflow").inner_text(),"1")
        self.assertEqual(self.page.locator("#history-rx-drop").inner_text(),"10")
        self.assertEqual(self.page.locator("#history-tx-drop").inner_text(),"5")
        self.assertIn("comparable retained host interval",
                      self.page.locator("#history-integrity-coverage").inner_text())
        rows=self.page.locator("#history-sample-rows tr")
        self.assertEqual(rows.count(),3)
        self.assertEqual(rows.first.locator("td").count(),8)
        self.assertEqual(rows.last.locator("td").nth(5).inner_text(),"Unavailable")
        csv_body=self.page.evaluate("window.AoTTHistoryView.exportCSV()")
        rows=list(csv.reader(io.StringIO(csv_body)))
        self.assertEqual(len(rows[0]),16)
        self.assertTrue(all(len(row)==16 for row in rows))
        self.assertIn("rx_fcs_error_delta",rows[0])
        self.assertIn("rx_drop_delta",rows[0])
        self.assertEqual(self.unexpected,[])
        self.assertEqual(self.errors,[])

    def test_invalid_counter_and_private_data_are_not_exported(self):
        forged=copy.deepcopy(self.data)
        forged["samples"][1]["rx_drop_delta"]=-1
        self.assertFalse(self.page.evaluate(
            "data=>window.AoTTHistoryView.render(data)",forged))
        self.assertTrue(self.page.locator("#history-json").is_disabled())
        self.assertEqual(self.page.locator("#history-rx-drop").inner_text(),"Unavailable")
        forged=copy.deepcopy(self.data)
        forged["samples"][1]["rx_drop_delta"]=1000000001
        self.assertFalse(self.page.evaluate(
            "data=>window.AoTTHistoryView.render(data)",forged))
        forged=copy.deepcopy(self.data)
        forged["samples"][1]["private_secret"]="<img onerror='window.__xss=1'>"
        self.assertTrue(self.page.evaluate(
            "data=>window.AoTTHistoryView.render(data)",forged))
        clean=self.page.evaluate("window.AoTTHistoryView.exportJSON()")
        self.assertNotIn("private_secret",clean)
        self.assertNotIn("<img",clean)
        self.assertFalse(self.page.evaluate("window.__xss===1"))
        self.assertEqual(self.errors,[])

    def test_no_background_polling_or_device_writes(self):
        self.assertEqual(len(self.calls),1)
        self.assertEqual(self.calls[0][0],"GET")
        self.assertEqual(self.unexpected,[])
        self.assertEqual(self.page.locator("#wan-state").inner_text(),"Not verified")
        self.assertEqual(self.page.locator("#optics-state").inner_text(),"Not collected")
        self.assertEqual(self.errors,[])


if __name__=="__main__":
    unittest.main()
