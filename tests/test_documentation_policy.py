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
    "docs/V2R5-SECURITY-AND-SIZE.md",
    "docs/V2R5-HARDWARE-TRIAL-READINESS.md",
    "docs/V2R6-BOOT-PLAN.md",
    "docs/V2R6-REPRODUCIBLE-PAIR.md",
    "docs/V2R6-STATE-GUARD.md",
    "docs/V2R6-HARDWARE-STAGING.md",
    "docs/V2R6-HARDWARE-ACCEPTANCE.md",
    "docs/V2R7-RELEASE.md",
    "docs/V2R7-HARDWARE-ACCEPTANCE.md",
    "docs/V2R8-PLAN.md",
    "docs/V2R8-IMPLEMENTATION-STATUS.md",
    "docs/V2R8-PERSISTENCE-DESIGN.md",
    "docs/V2R8-BOOT-READINESS-AUDIT.md",
    "docs/V2R8-STAGE-READINESS.md",
    "docs/V2R8-HARDWARE-TRIAL-ACCEPTANCE.md",
    "docs/V2R8-MANAGEMENT-ACL-AUDIT.md",
    "examples/monitoring/README.md",
    "docs/MONITORING-AND-TELEMETRY.md",
    "CHANGELOG.md",
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
