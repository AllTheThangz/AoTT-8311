"""Release documentation stays in GitHub, not in an ONU rootfs."""
from pathlib import Path
import json
import unittest

ROOT=Path(__file__).resolve().parent.parent
DOCS=[
    "docs/COMPATIBILITY.md",
    "docs/RESOURCE-ALLOCATION.md",
    "docs/BUILD-PROFILES.md",
    "docs/FEATURE-PRUNING-AUDIT.md",
    "docs/MIB-FORMAT.md",
    "docs/EXTERNAL-REFERENCE-PROJECTS.md",
    "docs/UPSTREAM-ARCHITECTURE.md",
    "docs/UPSTREAM-FORKS.md",
]


class DocumentationPolicyTests(unittest.TestCase):
    def test_all_new_documentation_is_stored_as_markdown(self):
        for rel in DOCS:
            with self.subTest(path=rel):
                self.assertTrue((ROOT/rel).is_file())
                self.assertGreater((ROOT/rel).stat().st_size,200)
                self.assertNotIn(chr(0x2014),(ROOT/rel).read_text())

    def test_readme_links_to_external_documentation(self):
        data=(ROOT/"README.md").read_text()
        self.assertNotIn(chr(0x2014),data)
        for rel in DOCS:
            self.assertIn(rel,data)

    def test_no_repository_manuals_in_overlay_manifest(self):
        manifest=json.loads((ROOT/"MANIFEST.json").read_text())
        paths={item["path"] for item in manifest["overlay_files"]}
        for rel in DOCS:
            self.assertNotIn(rel,paths)
        self.assertNotIn("etc/mibs/readme",paths)

    def test_onu_compatibility_not_claimed_universal(self):
        data=(ROOT/"docs/COMPATIBILITY.md").read_text()
        self.assertIn("Not compatible",data)
        self.assertIn("not directly verified",data)
        self.assertIn("WAS-110",data)

    def test_runtime_mib_ini_retained(self):
        data=(ROOT/"docs/BUILD-PROFILES.md").read_text()
        self.assertIn("MIB",data)
        self.assertIn("tcpdump",data)
        self.assertIn("libcrypto",data)

if __name__=="__main__":
    unittest.main()
