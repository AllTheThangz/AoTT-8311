"""Portable safety contracts for the independent v2r7 source-only revision.

No connection to hardware or private build workspaces is required.
"""
import hashlib
import json
from pathlib import Path
import re
import unittest

ROOT=Path(__file__).resolve().parents[1]
THEME="www/luci-static/bootstrap/aott-theme.css"


class V2R7CandidateBoundaries(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.meta=json.loads((ROOT/"release.json").read_text())
        cls.manifest=json.loads((ROOT/"MANIFEST.json").read_text())
        cls.readme=(ROOT/"README.md").read_text()
        cls.notes=(ROOT/"docs/V2R7-RELEASE.md").read_text()
        cls.style=(ROOT/"overlay"/THEME).read_text()
        cls.header=(ROOT/"overlay/usr/lib/lua/luci/view/themes/bootstrap/header.htm").read_text()
        cls.firmware=(ROOT/"overlay/usr/lib/lua/luci/view/8311/firmware.htm").read_text()

    def test_original_offline_candidate_metadata_is_historical(self):
        self.assertEqual(self.meta["version"],"v3")
        self.assertEqual(self.meta["revision"],"r2")
        self.assertEqual(self.meta["status"],"offline-candidate")
        self.assertEqual(self.manifest["release"],"AoTT-8311-v3r2")
        self.assertEqual(self.manifest["revision"],"r2")
        self.assertIn("NOT installed, trialed or committed",self.notes)
        self.assertIn("UNTRIALED_OFFLINE_ONLY",self.notes)
        self.assertIn("safe_for_live_install=false",self.notes)

    def test_source_identity_and_cache_tags_are_current(self):
        expected={
            "etc/8311_version":"FW_VERSION=AoTT-8311-v3r2",
            "etc/aott_release":"AOTT_REVISION=r2",
            "etc/banner":"AoTT-8311-v3 r2",
            "usr/lib/lua/8311/version.lua":'revision = "r2"'
        }
        for path,label in expected.items():
            with self.subTest(file=path):
                self.assertIn(label,(ROOT/"overlay"/path).read_text())
        self.assertIn("aott-theme.css?v=aott-8311-v3r2",self.header)
        self.assertIn("8311.js?v=aott-8311-v3-r2",self.firmware)
        self.assertIn("8311.css?v=aott-8311-v3-r2",self.firmware)

    def test_theme_change_remains_scoped_to_overview_graphs(self):
        selector='#view.aott-overview-live div:is([style*="height:300px"],[style*="height: 300px"])[style*="background"]'
        self.assertEqual(self.style.count(selector),5)
        self.assertNotIn('#view div[style*="height:300px"]',self.style)
        self.assertIn("polyline#rx",self.style)
        self.assertIn("polyline#tx",self.style)

    def test_theme_asset_matches_reviewed_manifest(self):
        rows=[r for r in self.manifest["overlay_files"] if r["path"]==THEME]
        self.assertEqual(len(rows),1)
        data=(ROOT/"overlay"/THEME).read_bytes()
        self.assertEqual(rows[0]["bytes"],len(data))
        self.assertEqual(rows[0]["sha256"],hashlib.sha256(data).hexdigest())

    def test_historical_v2r6_v2r7_and_current_r8_recovery_are_distinct(self):
        self.assertIn("Historical v2r7 acceptance",self.readme)
        self.assertIn("permanently committed in bank B with v2r6",self.readme)
        self.assertIn("original r8 was committed in a",self.readme.lower())
        self.assertIn("security-enhanced r8",self.readme.lower())
        self.assertIn("B remained uncommitted",self.readme)
        self.assertIn("bank A",self.readme)
        self.assertIn("bank B",self.readme)
        self.assertIn("v2r5",self.readme)
        self.assertIn("would overwrite the valid v2r5",self.notes)
        self.assertIn("separately approved stage-only",self.notes)
        self.assertIn("distinct",self.notes)
        self.assertIn("commit approval",self.notes)
        self.assertIn("docs/V2R7-RELEASE.md",self.readme)

    def test_public_release_has_no_private_runtime_images(self):
        self.assertTrue(self.manifest["source_only"])
        self.assertFalse(self.manifest["secrets_included"])
        self.assertFalse(self.manifest["firmware_binaries_included"])
        self.assertNotIn("usr/bin/omcid",
                         {r["path"] for r in self.manifest["overlay_files"]})
        for root in (ROOT/"docs",ROOT/"tests"):
            for p in root.rglob("*"):
                if p.is_file() and p.suffix in (".md", ".py", ".lua"):
                    self.assertNotIn(chr(0x2014),p.read_text(encoding="utf-8"))


if __name__=="__main__":
    unittest.main()
