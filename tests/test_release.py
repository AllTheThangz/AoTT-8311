"""Negative secret-sanitization and safe offline overlay tests."""
import importlib.util
import json
import pathlib
import shutil
import tempfile
import unittest

ROOT=pathlib.Path(__file__).resolve().parent.parent
SPEC=importlib.util.spec_from_file_location("release_audit",ROOT/"tools/verify_release.py")
verify=importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(verify)
STAGE_SPEC=importlib.util.spec_from_file_location("stage_module",ROOT/"tools/install_overlay.py")
stage_module=importlib.util.module_from_spec(STAGE_SPEC)
STAGE_SPEC.loader.exec_module(stage_module)

class SourceReleaseTest(unittest.TestCase):
    def test_source_clean(self):
        count,failures=verify.check(ROOT)
        self.assertGreater(count,60)
        self.assertEqual(failures,[])

    def test_full_manifest_matches(self):
        m=json.loads((ROOT/"MANIFEST.json").read_text())
        self.assertEqual(m["release"],"AoTT-8311-v2r3")
        self.assertTrue(m["source_only"])
        self.assertFalse(m["firmware_binaries_included"])
        self.assertGreaterEqual(len(m["overlay_files"]),60)

    def test_fake_github_token_detected(self):
        token="gh"+"p_"+"x"*38
        self.assertIn("GitHub token",verify.inspect_text("test.txt",token))

    def test_fake_openai_token_detected(self):
        token="s"+"k-"+"Z"*36
        self.assertIn("OpenAI style token",verify.inspect_text("test.txt",token))

    def test_crypt_hash_detected(self):
        secret="$"+"6"+"$"+"fakeSALT"+"$"+"A"*43
        self.assertIn("password hash",verify.inspect_text("test.txt",secret))

    def test_factory_placeholder_allowed(self):
        text="DEFAULT_PASSWORD=__REQUIRE_UNIQUE_PASSWORD_BEFORE_FLASH__"
        self.assertEqual(verify.inspect_text("test.txt",text),[])

    def test_hardcoded_factory_password_detected(self):
        self.assertIn("non-placeholder factory credential",
                      verify.inspect_text("test.txt","DEFAULT_PASSWORD="+"Insecure"+"Example777"))

    def test_real_private_ip_detected(self):
        ipv4="192"+".168"+".1"+".2"
        self.assertIn("unapproved embedded IPv4 address",
                      verify.inspect_text("test.txt","endpoint="+ipv4))

    def test_safe_factory_ip(self):
        self.assertEqual(verify.inspect_text("example.txt","DEFAULT_MGMT_IP=192.168.11.1"),[])

    def test_key_material_detected(self):
        key="-----BEGIN "+"OPENSSH PRIVATE KEY"+"-----"
        self.assertIn("private key",verify.inspect_text("test.txt",key))

    def test_mac_address_detected(self):
        mac="a2"+":1b"+":2c"+":3d"+":4e"+":5f"
        self.assertIn("literal hardware MAC address",
                      verify.inspect_text("test.txt",mac))

    def test_tampered_executable_mode_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            sandbox = pathlib.Path(tmp)/"release"
            shutil.copytree(ROOT,sandbox,ignore=shutil.ignore_patterns(".git","__pycache__"))
            target=sandbox/"overlay/usr/sbin/8311-bankctl.sh"
            target.chmod(0o644)
            _,findings=verify.check(sandbox)
            self.assertIn("overlay manifest executable-mode mismatch",
                          [issue for _,issue in findings])

    def test_tampered_size_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            sandbox = pathlib.Path(tmp)/"release"
            shutil.copytree(ROOT,sandbox,ignore=shutil.ignore_patterns(".git","__pycache__"))
            target=sandbox/"overlay/usr/sbin/8311-bankctl.sh"
            with target.open("ab") as stream:
                stream.write(b"\\n")
            _,findings=verify.check(sandbox)
            self.assertIn("overlay manifest size mismatch",
                          [issue for _,issue in findings])

    def test_offline_install_into_new_directory(self):
        with tempfile.TemporaryDirectory() as base:
            dst=pathlib.Path(base)/"staged-firmware-overlay"
            stage_module.stage(dst,ROOT)
            manifest=json.loads((ROOT/"MANIFEST.json").read_text())
            self.assertEqual(len(list(p for p in dst.rglob("*") if p.is_file())),
                             len(manifest["overlay_files"]))
            with self.assertRaises(ValueError):
                stage_module.stage(dst,ROOT)

if __name__=="__main__":
    unittest.main()
