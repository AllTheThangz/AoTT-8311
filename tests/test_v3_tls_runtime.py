from pathlib import Path
import importlib.util, os, shutil, subprocess, sys, unittest

ROOT=Path(__file__).resolve().parents[1]
OVERLAY=ROOT/"overlay"
LUA=OVERLAY/"usr/lib/lua"
FIXTURE=ROOT/"tests/v3_tls_runtime_fixture.lua"
VENDOR=Path(os.getenv("AOTT_VENDOR_ROOTFS","/missing/vendor-rootfs"))

class V3TlsRuntimeTests(unittest.TestCase):
    def run_fixture(self,argv):
        p=subprocess.run(argv+[str(FIXTURE),str(LUA)],cwd=ROOT,
                         capture_output=True,text=True,timeout=20)
        self.assertEqual(p.returncode,0,p.stderr)
        self.assertIn("AOTT_V3_TLS_RUNTIME_FIXTURE_PASS",p.stdout)

    def test_host_lua_validation_and_hardening_contract(self):
        if not shutil.which("lua5.1"): self.skipTest("Lua 5.1 unavailable")
        self.run_fixture(["lua5.1"])

    def test_vendor_mips_validation_and_hardening_contract(self):
        if not shutil.which("qemu-mips-static") or not (VENDOR/"usr/bin/lua").is_file():
            self.skipTest("Vendor MIPS runtime unavailable")
        self.run_fixture(["qemu-mips-static","-L",str(VENDOR),str(VENDOR/"usr/bin/lua")])

    def test_key_hardener_is_fixed_path_metadata_only(self):
        src=(LUA/"8311/tls_key_hardener.lua").read_text()
        self.assertIn('local KEY="/ptconf/8311/uhttpd/uhttpd.key"',src)
        self.assertIn("fs.lstat(KEY)",src)
        self.assertIn("fs.chmod(KEY,600)",src)
        self.assertNotIn("readfile",src)
        self.assertNotIn("io.open",src)
        self.assertNotIn("luci.model.uci",src)
        self.assertNotIn(":set(",src)
        self.assertNotIn(":commit(",src)
        init=(OVERLAY/"etc/init.d/8311-tls-key-permissions").read_text()
        self.assertIn("START=51",init)
        self.assertIn("/usr/libexec/8311-tls-key-permissions",init)

    def test_candidate_generator_never_installs_or_reloads_https(self):
        src=(LUA/"8311/tls_candidate.lua").read_text()
        self.assertIn('local DIR="/tmp/aott-tls-candidate"',src)
        self.assertIn('"/usr/sbin/px5g","selfsigned","-der"',src)
        self.assertIn('"ec_paramgen_curve:P-256"',src)
        self.assertIn('"rsa:2048"',src)
        self.assertIn("fs.chmod(KEY_NEW,600)",src)
        self.assertIn("install_available=false",src)
        for forbidden in ("/ptconf/","uci:","/etc/init.d/uhttpd","uhttpd reload",
                          "fw_setenv","fwenv_set","ubiupdatevol","reboot"):
            self.assertNotIn(forbidden,src)

    def test_controller_routes_are_https_authenticated_and_no_install(self):
        ctl=(OVERLAY/"usr/lib/lua/luci/controller/8311.lua").read_text()
        self.assertIn('entry({"admin", "8311", "tls"}',ctl)
        self.assertIn('entry({"admin", "8311", "tls_generate"}',ctl)
        self.assertIn('entry({"admin", "8311", "tls_discard"}',ctl)
        self.assertNotIn('"tls_install"',ctl)
        self.assertIn("tls_https_required()",ctl)
        self.assertIn("dispatcher.test_post_security(true)",ctl)
        self.assertIn("active_https_changed=false",ctl)
        self.assertIn("install_available=false",ctl)

    def test_view_states_activation_gate(self):
        view=(OVERLAY/"usr/lib/lua/luci/view/8311/tls.htm").read_text()
        self.assertIn("Inactive self-signed candidate",view)
        self.assertIn("Install/activate is intentionally unavailable",view)
        self.assertIn("HTTPS remains unchanged",view)
        self.assertNotIn("private key contents",view.lower())

    def test_vendor_px5g_offline_generator_still_qualifies(self):
        if not VENDOR.is_dir() or not shutil.which("qemu-mips-static"):
            self.skipTest("Vendor rootfs/QEMU unavailable")
        sys.path.insert(0,str(ROOT/"tools"))
        import s010_offline_vendor_tls as s010
        binary=VENDOR/"usr/sbin/px5g"
        self.assertTrue(binary.is_file())
        dns=["onu.example.test"]
        argv=s010.px5g_argv(binary,Path("/tmp/c.crt"),Path("/tmp/c.key"),
                            dns=dns,ips=(),days=365,key_type="ec-p256")
        self.assertIn("-addext",argv)
        self.assertIn("subjectAltName=DNS:onu.example.test",argv)
        self.assertIn("ec_paramgen_curve:P-256",argv)

if __name__=="__main__":
    unittest.main()
