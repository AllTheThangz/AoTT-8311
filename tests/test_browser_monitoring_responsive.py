"""Real source-template mobile accessibility and overflow checks.

Uses the actual monitoring LuCI markup and production stylesheets with only
LuCI server-side directives stripped. All requests are blocked; no ONU
authentication, network connection, configuration or firmware mutation.
"""
from pathlib import Path
import os
import re
import shutil
import unittest

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "overlay/usr/lib/lua/luci/view/8311/monitoring.htm"
VENDOR = Path(os.getenv("AOTT_VENDOR_ROOTFS", "/nonexistent/vendor/rootfs"))
CSS = [
    VENDOR / "www/luci-static/bootstrap/cascade.css",
    ROOT / "overlay/www/luci-static/bootstrap/aott-theme.css",
    ROOT / "overlay/www/luci-static/bootstrap/aott-v2r1.css",
]
MOBILE = VENDOR / "www/luci-static/bootstrap/mobile.css"
try:
    from playwright.sync_api import sync_playwright
except ImportError:
    sync_playwright = None


def render_static_template():
    source = TEMPLATE.read_text()
    source = re.sub(r"<%-.*?-%>", "", source, count=1, flags=re.S)
    source = source.replace("<%+header%>", "").replace("<%+footer%>", "")
    source = re.sub(r"<script>.*?</script>", "", source, flags=re.S)
    source = re.sub(
        r"<% if monitor.first_time_unconfigured then %>.*?<% end %>",
        '<div class="aott-section-intro" role="note">'
        '<strong>Monitoring has not been configured yet.</strong></div>',
        source, flags=re.S
    )
    source = re.sub(r"<%.*?%>", "", source, flags=re.S)
    if "<%" in source or "<script" in source:
        raise ValueError("Unresolved template syntax")
    return (
        '<!doctype html><html data-aott-theme="dark"><head>'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        '</head><body><main id="maincontent" class="container">'
        + source + '</main></body></html>'
    )


class MonitoringResponsiveTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        require = os.getenv("AOTT_REQUIRE_BROWSER") == "1"
        chrome = next((shutil.which(n) for n in
                       ("google-chrome-stable", "google-chrome", "chromium")
                       if shutil.which(n)), None)
        if sync_playwright is None or chrome is None or any(
                not p.is_file() for p in CSS+[MOBILE]):
            if require:
                raise AssertionError("Real browser or preserved vendor CSS unavailable")
            raise unittest.SkipTest("Real browser or vendor CSS unavailable")
        cls.playwright = sync_playwright().start()
        cls.browser = cls.playwright.chromium.launch(
            headless=True, executable_path=chrome,
            args=["--no-sandbox", "--disable-dev-shm-usage",
                  "--disable-background-networking", "--disable-extensions",
                  "--disable-component-update", "--no-first-run"])
        cls.markup = render_static_template()

    @classmethod
    def tearDownClass(cls):
        if getattr(cls, "browser", None):
            cls.browser.close()
        if getattr(cls, "playwright", None):
            cls.playwright.stop()

    def setUp(self):
        self.context = self.browser.new_context(
            viewport={"width": 1280, "height": 900}, service_workers="block")
        self.page = self.context.new_page()
        self.unexpected = []
        self.page.route("**/*", lambda route: (
            self.unexpected.append(route.request.url), route.abort()))
        self.page.set_content(self.markup, wait_until="load")

    def tearDown(self):
        self.context.close()

    def apply_css(self, width):
        # Include vendor mobile stylesheet as its real media="max-device-width"
        # rule, not as an unconditional desktop style.
        self.page.set_viewport_size({"width": width, "height": 900})
        self.page.add_style_tag(content=CSS[0].read_text())
        if width <= 854:
            self.page.add_style_tag(content=MOBILE.read_text())
        self.page.add_style_tag(content=CSS[1].read_text())
        self.page.add_style_tag(content=CSS[2].read_text())

    def test_real_template_has_label_targets_and_no_missing_controls(self):
        self.apply_css(375)
        found = self.page.evaluate("""() => {
            const form = document.querySelector('#aott-r8-monitoring');
            if (!form) return {missing:['form'], labels:[]};
            const ids=['aott-r8-log-enabled','aott-r8-log-ip',
              'aott-r8-log-port','aott-r8-log-proto',
              'aott-r8-metrics-enabled','aott-r8-client-ip',
              'aott-r8-token-rotate','aott-r8-token-revoke',
              'aott-r8-monitor-save','aott-r8-monitor-test'];
            return {
              missing:ids.filter(id=>!document.getElementById(id)),
              labels:Array.from(form.querySelectorAll('label[for]'))
                .map(n=>({for:n.htmlFor, exists:!!document.getElementById(n.htmlFor)}))
            };
        }""")
        self.assertEqual(found["missing"], [])
        self.assertTrue(found["labels"])
        self.assertTrue(all(v["exists"] for v in found["labels"]))

    def test_real_monitoring_template_fits_mobile_and_desktop(self):
        for width in (320, 360, 375, 390, 600, 960, 1280):
            for theme in ("dark", "light"):
                with self.subTest(width=width, theme=theme):
                    self.page.set_content(self.markup, wait_until="load")
                    self.apply_css(width)
                    self.page.evaluate(
                        "(theme) => document.documentElement.setAttribute('data-aott-theme',theme)",
                        theme
                    )
                    data = self.page.evaluate("""() => {
                       const controls=Array.from(document.querySelectorAll(
                         '#aott-r8-monitoring input:not([type=hidden]), '+
                         '#aott-r8-monitoring select, #aott-r8-monitoring button'))
                         .filter(n=>getComputedStyle(n).display!=='none')
                         .map(n=>({id:n.id||n.name,
                           left:n.getBoundingClientRect().left,
                           right:n.getBoundingClientRect().right}));
                       return {viewport:innerWidth, scroll:document.documentElement.scrollWidth,
                         content:document.querySelector('#maincontent').getBoundingClientRect().width,
                         out:controls.filter(v=>v.left< -1 || v.right>innerWidth+1)}
                    }""")
                    self.assertLessEqual(data["scroll"], data["viewport"]+1,
                        "Horizontal page overflow: " + repr(data))
                    self.assertEqual(data["out"], [], data)
        self.assertEqual(self.unexpected, [])


if __name__ == "__main__":
    unittest.main()
