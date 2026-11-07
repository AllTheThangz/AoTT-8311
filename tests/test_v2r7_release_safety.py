"""Sanitized source-only assertions for the untried v2r7 candidate."""
import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


class V2R7ReleaseSafety(unittest.TestCase):
    def test_release_identifies_untried_revision(self):
        release = json.loads((ROOT / "release.json").read_text())
        self.assertEqual(release["revision"], "r1")
        self.assertEqual(release["version"], "v3")
        self.assertEqual(release["status"], "offline-candidate")
        self.assertEqual(release["hardware_profile"], "potron-prx126-aott-v1")

    def test_release_notes_preserve_approval_gate(self):
        text = (ROOT / "docs/V2R7-RELEASE.md").read_text()
        self.assertIn("UNTRIALED_OFFLINE_ONLY", text)
        self.assertIn("safe_for_live_install=false", text)
        self.assertIn("a separately approved stage-only", text)
        self.assertIn("v2r5", text)

    def test_crypto_and_omci_are_not_trimmed_for_size(self):
        notes = (ROOT / "docs/V2R5-SECURITY-AND-SIZE.md").read_text()
        for item in ("libcrypto.so.1.1", "libssl.so.1.1", "OMCI", "Mbed TLS"):
            with self.subTest(item=item):
                self.assertIn(item, notes)
        self.assertIn("OpenSSL 1.1.1", notes)
        reboot = (ROOT / "docs/V2R6-BOOT-PLAN.md").read_text()
        self.assertIn("Next reboot", reboot)
        self.assertIn("invalid or missing", reboot.lower())

    def test_public_overlay_contains_no_vendor_executables(self):
        manifest = json.loads((ROOT / "MANIFEST.json").read_text())
        self.assertFalse(manifest["firmware_binaries_included"])
        self.assertTrue(manifest["source_only"])
        self.assertEqual(manifest["release"], "AoTT-8311-v3r1")
        paths = {entry["path"] for entry in manifest["overlay_files"]}
        self.assertNotIn("usr/libexec/cgi-io", paths)
        self.assertNotIn("sbin/rpcd", paths)
        self.assertNotIn("usr/bin/omcid", paths)


if __name__ == "__main__":
    unittest.main()
