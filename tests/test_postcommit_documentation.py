"""Current r9 hardware acceptance plus preserved historical release records."""

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
        cls.r9accept = (ROOT / "docs/V2R9-HARDWARE-ACCEPTANCE.md").read_text()
        cls.roadmap = (ROOT / "docs/ROADMAP.md").read_text()
        cls.plan = (ROOT / "docs/V2R8-PLAN.md").read_text()
        cls.meta = json.loads((ROOT / "release.json").read_text())
        cls.manifest = json.loads((ROOT / "MANIFEST.json").read_text())

    def test_latest_hardware_status_and_fallback(self):
        self.assertIn("Firmware source in this checkout:", self.readme)
        self.assertIn("AoTT-8311-v2r9", self.readme)
        self.assertIn("Private hardware acceptance, November 7, 2026", self.readme)
        self.assertIn("permanently committed in bank A", self.readme)
        self.assertIn("Enhanced r8 remains complete and valid in bank B", self.readme)
        self.assertIn("V2R9-HARDWARE-ACCEPTANCE.md", self.readme)
        self.assertIn("v2r9 (privately hardware-qualified and committed", self.changelog)
        for phrase in ("AoTT-8311-v2r9", "Active bank | A", "Committed bank | A",
                       "PON state | O5.1", "Host Ethernet | 10,000 Mbps",
                       "Bank B native integrity | passed", "offline-candidate"):
            self.assertIn(phrase.lower(), self.r9accept.lower())

        # Older accepted releases remain documented as historical evidence.
        self.assertIn("historical v2r7 acceptance", self.readme.lower())
        self.assertIn("v2r7 (privately hardware-qualified and committed", self.changelog)
        self.assertIn("v2r7 is committed on firmware bank B", self.changelog)
        self.assertNotIn("v2r7 is an offline-only development candidate", self.readme)
        for phrase in ("AoTT-8311-v2r7", "bank B", "v2r6 in bank A",
                       "PON O5.1", "10 Gbps", "longer-term", "source overlay only"):
            self.assertIn(phrase.lower(), self.r7accept.lower())

    def test_historical_records_remain_unmodified_in_meaning(self):
        self.assertEqual(self.meta["revision"], "r1")
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

    def test_r9_acceptance_is_distinct_from_public_binary_and_future_work(self):
        self.assertIn("r9 includes the GUI-controlled optional remote syslog", self.readme)
        self.assertIn("privately hardware-qualified and committed", self.readme)
        self.assertIn("source-only", self.readme)
        self.assertIn("scope defined, implementation not started", self.plan)
        self.assertIn("v2r9", self.roadmap)
        self.assertEqual(self.meta["version"], "v3")
        self.assertIn("permanently committed in A", self.roadmap)
        self.assertIn("enhanced r8", self.roadmap.lower())
        self.assertIn("bank-B recovery image", self.roadmap)
        self.assertIn("MONITORING-AND-TELEMETRY.md", self.readme)
        self.assertEqual(self.meta["revision"], "r1")

    def test_public_source_preserves_privacy_and_manifest(self):
        data = self.readme + self.changelog + self.r7accept + self.r9accept + self.roadmap + self.plan
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
