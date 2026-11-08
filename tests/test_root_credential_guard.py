from pathlib import Path
import os, shutil, subprocess, unittest

ROOT=Path(__file__).resolve().parents[1]
OVERLAY=ROOT/"overlay"
HELPER=OVERLAY/"usr/libexec/8311-root-credential-ready"
PERSIST=OVERLAY/"usr/sbin/8311-persist-root-password.sh"
UPGRADE=OVERLAY/"usr/sbin/8311-firmware-upgrade.sh"
FIXTURE=ROOT/"tests/root_credential_guard_fixture.lua"
VENDOR=Path(os.getenv("AOTT_VENDOR_ROOTFS","/missing/vendor-rootfs"))

class RootCredentialGuardTests(unittest.TestCase):
    def run_fixture(self, command):
        p=subprocess.run(command,cwd=ROOT,capture_output=True,text=True,timeout=20)
        self.assertEqual(p.returncode,0,p.stderr)
        self.assertIn("AOTT_ROOT_CREDENTIAL_GUARD_PASS",p.stdout)

    def test_host_lua_classification(self):
        if not shutil.which("lua5.1"):
            self.skipTest("Lua 5.1 unavailable")
        self.run_fixture(["lua5.1",str(FIXTURE),str(OVERLAY/"usr/lib/lua")])

    def test_vendor_mips_classification(self):
        if not shutil.which("qemu-mips-static") or not (VENDOR/"usr/bin/lua").is_file():
            self.skipTest("Vendor MIPS runtime unavailable")
        self.run_fixture(["qemu-mips-static","-L",str(VENDOR),str(VENDOR/"usr/bin/lua"),
                          str(FIXTURE),str(OVERLAY/"usr/lib/lua")])

    def test_live_helper_is_status_only_and_fixed_root_check(self):
        s=HELPER.read_text()
        self.assertIn('nixio.getsp("root")',s)
        self.assertIn('guard.classify(hash,nixio.crypt)',s)
        self.assertNotIn("print(",s)
        self.assertNotIn("io.write",s)
        self.assertNotIn("os.execute",s)
        self.assertNotIn("arg[",s)
        self.assertNotIn("known_factory_root_password",s)

    def test_persistence_accepts_factory_or_custom_supported_credential_before_hash_write(self):
        s=PERSIST.read_text()
        check=s.index("/usr/libexec/8311-root-credential-ready")
        read=s.index("ROOT_PWHASH=$(awk")
        write=s.index("fwenv_set -8 root_pwhash")
        self.assertLess(check,read)
        self.assertLess(read,write)
        self.assertIn("factory root/root",s)
        self.assertNotIn("unique root password",s)
        self.assertIn(">/dev/null 2>&1",s[check:read])

    def test_installer_preserves_credential_after_confirmation_before_bank_mutation(self):
        s=UPGRADE.read_text()
        self.assertIn("preserve_admin_credential()",s)
        call=s.rindex("\npreserve_admin_credential\n")
        prompt=s.index("Install these preflight-checked bytes into the inactive bank?")
        first_bank_mutation=s.index('persist_receipt "$INSTALL_BANK" incomplete')
        first_image_write=s.index('ubiupdatevol -s "$size"')
        self.assertGreater(call,prompt)
        self.assertLess(call,first_bank_mutation)
        self.assertLess(call,first_image_write)
        self.assertIn('"$helper" >/dev/null 2>&1',s)
        self.assertNotIn("Set a unique root password",s)

    def test_validate_only_exits_before_credential_mutation(self):
        s=UPGRADE.read_text()
        self.assertLess(s.index("$INSTALL || exit 0"),s.rindex("\npreserve_admin_credential\n"))

if __name__=="__main__":
    unittest.main()
