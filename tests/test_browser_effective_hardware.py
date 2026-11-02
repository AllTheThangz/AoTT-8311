"""Real Chromium tests of the C-011 advanced read-only configuration panel.

Only synthetic API data and intercepted local HTTP requests. The
actual shipped LuCI template section and full 8311.js are executed.
"""
import json
import os
from pathlib import Path
import re
import shutil
import unittest
from urllib.parse import urlsplit

ROOT=Path(__file__).resolve().parents[1]
TEMPLATE=ROOT/"overlay/usr/lib/lua/luci/view/8311/config.htm"
SCRIPT=ROOT/"overlay/www/luci-static/resources/view/8311.js"
JQUERY=Path("/usr/share/javascript/jquery/jquery.min.js")
HOST="http://aott.test"
PAGE="/cgi-bin/luci/admin/8311/config"
ENDPOINT="/cgi-bin/luci/admin/8311/effective_hardware"
IDS=("bootdelay","uart_select","console_en","dying_gasp_en",
     "rx_los","ethtool_speed","failsafe_delay","persist_root")

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    sync_playwright=None


def html():
    s=TEMPLATE.read_text()
    m=re.search(r'<section id="aott-hardware-effective".*?</section>',
                s,flags=re.S)
    assert m,"Actual LuCI advanced readback section missing"
    fragment=m.group().replace(
        "<%=esc(url('admin/8311/effective_hardware'))%>",ENDPOINT)
    assert "<%" not in fragment
    return ("<!doctype html><html><head><meta charset='utf-8'>"
            "</head><body>"+fragment+"</body></html>")


def data():
    fields={}
    for id in IDS:
        fields[id]={
            "id":id,"saved_value":None,"configured_value":None,
            "observed_effective_value":None,
            "observed_source":"unavailable",
            "saved_to_observed":"unverified",
            "runtime_effect_proven":False,
            "hardware_qualified":False
        }
    fields["console_en"].update(
        saved_value="1",observed_effective_value="1",
        observed_source="kernel_gpio510_output_only",
        saved_to_observed="match")
    fields["dying_gasp_en"].update(
        saved_value="1",configured_value="1",
        observed_effective_value="1",
        observed_source="kernel_gpio508_output_only",
        saved_to_observed="match")
    fields["ethtool_speed"].update(
        saved_value="speed 10000 duplex full autoneg off")
    fields["bootdelay"].update(saved_value="3")
    fields["uart_select"].update(saved_value="on")
    return {
        "success":True,
        "data":{
            "schema":1,
            "group":"advanced_system_and_host",
            "no_device_write":True,"no_reboot":True,
            "no_firmware_commit":True,
            "contains_credential_material":False,
            "source_only_not_hardware_qualified":True,
            "fields":fields,
            "diagnostics":{
                "ethernet":{
                    "negotiated_speed_mbps":"10000",
                    "proves_speed_override_applied":False,
                    "proves_subscriber_internet":False
                },
                "rx_los_daemon_present":True,
                "rx_los_daemon_proves_alarm":False
            },
            "summary":{"source_fields":8,
                       "fully_effective_verified":0,
                       "hardware_qualified":0}
        }
    }


class HardwareBrowserTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        binary=next((shutil.which(v) for v in (
            "google-chrome-stable","google-chrome","chromium","chromium-browser"
        ) if shutil.which(v)),None)
        missing=[]
        if sync_playwright is None:missing.append("Playwright")
        if not binary:missing.append("Chromium")
        if not JQUERY.is_file():missing.append("jQuery")
        if missing:
            if os.environ.get("AOTT_REQUIRE_BROWSER")=="1":
                raise AssertionError("Missing headless dependencies: "+",".join(missing))
            raise unittest.SkipTest(",".join(missing))
        cls.runner=sync_playwright().start()
        cls.browser=cls.runner.chromium.launch(
            executable_path=binary,headless=True,
            args=["--no-sandbox","--disable-dev-shm-usage",
                  "--disable-background-networking","--disable-extensions",
                  "--no-first-run","--disable-component-update"]
        )

    @classmethod
    def tearDownClass(cls):
        if getattr(cls,"browser",None):cls.browser.close()
        if getattr(cls,"runner",None):cls.runner.stop()

    def setUp(self):
        self.ctx=self.browser.new_context(
            viewport={"width":1060,"height":750},
            service_workers="block",accept_downloads=False)
        self.page=self.ctx.new_page()
        self.requests=[]
        self.unexpected=[]
        self.errors=[]
        self.status=200
        self.payload=data()
        self.page.on("pageerror",lambda err:self.errors.append(str(err)))
        self.page.route("**/*",self.route)
        self.page.goto(HOST+PAGE,wait_until="load",timeout=13000)
        self.page.add_script_tag(path=str(JQUERY))
        self.page.add_script_tag(path=str(SCRIPT))
        self.page.wait_for_function(
            "typeof refreshHardwareEffective === 'function'",timeout=9000)

    def tearDown(self):
        self.ctx.close()

    def route(self,route):
        req=route.request
        path=urlsplit(req.url).path
        if req.url.startswith(HOST) and path==PAGE:
            return route.fulfill(
                status=200,content_type="text/html",body=html(),
                headers={"Cache-Control":"no-store"})
        if req.url.startswith(HOST) and path==ENDPOINT:
            self.requests.append((req.method,path))
            return route.fulfill(
                status=self.status,content_type="application/json",
                body=json.dumps(self.payload),
                headers={"Cache-Control":"no-store"})
        if req.url.startswith(HOST) and path=="/favicon.ico":
            return route.fulfill(status=404,body="")
        self.unexpected.append((req.method,req.url))
        return route.abort()

    def click_and_wait(self,needle="comparison complete"):
        self.page.locator("#aott-hardware-effective-refresh").click()
        self.page.wait_for_function(
            """needle => document.getElementById(
                'aott-hardware-effective-status').textContent
                .toLowerCase().includes(needle)""",
            arg=needle,timeout=12000)

    def test_manually_triggered_get_only_no_background_or_external_calls(self):
        self.assertEqual(self.requests,[])
        self.click_and_wait()
        self.assertEqual(self.requests,[("GET",ENDPOINT)])
        self.assertEqual(self.unexpected,[])
        self.assertEqual(self.page.locator(
            "#aott-hardware-effective-results table tr").count(),9)
        self.assertFalse(self.page.locator(
            "#aott-hardware-effective-results").evaluate("(el)=>el.hidden"))
        self.assertEqual(self.errors,[])

    def test_gpio_is_not_described_as_functional_console(self):
        self.click_and_wait()
        t=self.page.locator("#aott-hardware-effective-results").inner_text()
        self.assertIn("GPIO output observed, but serial or optical function unverified",t)
        self.assertIn("Host link speed is shown separately; override effect unverified",t)
        self.assertIn("Negotiated host Ethernet: 10000 Mbps",t)
        self.assertIn("do not establish forced speed",t)
        self.assertNotIn("fully qualified",t.lower())

    def test_untrusted_saved_data_escaped_and_no_credential_field(self):
        self.payload["data"]["fields"]["ethtool_speed"]["saved_value"]=(
            "<img src=x onerror=window.__hardware_xss=true>")
        self.click_and_wait()
        table=self.page.locator("#aott-hardware-effective-results")
        self.assertIn("<img src=x onerror=window.__hardware_xss=true>",
                      table.inner_text())
        self.assertEqual(table.locator("img").count(),0)
        self.assertIsNone(self.page.evaluate("window.__hardware_xss"))
        self.assertNotIn("pwhash",table.inner_text().lower())
        self.assertEqual(self.errors,[])

    def test_absent_optional_kernel_readbacks_stay_unknown(self):
        for id in ("console_en","dying_gasp_en"):
            self.payload["data"]["fields"][id].pop("observed_effective_value")
            self.payload["data"]["fields"][id].pop("observed_source")
        self.payload["data"]["diagnostics"].pop("rx_los_daemon_present")
        self.payload["data"]["diagnostics"]["ethernet"].pop("negotiated_speed_mbps")
        self.click_and_wait()
        body=self.page.locator("#aott-hardware-effective-results").inner_text()
        self.assertIn("unknown Mbps",body)
        self.assertIn("RX_LOS daemon: unknown",body)
        self.assertIn("Saved setting only; runtime effect not proven",body)

    def test_claim_of_runtime_hardware_qualification_is_rejected(self):
        self.payload["data"]["fields"]["console_en"]["runtime_effect_proven"]=True
        self.page.locator("#aott-hardware-effective-refresh").click()
        self.page.wait_for_function(
            """() => document.getElementById('aott-hardware-effective-status')
                .textContent.includes('Readback unavailable')""",
            timeout=12000)
        self.assertTrue(self.page.locator(
            "#aott-hardware-effective-results").evaluate("(el)=>el.hidden"))
        self.assertEqual(self.requests,[("GET",ENDPOINT)])

    def test_incomplete_response_or_503_fails_closed(self):
        self.click_and_wait()
        del self.payload["data"]["fields"]["uart_select"]
        self.page.locator("#aott-hardware-effective-refresh").click()
        self.page.wait_for_function(
            """() => document.getElementById('aott-hardware-effective-status')
                .textContent.includes('Readback unavailable')""",
            timeout=12000)
        self.assertEqual(self.page.locator(
            "#aott-hardware-effective-results table").count(),0)
        self.status=503
        self.payload={"success":False,"error":"Synthetic read failure"}
        self.page.locator("#aott-hardware-effective-refresh").click()
        self.page.wait_for_function(
            """() => document.getElementById('aott-hardware-effective-status')
                .textContent.includes('Readback unavailable')""",
            timeout=12000)
        self.assertIn("No settings changed",
            self.page.locator("#aott-hardware-effective-status").inner_text())
        self.assertEqual(self.unexpected,[])
        self.assertEqual(self.errors,[])

    def test_external_endpoint_is_rejected_before_network_call(self):
        self.page.locator("#aott-hardware-effective").evaluate(
            "(el)=>el.setAttribute('data-effective-url','https://remote.example/')")
        self.page.locator("#aott-hardware-effective-refresh").click()
        self.assertIn("invalid",self.page.locator(
            "#aott-hardware-effective-status").inner_text())
        self.assertEqual(self.requests,[])
        self.assertEqual(self.unexpected,[])


if __name__=="__main__":
    unittest.main()
