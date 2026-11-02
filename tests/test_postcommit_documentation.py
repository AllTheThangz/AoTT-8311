"""Public r7 source, historical r7 acceptance and private r8 trial records."""

import json
import re
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


class CurrentReleaseDocumentationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.readme = (ROOT / "README.md").read_text()
        cls.changelog = (ROOT / "CHANGELOG.md").read_text()
        cls.r6release = (ROOT / "docs/RELEASE.md").read_text()
        cls.r6accept = (ROOT / "docs/V2R6-HARDWARE-ACCEPTANCE.md").read_text()
        cls.r7accept = (ROOT / "docs/V2R7-HARDWARE-ACCEPTANCE.md").read_text()
        cls.r7build = (ROOT / "docs/V2R7-RELEASE.md").read_text()
        cls.roadmap = (ROOT / "docs/ROADMAP.md").read_text()
        cls.plan = (ROOT / "docs/V2R8-PLAN.md").read_text()
        cls.meta = json.loads((ROOT / "release.json").read_text())
        cls.manifest = json.loads((ROOT / "MANIFEST.json").read_text())

    def test_latest_hardware_status_and_fallback(self):
        # The public release remains r7, but the private hardware has since
        # moved to original r8/A committed and enhanced r8/B as a trial.
        self.assertIn("Public firmware source:", self.readme)
        self.assertIn("source-only release on `main`", self.readme)
        self.assertIn("security-enhanced", self.readme)
        self.assertIn("bank B is not permanently committed", self.readme)
        self.assertIn("original-r8 fallback", self.readme)
        self.assertIn("historical v2r7 acceptance", self.readme.lower())
        self.assertIn("v2r7 (privately hardware-qualified and committed", self.changelog)
        self.assertIn("v2r7 is committed on firmware bank B", self.changelog)
        self.assertNotIn("v2r7 is an offline-only development candidate", self.readme)
        for phrase in ("AoTT-8311-v2r7", "bank B", "v2r6 in bank A",
                       "PON O5.1", "10 Gbps", "longer-term", "source overlay only"):
            self.assertIn(phrase.lower(), self.r7accept.lower())

    def test_historical_records_remain_unmodified_in_meaning(self):
        self.assertEqual(self.meta["revision"], "r7")
        self.assertEqual(self.meta["status"], "offline-candidate")
        self.assertEqual(self.meta["hardware_profile"], "potron-prx126-aott-v1")
        self.assertIn("UNTRIALED_OFFLINE_ONLY", self.r7build)
        self.assertIn("safe_for_live_install=false", self.r7build)
        self.assertIn("UNTRIALED_OFFLINE_ONLY", self.r6release)
        self.assertIn("safe_for_live_install=false", self.r6release)
        self.assertIn("v2r7 acceptance", self.r6release.lower())
        self.assertIn("v2r6 was separately hardware-qualified", self.readme)
        self.assertIn("V2R6-HARDWARE-ACCEPTANCE.md", self.readme)
        self.assertIn("V2R7-HARDWARE-ACCEPTANCE.md", self.readme)

    def test_r8_trial_is_distinct_from_public_source_and_future_work(self):
        self.assertIn("Public main still contains r7 source only", self.readme)
        self.assertIn("private r8 hardware-trial build", self.readme)
        self.assertIn("source-only", self.readme)
        self.assertIn("scope defined, implementation not started", self.plan)
        self.assertIn("Security-enhanced v2r8", self.roadmap)
        self.assertIn("not permanently committed", self.roadmap)
        self.assertIn("MONITORING-AND-TELEMETRY.md", self.readme)
        self.assertEqual(self.meta["revision"], "r7")

    def test_public_source_preserves_privacy_and_manifest(self):
        data = self.readme + self.changelog + self.r7accept + self.roadmap + self.plan
        self.assertNotIn(chr(0x2014), data)
        for forbidden in (r"\b192\.168\.", r"\b10\.10\.10\.",
                          r"\b66\.119\.99\.", r"/var/tmp/aott-v2r7-offline-"):
            self.assertIsNone(re.search(forbidden, data))
        self.assertTrue(self.manifest["source_only"])
        self.assertFalse(self.manifest["firmware_binaries_included"])
        paths = {item["path"] for item in self.manifest["overlay_files"]}
        for name in ("docs/V2R7-HARDWARE-ACCEPTANCE.md", "docs/V2R8-PLAN.md",
                     "docs/MONITORING-AND-TELEMETRY.md", "README.md"):
            self.assertNotIn(name, paths)


if __name__ == "__main__":
    unittest.main()
