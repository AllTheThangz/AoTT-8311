"""The validator's stdout must never contaminate a saved password hash.

Tests use synthetic local shell helpers only. No passwords or device access.
"""
from pathlib import Path
import os
import re
import subprocess
import tempfile
import unittest

SOURCE=Path(__file__).resolve().parent.parent
LIB=SOURCE/"overlay/lib/8311.sh"

class RootHashValidatorOutputTests(unittest.TestCase):
    def test_validated_getter_returns_only_hash_even_when_validator_prints(self):
        content=LIB.read_text()
        match=re.search(r"^get_8311_root_pwhash\(\) \{\n.*?^\}",content,re.M|re.S)
        self.assertIsNotNone(match)
        with tempfile.TemporaryDirectory() as tmp:
            stub=Path(tmp)/"validator.sh"
            stub.write_text("#!/bin/sh\nprintf 'INTERNAL VALIDATOR DIAGNOSTIC\\n'\n"
                            "[ \"$1\" = \"$AOTT_SYNTHETIC_HASH\" ]\n")
            stub.chmod(0o700)
            getter=match.group(0).replace("/usr/libexec/8311-root-hash-valid",str(stub))
            value="synthetic-test-hash-not-an-actual-password"
            helper='fwenv_get_8311() { [ "$1" = root_pwhash ] && printf \'%s\\n\' "$AOTT_SYNTHETIC_HASH"; }\n'
            cmd=helper+getter+"\nget_8311_root_pwhash\n"
            p=subprocess.run(["sh","-c",cmd],env={**os.environ,"AOTT_SYNTHETIC_HASH":value},
                             text=True,capture_output=True,timeout=6)
            self.assertEqual(p.returncode,0,p.stderr)
            self.assertEqual(p.stdout,value+"\n")

    def test_failed_validator_is_rejected_without_diagnostic_output(self):
        content=LIB.read_text()
        match=re.search(r"^get_8311_root_pwhash\(\) \{\n.*?^\}",content,re.M|re.S)
        self.assertIsNotNone(match)
        with tempfile.TemporaryDirectory() as tmp:
            stub=Path(tmp)/"validator.sh"
            stub.write_text("#!/bin/sh\nprintf 'BAD HASH DIAGNOSTIC\\n'\nexit 1\n")
            stub.chmod(0o700)
            getter=match.group(0).replace("/usr/libexec/8311-root-hash-valid",str(stub))
            helper='fwenv_get_8311() { echo synthetic-test-value; }\n'
            cmd=helper+getter+"\nget_8311_root_pwhash\n"
            p=subprocess.run(["sh","-c",cmd],text=True,capture_output=True,timeout=6)
            self.assertNotEqual(p.returncode,0)
            self.assertEqual(p.stdout,"")

    def test_setter_also_suppresses_validator_stdout(self):
        text=LIB.read_text()
        match=re.search(r"^set_8311_root_pwhash\(\) \{\n.*?^\}",text,re.M|re.S)
        self.assertIsNotNone(match)
        self.assertIn('/usr/libexec/8311-root-hash-valid "$hash" >/dev/null 2>&1',match.group(0))

if __name__=="__main__":
    unittest.main()
