"""Simulate the exact administrator hash restoration block with a fake shadow file.

The production device is never accessed, no real hashes/passwords are used,
and no files outside an isolated TemporaryDirectory are changed.
"""
from pathlib import Path
import os
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "overlay/etc/init.d/_8311-sysinit.sh"

def boot_block():
    script = SOURCE.read_text()
    start = script.index("\t# Apply an existing, validated saved administrator hash.")
    end = script.index("\n}\n\nboot() {", start)
    block = script[start:end]
    if "cat /etc/shadow" not in block or "unset ROOT_PWHASH" not in block:
        raise AssertionError("Expected credential readback/cleanup missing")
    return block

class SavedCredentialBootTest(unittest.TestCase):
    def invoke(self, present=True, fail_write=False, bad_readback=False):
        # Format-valid synthetic fixture, NOT a working account credential.
        test_hash = "$" + "6" + "$" + "fixture" + "$" + "A" * 86
        with tempfile.TemporaryDirectory() as tmp:
            shadow = Path(tmp) / "shadow"
            shadow.write_text("root::19000:0:99999:7:::\n")
            code = boot_block().replace("/etc/shadow", str(shadow))
            helpers = r'''
to_console() { cat >&2; }
get_8311_root_pwhash() { printf '%s\n' "$TEST_SAVED"; }
set_8311_root_pwhash() {
    [ "$TEST_WRITE_FAIL" != 1 ] || return 1
    if [ "$TEST_READBACK_BAD" = 1 ]; then
        new_hash=malformed
    else
        new_hash=$1
    fi
    printf 'root:%s:19000:0:99999:7:::\n' "$new_hash" > "$TEST_SHADOW"
}
'''
            script = helpers + "\nrestore() {\n" + code + "\n}\nrestore\n"
            env = {**os.environ, "TEST_SAVED": test_hash if present else "",
                   "TEST_WRITE_FAIL": "1" if fail_write else "0",
                   "TEST_READBACK_BAD": "1" if bad_readback else "0",
                   "TEST_SHADOW": str(shadow)}
            result = subprocess.run(["/bin/sh", "-c", script], env=env,
                                    capture_output=True, text=True, timeout=6)
            captured = result.stdout + result.stderr
            self.assertNotIn(test_hash, captured, "Credential appeared in output")
            return result, shadow.read_text(), test_hash

    def test_valid_saved_hash_applies_and_verifies(self):
        proc,shadow,secret = self.invoke()
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("root:"+secret+":", shadow)
        self.assertEqual(proc.stdout,"")
        self.assertEqual(proc.stderr,"")

    def test_missing_saved_hash_warns_without_setting_shared_default(self):
        proc,shadow,_ = self.invoke(present=False)
        self.assertEqual(proc.returncode,0)
        self.assertIn("root::",shadow)
        self.assertIn("Security warning",proc.stderr)

    def test_failed_setter_exits_and_warns_without_leaking_hash(self):
        proc,shadow,_ = self.invoke(fail_write=True)
        self.assertNotEqual(proc.returncode,0)
        self.assertIn("failed to apply",proc.stderr)
        self.assertIn("root::",shadow)

    def test_mismatch_after_setter_exits_and_warns(self):
        proc,shadow,_ = self.invoke(bad_readback=True)
        self.assertNotEqual(proc.returncode,0)
        self.assertIn("did not survive live readback",proc.stderr)
        self.assertIn("root:malformed:",shadow)

if __name__=="__main__":
    unittest.main()
