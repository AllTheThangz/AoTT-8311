"""Regression checks for Overview light/dark cards, graphs and text.

Tests the theme CSS semantics, scoped selectors and WCAG contrast values.
No browser or device access is required.
"""
from pathlib import Path
import re
import unittest

ROOT=Path(__file__).resolve().parent.parent
CSS=(ROOT/"overlay/www/luci-static/bootstrap/aott-theme.css").read_text()
VIEW=(ROOT/"overlay/usr/lib/lua/luci/view/admin_status/index.htm").read_text()


def css_block(selector):
    escaped=re.escape(selector)
    match=re.search(escaped+r"\s*\{([^{}]*)\}",CSS)
    if match is None:
        raise AssertionError("Missing CSS selector: "+selector)
    return match.group(1)


def tokens(theme):
    # The original stylesheet declares color-scheme separately from the palette.
    blocks=re.findall(r':root\[data-aott-theme="'+re.escape(theme)+r'"\]\s*\{([^{}]*)\}',CSS)
    palette={}
    for body in blocks:
        palette.update(re.findall(r"(--aott-[\w-]+)\s*:\s*(#[0-9a-fA-F]{6})",body))
    if not palette:
        raise AssertionError("No theme palette: "+theme)
    return dict(palette)


def luminance(rgb):
    components=[]
    for c in (int(rgb[i:i+2],16)/255 for i in (1,3,5)):
        components.append(c/12.92 if c <= 0.04045 else ((c+0.055)/1.055)**2.4)
    return sum(x*y for x,y in zip(components,(0.2126,0.7152,0.0722)))


def contrast(foreground,background):
    bright,dark=sorted((luminance(foreground),luminance(background)),reverse=True)
    return (bright+0.05)/(dark+0.05)


class OverviewContrastTest(unittest.TestCase):
    def test_overview_has_explicit_scope(self):
        self.assertIn('id="view" class="aott-overview-live"',VIEW)

    def test_theme_is_scoped_to_overview(self):
        self.assertIn("#view.aott-overview-live .network-status-table .ifacebox",CSS)
        self.assertIn("#view.aott-overview-live .network-status-table .ifacebadge",CSS)
        self.assertIn("#view.aott-overview-live .cbi-progressbar",CSS)
        self.assertIn("#view.aott-overview-live svg text",CSS)
        self.assertIn("#view.aott-overview-live svg line",CSS)
        self.assertIn("#view.aott-overview-live svg polyline#rx",CSS)
        self.assertIn("#view.aott-overview-live svg polyline#tx",CSS)

    def test_legacy_white_card_and_text_glow_replaced(self):
        rule=css_block("[data-aott-theme] #view.aott-overview-live .network-status-table .ifacebox,\n"
                       "[data-aott-theme] #view.aott-overview-live .network-status-table .ifacebadge")
        self.assertIn("background:var(--aott-pane-alt)",rule)
        self.assertIn("background-image:none",rule)
        self.assertIn("text-shadow:none",rule)
        self.assertIn("color:var(--aott-text)",rule)

    def test_progress_labels_have_sufficient_contrast_over_filled_and_empty_track(self):
        light,dark=tokens("light"),tokens("dark")
        light_bar="#91cffa"
        for name,theme,fill in (("light",light,light_bar),
                                ("dark",dark,dark["--aott-action"])):
            with self.subTest(theme=name,part="track"):
                self.assertGreaterEqual(
                    contrast(theme["--aott-text"],theme["--aott-control"]),
                    4.5)
            with self.subTest(theme=name,part="bar"):
                self.assertGreaterEqual(
                    contrast(theme["--aott-text"],fill),
                    4.5)
        label=css_block("[data-aott-theme] #view.aott-overview-live .cbi-progressbar::after")
        self.assertIn("color:var(--aott-text)",label)
        self.assertIn("text-shadow:none",label)
        self.assertIn("font-size:12px",label)

    def test_interface_card_text_contrast_in_both_themes(self):
        for name in ("light","dark"):
            theme=tokens(name)
            for surface in ("--aott-pane","--aott-pane-alt","--aott-highlight"):
                with self.subTest(theme=name,surface=surface):
                    self.assertGreaterEqual(
                        contrast(theme["--aott-text"],theme[surface]),4.5)

    def test_dark_svg_tick_text_and_grid_contrast(self):
        bg=tokens("dark")["--aott-pane-alt"]
        self.assertGreaterEqual(contrast("#f0f6ff",bg),4.5)
        self.assertGreaterEqual(contrast("#91a8c7",bg),3.0)
        self.assertGreaterEqual(contrast("#77cfff",bg),3.0)
        self.assertGreaterEqual(contrast("#8dea9d",bg),3.0)

    def test_realtime_graph_axes_text_and_container_contrast(self):
        pattern='#view div[style*="height:300px"][style*="background:#fff"]'
        container=css_block('[data-aott-theme] '+pattern)
        ticks=css_block('[data-aott-theme] '+pattern+' svg text')
        grid=css_block('[data-aott-theme] '+pattern+' svg line')
        self.assertIn('background:var(--aott-pane-alt)!important',container)
        self.assertIn('border:1px solid var(--aott-border)!important',container)
        self.assertIn('fill:var(--aott-text)!important',ticks)
        self.assertIn('text-shadow:none!important',ticks)
        self.assertIn('stroke:var(--aott-muted)!important',grid)
        for theme in ("light","dark"):
            pal=tokens(theme)
            with self.subTest(theme=theme):
                self.assertGreaterEqual(
                    contrast(pal["--aott-text"],pal["--aott-pane-alt"]),4.5)
                self.assertGreaterEqual(
                    contrast(pal["--aott-muted"],pal["--aott-pane-alt"]),3.0)

    def test_css_version_cache_refresh(self):
        header=(ROOT/"overlay/usr/lib/lua/luci/view/themes/bootstrap/header.htm").read_text()
        self.assertIn('aott-theme.css?v=aott-8311-v2r1-1-contrast',header)
        self.assertNotIn('aott-theme.css?v=aott-8311-v1-r4',header)

    def test_graph_lines_preserve_rx_tx_identity(self):
        rx=css_block('[data-aott-theme="dark"] #view.aott-overview-live svg polyline#rx')
        tx=css_block('[data-aott-theme="dark"] #view.aott-overview-live svg polyline#tx')
        self.assertIn("stroke:#77cfff",rx)
        self.assertIn("stroke:#8dea9d",tx)
        self.assertNotIn("display:none",rx+tx)

if __name__=="__main__":
    unittest.main()
