from pathlib import Path
import importlib.util
import json
import subprocess
import unittest

ROOT=Path(__file__).resolve().parents[1]
TOOL=ROOT/"tools/build_c017_gui_audit.py"
DOC=ROOT/"docs/C-017-GUI-BACKEND-AUDIT.json"

spec=importlib.util.spec_from_file_location("c017",TOOL)
c017=importlib.util.module_from_spec(spec)
spec.loader.exec_module(c017)

class C017GuiAuditTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.report=c017.build(ROOT)

    def test_all_menu_pages_covered(self):
        s=self.report["summary"]
        self.assertEqual(s["menu_pages"],14)
        self.assertEqual(s["menu_pages_with_real_chromium_evidence"],14)
        self.assertEqual(s["uncovered_menu_pages"],0)
        routes={row["route"] for row in self.report["pages"]}
        self.assertEqual(routes,{
            "config","pon_status","pon_explorer","vlans","support","firmware",
            "health","security","monitoring","history","management_preflight",
            "tls","v3","access",
        })

    def test_every_write_action_has_explicit_session_and_csrf(self):
        rows=self.report["write_actions"]
        self.assertGreaterEqual(len(rows),28)
        for row in rows:
            self.assertTrue(row["session_gate"],row)
            self.assertTrue(row["csrf_gate"],row)
        self.assertEqual(
            self.report["summary"]["write_handlers_missing_session_or_csrf_gate"],0)

    def test_committed_audit_is_deterministic(self):
        committed=json.loads(DOC.read_text())
        current=dict(self.report)
        current["controller_sha256"]=committed["controller_sha256"]
        self.assertEqual(committed,current)
        self.assertFalse(committed["live_device_queried"])
        self.assertFalse(committed["device_configuration_modified"])

    def test_builder_cli_passes_without_device_io(self):
        p=subprocess.run(["python3",str(TOOL),"--source-root",str(ROOT)],
                         capture_output=True,text=True,timeout=20)
        self.assertEqual(p.returncode,0,p.stderr)
        self.assertIn("C017_GUI_BACKEND_AUDIT_PASS",p.stdout)

if __name__=="__main__":
    unittest.main()
