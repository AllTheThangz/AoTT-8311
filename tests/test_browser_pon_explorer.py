"""Headless Chromium tests for the real AoTT PON Explorer JavaScript.

All fixtures are synthetic. Requests are intercepted, external access is
blocked, and no screenshots, browser profiles, subscriber data, or recordings
are created. Run as a separate CI browser job with AOTT_REQUIRE_BROWSER=1.

Ordinary Python source checks can run without a browser; then this suite
reports a skipped class rather than downloading any browser automatically.
"""
import os
from pathlib import Path
import re
import shutil
import unittest
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
VIEW = ROOT / "overlay/usr/lib/lua/luci/view/8311/pon_me.htm"
JS = ROOT / "overlay/www/luci-static/resources/view/8311.js"
STYLE = ROOT / "overlay/www/luci-static/bootstrap/aott-theme.css"
JQUERY = Path("/usr/share/javascript/jquery/jquery.min.js")
HOST = "http://aott.test"
PAGE_PATH = "/admin/8311/pon_explorer"
DUMP_PATH = "/cgi-bin/luci/admin/8311/pon_dump"

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    sync_playwright = None


def chrome_binary():
    return next(
        (shutil.which(name) for name in
         ("google-chrome-stable", "google-chrome", "chromium", "chromium-browser")
         if shutil.which(name)),
        None,
    )


def fixture():
    # This is the same shipped PON ME template, with LuCI substitutions filled
    # exclusively by synthetic data. There is never a call to a real ONU.
    html = VIEW.read_text()
    html = html.replace("<%+header%>", "").replace("<%+footer%>", "")
    html = re.sub(r'<script\s+src="[^"]+"\s*></script>', "", html)
    html = html.replace(
        '<%=luci.dispatcher.build_url("admin", "8311", "pon_dump")%>',
        DUMP_PATH,
    )
    entries = """
    <div class="aott-me-line" data-me-entry="1">
      <a href="/cgi-bin/luci/admin/8311/pon_dump/278/1"
         data-me-id="278" data-instance-id="1">278 VLAN example</a>
    </div>
    <div class="aott-me-line" data-me-entry="1">
      <a href="/cgi-bin/luci/admin/8311/pon_dump/7/1"
         data-me-id="7" data-instance-id="1">7 Software Image example</a>
    </div>
    """
    assert html.count("<%= omci %>") == 1
    html = html.replace("<%= omci %>", entries)
    assert "<%" not in html
    return "<!doctype html><html><head><meta charset='utf-8'></head><body>" + html + "</body></html>"


class RealBrowserPonExplorerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        strict = os.environ.get("AOTT_REQUIRE_BROWSER") == "1"
        missing = []
        if sync_playwright is None:
            missing.append("Python Playwright")
        cls.chrome = chrome_binary()
        if cls.chrome is None:
            missing.append("Chrome/Chromium executable")
        if not JQUERY.is_file():
            missing.append("system libjs-jquery")
        if missing:
            reason = "Missing headless-browser test dependencies: " + ", ".join(missing)
            if strict:
                raise AssertionError(reason)
            raise unittest.SkipTest(reason)
        cls.runner = sync_playwright().start()
        cls.browser = cls.runner.chromium.launch(
            headless=True,
            executable_path=cls.chrome,
            args=[
                "--no-sandbox", "--disable-dev-shm-usage",
                "--disable-background-networking", "--disable-extensions",
                "--no-first-run", "--disable-component-update",
            ],
        )

    @classmethod
    def tearDownClass(cls):
        if getattr(cls, "browser", None):
            cls.browser.close()
        if getattr(cls, "runner", None):
            cls.runner.stop()

    def setUp(self):
        self.context = self.browser.new_context(
            viewport={"width": 1024, "height": 768},
            service_workers="block",
            accept_downloads=False,
        )
        self.page = self.context.new_page()
        self.request_paths = []
        self.unexpected_requests = []
        self.dump_status = 200
        self.dump_body = "Synthetic OMCI attribute: <script>window.__aott_injected=true</script>"
        self.page.route("**/*", self.route)
        self.page.goto(HOST + PAGE_PATH, wait_until="load", timeout=15000)
        self.page.add_script_tag(path=str(JQUERY))
        self.page.add_style_tag(path=str(STYLE))
        self.page.add_script_tag(path=str(JS))
        self.page.wait_for_function(
            'document.getElementById("me-filter-count").textContent.includes("2 of 2")',
            timeout=10000,
        )

    def tearDown(self):
        self.context.close()

    def route(self, route):
        path = urlsplit(route.request.url).path
        if route.request.url.startswith(HOST) and path == PAGE_PATH:
            return route.fulfill(
                status=200, body=fixture(), content_type="text/html; charset=utf-8",
                headers={"Cache-Control": "no-store"},
            )
        if route.request.url.startswith(HOST) and path.startswith(DUMP_PATH + "/"):
            self.request_paths.append(path)
            return route.fulfill(
                status=self.dump_status,
                body=self.dump_body,
                content_type="text/plain; charset=utf-8",
                headers={"Cache-Control": "no-store"},
            )
        self.unexpected_requests.append(path)
        return route.abort()

    def test_search_filters_and_clears_without_network(self):
        self.page.locator("#me-filter").fill("VLAN")
        self.assertIn("1 of 2", self.page.locator("#me-filter-count").inner_text())
        self.assertFalse(self.page.locator("a[data-me-id='278']").evaluate(
            "(el) => el.closest('.aott-me-line').hidden"
        ))
        self.assertTrue(self.page.locator("a[data-me-id='7']").evaluate(
            "(el) => el.closest('.aott-me-line').hidden"
        ))
        self.page.locator("#me-clear").click()
        self.assertIn("2 of 2", self.page.locator("#me-filter-count").inner_text())
        self.assertEqual(self.request_paths, [])
        self.assertEqual(self.unexpected_requests, [])

    def test_me_read_uses_absolute_luci_route_and_text_only(self):
        self.page.locator("a[data-me-id='278']").click()
        self.page.wait_for_function(
            'document.getElementById("me-status").textContent.includes("retrieved")',
            timeout=10000,
        )
        self.assertEqual(self.request_paths, [DUMP_PATH + "/278/1"])
        self.assertIn("<script>window.__aott_injected=true</script>",
                      self.page.locator("#me_dump").inner_text())
        self.assertIsNone(self.page.evaluate("window.__aott_injected"))
        self.assertEqual(self.page.locator("#me_dump script").count(), 0)
        self.assertEqual(self.page.locator("#me_dump").get_attribute("aria-busy"),
                         "false")
        self.assertEqual(self.unexpected_requests, [])

    def test_client_rejects_out_of_range_and_missing_endpoint(self):
        self.page.evaluate("""() => {
            const entry = document.createElement("div");
            entry.className = "aott-me-line";
            entry.innerHTML = '<a href="#" data-me-id="65536" data-instance-id="1">Synthetic invalid id</a>';
            document.getElementById("me-list").appendChild(entry);
        }""")
        self.page.get_by_text("Synthetic invalid id").click()
        self.assertIn("Invalid Managed Entity identifier",
                      self.page.locator("#me-status").inner_text())
        self.assertEqual(self.request_paths, [])

        self.page.locator("#me-list").evaluate(
            "(el) => el.setAttribute('data-dump-base', '')"
        )
        self.page.locator("a[data-me-id='278']").click()
        self.assertIn("endpoint is unavailable", self.page.locator("#me-status").inner_text())
        self.assertEqual(self.request_paths, [])
        self.assertEqual(self.unexpected_requests, [])

    def test_failed_lookup_does_not_echo_response_body(self):
        self.dump_status = 502
        self.dump_body = "PRIVATE_SYNTHETIC_ERROR_SENTINEL_NOT_FOR_DISPLAY"
        self.page.locator("a[data-me-id='7']").click()
        self.page.wait_for_function(
            'document.getElementById("me-status").textContent.includes("could not be read")',
            timeout=10000,
        )
        self.assertEqual(self.request_paths, [DUMP_PATH + "/7/1"])
        self.assertNotIn("PRIVATE_SYNTHETIC_ERROR_SENTINEL_NOT_FOR_DISPLAY",
                         self.page.locator("#me_dump").inner_text())
        self.assertIn("HTTP 502", self.page.locator("#me_dump").inner_text())
        self.assertEqual(self.unexpected_requests, [])


if __name__ == "__main__":
    unittest.main()
