"""Simulate the exact administrator credential boot block with a fake shadow file.

The production device is never accessed. The test verifies that a persisted
supported hash wins and that a missing persisted hash selects the documented
root/root factory path.
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
    start = script.index("\t# A valid saved administrator hash always wins.")
    end = script.index("\n}\n\nboot() {", start)
    block = script[start:end]
    if "cat /etc/shadow" not in block or "root:root" not in block:
        raise AssertionError("Expected saved-credential and factory-default paths")
    return block

class SavedCredentialBootTest(unittest.TestCase):
    def invoke(self, present=True, fail_write=False, bad_readback=False,
               fail_factory=False):
        test_hash = "$" + "6" + "$" + "fixture" + "$" + "A" * 86
        factory_hash = "$" + "6" + "$" + "factory" + "$" + "B" * 86
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            shadow = tmp / "shadow"
            shadow.write_text("root::19000:0:99999:7:::\n")
            chpasswd = tmp / "chpasswd"
            chpasswd.write_text("""#!/bin/sh
[ "$TEST_FACTORY_FAIL" != 1 ] || exit 7
IFS= read -r line
[ "$line" = "root:root" ] || exit 8
printf 'root:%s:19000:0:99999:7:::\n' "$TEST_FACTORY_HASH" > "$TEST_SHADOW"
""")
            chpasswd.chmod(0o700)
            ready = tmp / "root-ready"
            ready.write_text("#!/bin/sh\nexit 0\n")
            ready.chmod(0o700)

            code = boot_block().replace("/etc/shadow", str(shadow))
            code = code.replace("/usr/sbin/chpasswd", str(chpasswd))
            code = code.replace("/usr/libexec/8311-root-credential-ready", str(ready))
            helpers = r"""
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
"""
            script = helpers + "\nrestore() {\n" + code + "\n}\nrestore\n"
            env = {
                **os.environ,
                "TEST_SAVED": test_hash if present else "",
                "TEST_WRITE_FAIL": "1" if fail_write else "0",
                "TEST_READBACK_BAD": "1" if bad_readback else "0",
                "TEST_FACTORY_FAIL": "1" if fail_factory else "0",
                "TEST_FACTORY_HASH": factory_hash,
                "TEST_SHADOW": str(shadow),
            }
            result = subprocess.run(
                ["/bin/sh", "-c", script], env=env,
                capture_output=True, text=True, timeout=6
            )
            captured = result.stdout + result.stderr
            self.assertNotIn(test_hash, captured, "Saved credential appeared in output")
            self.assertNotIn(factory_hash, captured, "Factory hash appeared in output")
            return result, shadow.read_text(), test_hash, factory_hash

    def test_valid_saved_hash_applies_and_verifies(self):
        proc,shadow,secret,_ = self.invoke()
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("root:"+secret+":", shadow)
        self.assertEqual(proc.stdout,"")
        self.assertEqual(proc.stderr,"")

    def test_missing_saved_hash_sets_documented_factory_root_root(self):
        proc,shadow,_,factory = self.invoke(present=False)
        self.assertEqual(proc.returncode,0,proc.stderr)
        self.assertIn("root:"+factory+":",shadow)
        self.assertIn("factory root credential (root/root)",proc.stderr)

    def test_factory_default_failure_fails_boot(self):
        proc,shadow,_,_ = self.invoke(present=False,fail_factory=True)
        self.assertNotEqual(proc.returncode,0)
        self.assertIn("failed to install documented factory root credential",proc.stderr)
        self.assertIn("root::",shadow)

    def test_failed_saved_setter_exits_without_leaking_hash(self):
        proc,shadow,_,_ = self.invoke(fail_write=True)
        self.assertNotEqual(proc.returncode,0)
        self.assertIn("failed to apply saved root credential",proc.stderr)
        self.assertIn("root::",shadow)

    def test_saved_readback_mismatch_exits(self):
        proc,shadow,_,_ = self.invoke(bad_readback=True)
        self.assertNotEqual(proc.returncode,0)
        self.assertIn("did not survive live readback",proc.stderr)
        self.assertIn("root:malformed:",shadow)

if __name__=="__main__":
    unittest.main()
