"""Keep real Chromium mandatory in source-validation CI for every browser suite."""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


class BrowserCIGates(unittest.TestCase):
    def test_all_headless_browser_suites_are_mandatory_in_ci(self):
        workflow = (ROOT / ".github/workflows/source-validation.yml").read_text()
        self.assertIn('AOTT_REQUIRE_BROWSER: "1"', workflow)
        self.assertIn("-p 'test_browser_*.py'", workflow)
        self.assertNotIn("-p 'test_browser_pon_explorer.py'", workflow)
        self.assertIn("No installed Chrome/Chromium executable", workflow)

    def test_both_browser_suites_are_source_only(self):
        files = [p.name for p in (ROOT / "tests").glob("test_browser_*.py")]
        self.assertIn("test_browser_pon_explorer.py", files)
        self.assertIn("test_browser_firmware_boot_plan.py", files)
        self.assertEqual(len(files), len(set(files)))


if __name__ == "__main__":
    unittest.main()
