"""P0 private atomic-write regression, host source and vendor-MIPS execution."""
from pathlib import Path
import os,shutil,subprocess,tempfile,unittest
ROOT=Path(__file__).resolve().parents[1]
SOURCE=ROOT/"overlay/usr/lib/lua"
MOD=SOURCE/"8311/webutil.lua"
FIXTURE=ROOT/"tests/p0_webutil_write_fixture.lua"
VENDOR=Path(os.environ.get("AOTT_VENDOR_ROOTFS","/offline/vendor-rootfs"))

class P0WebutilPrivateWriteTests(unittest.TestCase):
    def test_no_create_then_chmod_secret_exposure(self):
        source=MOD.read_text()
        code=source.split("function M.write(",1)[1].split("\nend",1)[0]
        self.assertNotIn('io.open(path, "wb")',code)
        self.assertIn('nixio.open(stage, nixio.open_flags("wronly","creat","excl"), "0600")',code)
        self.assertIn("fd:writeall(data)",code)
        self.assertIn("fd:sync()",code)
        self.assertIn("synced ~= true",code)
        self.assertIn("fs.readfile(stage,#data+1) ~= data",code)
        self.assertLess(code.index("fd:sync()"),code.index('fs.rename(stage,path)'))
        self.assertIn("temporary.modedec ~= 600",code)
        self.assertIn("fs.chmod(stage,mode)",code)
        self.assertIn("fs.rename(stage,path)",code)
        self.assertIn("current.ino ~= existing.ino",code)
        self.assertIn("saved.modedec ~= mode",code)
        self.assertIn("#data > 1048576",code)
        self.assertLess(code.index('nixio.open(stage'),code.index('fs.chmod(stage,mode)'))
        self.assertLess(code.index('fs.chmod(stage,mode)'),code.index('fs.rename(stage,path)'))

    def test_mutating_routes_have_post_security_checks(self):
        controller=(ROOT/"overlay/usr/lib/lua/luci/controller/8311.lua").read_text()
        for name in (
            "save","save_hook_script","history_save","management_apply",
            "management_confirm","access_apply","access_confirm",
            "tls_generate","tls_import","tls_activate",
            "pon_config_apply","pon_config_confirm","boot_config_apply",
            "factory_password_ack","r8_monitoring_save","r8_monitoring_credential",
        ):
            with self.subTest(route=name):
                declaration="function action_"+name+"()"
                self.assertIn(declaration,controller)
                handler=controller.split(declaration,1)[1].split("\nfunction ",1)[0]
                self.assertIn("dispatcher.test_post_security(",handler)
                self.assertIn("dispatcher.context.authsession",handler)

    def test_vendor_mips_atomic_write_and_failure_injection(self):
        if not os.environ.get("AOTT_VENDOR_ROOTFS"):
            self.skipTest("Vendor MIPS rootfs not selected")
        if os.geteuid()!=0 or not shutil.which("qemu-mips-static") or not (VENDOR/"usr/bin/lua").is_file():
            self.skipTest("Vendor MIPS and root-owned fixture unavailable")
        with tempfile.TemporaryDirectory(prefix="aott-p0-write-fixture-") as d:
            os.chmod(d,0o700)
            result=subprocess.run([
                "qemu-mips-static","-L",str(VENDOR),str(VENDOR/"usr/bin/lua"),
                str(FIXTURE),str(SOURCE),d],
                cwd=ROOT,capture_output=True,text=True,timeout=25)
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertIn("P0_VENDOR_MIPS_ATOMIC_WRITE_PASS",result.stdout)

if __name__=="__main__":
    unittest.main()
