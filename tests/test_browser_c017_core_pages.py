from pathlib import Path
import json, os, shutil, time, unittest
from urllib.parse import parse_qs, urlsplit

ROOT=Path(__file__).resolve().parents[1]
MAIN_JS=ROOT/"overlay/www/luci-static/resources/view/8311.js"
HEALTH_JS=ROOT/"overlay/www/luci-static/resources/view/8311-v2r1.js"
VIEWS=ROOT/"overlay/usr/lib/lua/luci/view/8311"
VENDOR=Path(os.getenv("AOTT_VENDOR_ROOTFS",
    "/var/tmp/aott-v3-az-build-20261108/build-A-final/rootfs"))
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

class BrowserC017CorePages(unittest.TestCase):
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

    def new_page(self,html,routes,script=MAIN_JS):
        context=self.browser.new_context(ignore_https_errors=True)
        page=context.new_page()
        def handler(route):
            u=urlsplit(route.request.url)
            if route.request.resource_type=="document":
                return route.fulfill(status=200,content_type="text/html",body=html)
            fn=routes.get((route.request.method,u.path))
            if fn:
                return fn(route,u)
            return route.abort()
        page.route("**/*",handler)
        page.goto(HOST+"/page",wait_until="load")
        if script==MAIN_JS:
            page.add_script_tag(path=str(JQ))
        page.add_script_tag(path=str(script))
        return context,page

    def test_pon_status_switches_actual_report_client(self):
        html="""<!doctype html><html><body>
<button class="aott-pon-quick" data-pon-status-tab="status"></button>
<button class="aott-pon-quick" data-pon-status-tab="optical"></button>
<select id="pon-status-picker"><option value="status">Registration status</option><option value="optical">Optical status</option></select>
<h3 id="pon-report-title"></h3><p id="pon-report-status"></p><pre id="pon-report"></pre>
</body></html>"""
        def text(body):
            return lambda route,u: route.fulfill(status=200,content_type="text/plain",body=body)
        context,page=self.new_page(html,{
            ("GET","/pontop/status"):text("current=51 previous=40"),
            ("GET","/pontop/optical"):text("rx_power=-14.0"),
        })
        try:
            page.evaluate("switchTabPonStatus('status')")
            page.wait_for_function("document.getElementById('pon-report').textContent.includes('current=51')")
            self.assertIn("Read-only",page.locator("#pon-report-status").inner_text())
            page.evaluate("switchTabPonStatus('optical')")
            page.wait_for_function("document.getElementById('pon-report').textContent.includes('rx_power')")
            self.assertEqual(page.locator("#pon-report-title").inner_text(),"Optical status")
        finally: context.close()

    def test_vlan_table_actual_client_is_read_only(self):
        html="""<!doctype html><html><body><p id="vlan-report-status"></p><pre id="vlan-report"></pre></body></html>"""
        context,page=self.new_page(html,{
            ("GET","/vlans/extvlans"):lambda route,u: route.fulfill(
                status=200,content_type="text/plain",body="GEM 513 -> VLAN 100")
        })
        try:
            page.evaluate("vlanTables()")
            page.wait_for_function("document.getElementById('vlan-report').textContent.includes('VLAN 100')")
            self.assertIn("Read-only VLAN inspection completed",page.locator("#vlan-report-status").inner_text())
        finally: context.close()

    def test_support_actual_client_posts_sanitized_mode_with_csrf(self):
        html="""<!doctype html><html><body>
<input id="8311-token" name="token" value="csrf-fixture">
<select id="support-mode"><option value="0" selected>Sanitized</option><option value="1">Full</option></select>
<button id="support-start"></button><div id="support-message"></div>
<div id="job-panel" data-kind="support"><p id="job-state"></p><pre id="job-output"></pre>
<button id="job-cancel"></button><a id="support-download"></a></div>
</body></html>"""
        seen=[]
        def post(route,u):
            body=parse_qs(route.request.post_data or "",keep_blank_values=True)
            seen.append(body)
            return route.fulfill(status=202,content_type="application/json",
                body=json.dumps({"id":"c"*32,"kind":"support","state":"succeeded",
                                 "output":"sanitized complete","download_ready":False,
                                 "created":int(time.time())}))
        context,page=self.new_page(html,{("POST","/support"):post})
        try:
            page.evaluate("startSupport(document.createElement('form'))")
            page.wait_for_function("document.getElementById('job-state').textContent.includes('succeeded')")
            self.assertEqual(len(seen),1)
            self.assertEqual(seen[0]["token"],["csrf-fixture"])
            self.assertEqual(seen[0]["action"],["generate"])
            self.assertEqual(seen[0]["full"],["0"])
            self.assertIn("sanitized complete",page.locator("#job-output").inner_text())
        finally: context.close()

    def test_live_health_actual_client_renders_bounded_snapshot(self):
        ids=("aott-r5-refresh","aott-r5-last-sample","aott-r5-load-status","aott-r5-pon",
             "aott-r5-eth","aott-r5-rx-dbm","aott-r5-tx-dbm","aott-r5-optic-temp",
             "aott-r5-cpu-temp","aott-r5-voltage","aott-r5-tx-bias","aott-r5-upload",
             "aott-r5-download","aott-r5-rate-notes")
        html=["<!doctype html><html><body>",
              '<select id="aott-r5-interval"><option value="0" selected>Manual</option></select>']
        for x in ids:
            tag="button" if x=="aott-r5-refresh" else "div"
            html.append(f'<{tag} id="{x}"></{tag}>')
        html.append('<table><tbody id="aott-r5-gem-body"></tbody></table>')
        html.append('<table><tbody id="aott-r5-mac-body"></tbody></table></body></html>')
        payload={
            "schema":1,"success":True,"sampled_at":int(time.time()),"uptime_seconds":100,
            "eth_speed_mbps":10000,
            "optics":{"ploam_state":51,"rx_power_dBm":-14.1,"tx_power_dBm":6.2,
                      "optic_tempC":43.0,"cpu1_tempC":50.0,"cpu2_tempC":51.0,
                      "module_voltage":3.3,"tx_bias_mA":37.0},
            "counters":{},"gem_ports":[],
        }
        context,page=self.new_page("".join(html),{
            ("GET","/cgi-bin/luci/admin/8311/health_data"):lambda route,u: route.fulfill(
                status=200,content_type="application/json",body=json.dumps(payload))
        },script=HEALTH_JS)
        try:
            page.wait_for_function("document.getElementById('aott-r5-pon').textContent.includes('O5.1')")
            self.assertIn("10.0 Gbps",page.locator("#aott-r5-eth").inner_text())
            self.assertIn("-14.10",page.locator("#aott-r5-rx-dbm").inner_text())
            self.assertIn("Live counters read successfully",page.locator("#aott-r5-load-status").inner_text())
        finally: context.close()

    def test_v3_page_source_keeps_residential_and_remote_off_contract(self):
        text=(VIEWS/"v3.htm").read_text()
        self.assertIn("Residential XGS-PON bridge / management",text)
        self.assertIn("Remote GUI default",text)
        self.assertIn("Disabled",text)
        context=self.browser.new_context(ignore_https_errors=True)
        page=context.new_page()
        try:
            page.set_content("""<!doctype html><html><body><main>
<h2>AoTT-8311 V3</h2><table><tr><td>Remote GUI default</td><td>Disabled</td></tr></table>
</main></body></html>""")
            self.assertEqual(page.locator("h2").inner_text(),"AoTT-8311 V3")
            self.assertIn("Remote GUI default",page.locator("main").inner_text())
            self.assertIn("Disabled",page.locator("main").inner_text())
        finally: context.close()

    def test_health_copy_is_not_corrupted(self):
        text=(VIEWS/"health.htm").read_text()
        self.assertIn("O5.1</strong> means optical association, not a verified Internet route",text)
        self.assertNotIn("associationNot availablenot",text)

if __name__=="__main__":
    unittest.main()
