"""Real Chromium verification of the installed AoTT LuCI graph theme.

The fixture uses synthetic markup matching the inherited LuCI realtime
graph container. No device connection, network access or screenshots.
"""
import os
from pathlib import Path
import re
import shutil
import unittest

ROOT = Path(__file__).resolve().parents[1]
CSS = ROOT / "overlay/www/luci-static/bootstrap/aott-theme.css"

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    sync_playwright = None


def chrome():
    return next((shutil.which(p) for p in
                 ("google-chrome-stable", "google-chrome",
                  "chromium", "chromium-browser") if shutil.which(p)), None)


def rgb(value):
    value = value.strip()
    if re.fullmatch(r"#[0-9a-fA-F]{6}",value):
        return [int(value[i:i+2],16)/255 for i in (1,3,5)]
    numbers = re.findall(r"[0-9]+(?:\.[0-9]+)?", value)
    if len(numbers) < 3:
        raise ValueError("Invalid RGB color")
    return [float(n)/255 for n in numbers[:3]]


def luminance(color):
    xs = [v/12.92 if v <= 0.04045 else ((v+0.055)/1.055)**2.4
          for v in rgb(color)]
    return sum(a*b for a,b in zip(xs,(0.2126,0.7152,0.0722)))


def contrast(foreground, background):
    bright,dark = sorted((luminance(foreground),luminance(background)),
                         reverse=True)
    return (bright+0.05)/(dark+0.05)


HTML = """<!doctype html><html data-aott-theme="dark"><head>
<meta charset="utf-8"></head><body>
<div id="view" class="aott-overview-live">
  <div id="realtime" style="width:100%;height:300px;border:1px solid #000;background:#fff">
    <svg viewBox="0 0 200 100" width="200" height="100">
      <text id="tick" x="10" y="25" fill="#eeeeee">250 kb/s</text>
      <line id="grid" x1="5" y1="40" x2="180" y2="40" stroke="#eeeeee"></line>
      <polyline id="rx" points="10,80 100,20 180,65" fill="none" stroke="#444444"></polyline>
      <polyline id="tx" points="10,75 100,40 180,60" fill="none" stroke="#cccccc"></polyline>
    </svg>
  </div>
  <div class="network-status-table">
    <div class="ifacebox"><div class="ifacebox-head active">Online</div></div>
  </div>
  <div class="cbi-progressbar"><div style="width:50%"></div></div>
</div>
</body></html>"""


class RealBrowserOverviewContrastTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        required = os.environ.get("AOTT_REQUIRE_BROWSER") == "1"
        missing = []
        if sync_playwright is None:
            missing.append("Python Playwright")
        cls.binary = chrome()
        if not cls.binary:
            missing.append("Chromium")
        if missing:
            reason = "Missing browser dependencies: " + ", ".join(missing)
            if required:
                raise AssertionError(reason)
            raise unittest.SkipTest(reason)
        cls.runner = sync_playwright().start()
        cls.browser = cls.runner.chromium.launch(
            headless=True, executable_path=cls.binary,
            args=["--no-sandbox","--disable-dev-shm-usage",
                  "--disable-background-networking","--disable-extensions",
                  "--no-first-run","--disable-component-update"]
        )

    @classmethod
    def tearDownClass(cls):
        if getattr(cls, "browser", None):
            cls.browser.close()
        if getattr(cls, "runner", None):
            cls.runner.stop()

    def setUp(self):
        self.context = self.browser.new_context(
            viewport={"width":1024,"height":768},
            service_workers="block",accept_downloads=False
        )
        self.page = self.context.new_page()
        self.unexpected_requests = []
        self.page.route("**/*",lambda route: (
            self.unexpected_requests.append(route.request.url),route.abort()
        ))
        self.page.set_content(HTML,wait_until="load")
        self.page.add_style_tag(path=str(CSS))

    def tearDown(self):
        self.context.close()

    def appearance(self, theme):
        return self.page.evaluate("""theme => {
            document.documentElement.setAttribute('data-aott-theme', theme);
            const computed = id => getComputedStyle(document.getElementById(id));
            const root = getComputedStyle(document.documentElement);
            return {
                pane: root.getPropertyValue('--aott-pane-alt').trim(),
                text: root.getPropertyValue('--aott-text').trim(),
                muted: root.getPropertyValue('--aott-muted').trim(),
                graphBackground: computed('realtime').backgroundColor,
                graphText: computed('tick').fill,
                graphGrid: computed('grid').stroke,
                graphRx: computed('rx').stroke,
                graphTx: computed('tx').stroke,
                cardBackground: document.querySelector('.ifacebox') &&
                    getComputedStyle(document.querySelector('.ifacebox')).backgroundColor
            };
        }""",theme)

    def test_real_computed_graph_text_contrast_in_both_themes(self):
        for theme in ("dark","light"):
            with self.subTest(theme=theme):
                value = self.appearance(theme)
                self.assertGreaterEqual(
                    contrast(value["graphText"],value["graphBackground"]),4.5)
                self.assertGreaterEqual(
                    contrast(value["graphGrid"],value["graphBackground"]),3.0)
                self.assertGreaterEqual(
                    contrast(value["text"],value["graphBackground"]),4.5)
                self.assertGreaterEqual(
                    contrast(value["text"],value["cardBackground"]),4.5)
        self.assertEqual(self.unexpected_requests, [])

    def test_real_dark_mode_rx_tx_series_remain_distinct(self):
        value = self.appearance("dark")
        self.assertEqual(value["graphRx"],"rgb(119, 207, 255)")
        self.assertEqual(value["graphTx"],"rgb(141, 234, 157)")
        self.assertGreaterEqual(
            contrast(value["graphRx"],value["graphBackground"]),3.0)
        self.assertGreaterEqual(
            contrast(value["graphTx"],value["graphBackground"]),3.0)
        self.assertEqual(self.unexpected_requests, [])

    def test_theme_switch_restores_dark_graph_text_and_grid(self):
        first = self.appearance("dark")
        light = self.appearance("light")
        last = self.appearance("dark")
        self.assertEqual(first,last)
        self.assertNotEqual(first["graphBackground"],light["graphBackground"])
        self.assertNotEqual(first["graphText"],light["graphText"])
        self.assertEqual(self.unexpected_requests, [])

    def test_inline_css_whitespace_and_order_variations_are_accessible(self):
        # LuCI may change inline-style spacing or color serialization while
        # retaining the same graph. The theme must not depend on exact text.
        variations = (
            "width:100%;height:300px;border:1px solid #000;background:#fff",
            "width:100%;height: 300px; border:1px solid #000; background: #fff",
            "background:white; width:100%; height: 300px; border:1px solid #000",
            "height:300px; background:rgb(255,255,255); width:100%",
        )
        for style in variations:
            for theme in ("dark","light"):
                with self.subTest(style=style,theme=theme):
                    self.page.locator("#realtime").evaluate(
                        "(node, css) => node.setAttribute('style', css)",style
                    )
                    values=self.appearance(theme)
                    self.assertGreaterEqual(
                        contrast(values["graphText"],values["graphBackground"]),4.5
                    )
                    self.assertGreaterEqual(
                        contrast(values["graphGrid"],values["graphBackground"]),3.0
                    )
        self.assertEqual(self.unexpected_requests, [])

    def test_unrelated_non_graph_height_is_not_themed_as_realtime_graph(self):
        self.page.locator("#view").evaluate("""node => {
            const unrelated=document.createElement('div');
            unrelated.id='unrelated';
            unrelated.setAttribute('style','width:300px;height:200px;background:#fff');
            node.appendChild(unrelated);
        }""")
        self.appearance("dark")
        value=self.page.locator("#unrelated").evaluate(
            "el => getComputedStyle(el).backgroundColor"
        )
        self.assertEqual(value,"rgb(255, 255, 255)")
        self.assertEqual(self.unexpected_requests, [])


if __name__ == "__main__":
    unittest.main()
