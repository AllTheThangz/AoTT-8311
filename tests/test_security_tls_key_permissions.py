"""Source-only TLS key metadata and collector NAT warning contracts.

Fixtures do not contact an ONU or read any certificate or private key.
"""
import os
from pathlib import Path
import shutil
import subprocess
import unittest

ROOT=Path(__file__).resolve().parents[1]
HEALTH=ROOT/"overlay/usr/lib/lua/8311/health.lua"
SECURITY=ROOT/"overlay/usr/lib/lua/luci/view/8311/security.htm"
CLIENT=ROOT/"overlay/www/luci-static/resources/view/8311-v2r1.js"
MONITOR=ROOT/"overlay/usr/lib/lua/luci/view/8311/monitoring.htm"
FIXTURE=ROOT/"tests/security_tls_permissions_fixture.lua"
VENDOR=Path(os.getenv("AOTT_VENDOR_ROOTFS","/nonexistent/vendor/rootfs"))

class SecurityKeyMetadataTests(unittest.TestCase):
    def test_key_path_is_never_read_or_returned(self):
        source=HEALTH.read_text()
        block=source.split("local function tls_private_key_permissions(webserver)",1)[1]
        block=block.split("\nend",1)[0]
        self.assertIn("fs.lstat(path)",block)
        self.assertNotIn("fs.readfile(path)",block)
        self.assertNotIn("web.capture(",block)
        self.assertIn("info.uid ~= 0",block)
        self.assertIn('info.type ~= "reg"',block)
        self.assertIn("info.modedec == 600",block)
        self.assertIn("info.modedec == 400",block)
        self.assertIn('return "overexposed"',block)
        self.assertIn("tls_private_key_permissions=tls_key_permissions",source)
        self.assertIn('"tls_key_file_permissions"',source)
        self.assertIn('"tls_key_file_integrity"',source)

    def test_management_page_displays_only_status(self):
        html=SECURITY.read_text()
        js=CLIENT.read_text()
        self.assertIn('id="aott-r5-https-key-permissions"',html)
        self.assertIn('put("aott-r5-https-key-permissions"',js)
        self.assertIn('overexposed:"Too permissive"',js)
        self.assertIn('restricted:"Restricted to root"',js)
        self.assertNotIn("uhttpd.key",html)
        self.assertNotIn("-"*5+"BEGIN "+"PRIVATE "+"KEY"+"-"*5,js)

    def test_monitoring_warns_about_nat_shared_source(self):
        html=MONITOR.read_text()
        self.assertIn("NAT may make multiple devices appear under the same public address",html)
        self.assertIn("cannot distinguish those devices",html)
        self.assertIn("enforce per-client access at the gateway before translation",html)
        self.assertIn("HTTPS and the separate collector token are still required",html)

    def test_real_vendor_lua51_fixtures(self):
        if not shutil.which("lua5.1"):
            self.skipTest("Lua 5.1 unavailable")
        args=["tests/security_tls_permissions_fixture.lua",
              "overlay/usr/lib/lua/8311/health.lua"]
        host=subprocess.run(["lua5.1",*args],cwd=ROOT,capture_output=True,text=True,timeout=12)
        self.assertEqual(host.returncode,0,host.stderr)
        self.assertIn("SECURITY_TLS_KEY_MODE_READONLY_FIXTURE_PASS",host.stdout)
        if os.environ.get("AOTT_VENDOR_ROOTFS"):
            if not shutil.which("qemu-mips-static") or not (VENDOR/"usr/bin/lua").is_file():
                self.fail("Explicit vendor MIPS runtime unavailable")
            target=subprocess.run(["qemu-mips-static","-L",str(VENDOR),
                                   str(VENDOR/"usr/bin/lua"),*args],
                                  cwd=ROOT,capture_output=True,text=True,timeout=20)
            self.assertEqual(target.returncode,0,target.stderr)
            self.assertIn("SECURITY_TLS_KEY_MODE_READONLY_FIXTURE_PASS",target.stdout)

if __name__=="__main__":
    unittest.main()
