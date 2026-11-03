"""H-010/H-011 source-only exact-counter model and bounded RAM sampler.

Mock input only. Never connects to any real ONU or starts resident services.
"""
from pathlib import Path
import json
import os
import shutil
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "prototypes/history/8311"
MODEL = SOURCE / "history_model.lua"
SAMPLER = SOURCE / "history_sampler.lua"
MODEL_FIXTURE = ROOT / "tests/history_model_fixture.lua"
SAMPLER_FIXTURE = ROOT / "tests/history_sampler_fixture.lua"
VENDOR = Path(os.environ.get("AOTT_VENDOR_ROOTFS",
                             "/offline-vendor-rootfs-unavailable"))


class H011InMemorySamplerTests(unittest.TestCase):
    def check_fixture(self, runtime, fixture, args, marker):
        result = subprocess.run(runtime + [str(fixture), *args],
                                capture_output=True, text=True, timeout=35)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(marker, result.stdout)

    def test_host_exact_u64_history_model(self):
        if not shutil.which("lua5.1"):
            self.skipTest("Lua 5.1 not installed")
        self.check_fixture(["lua5.1"], MODEL_FIXTURE, [str(MODEL)],
                           "AOTT_VNEXT_PORTABLE_HISTORY_MODEL_FIXTURE_PASS checks=53")

    def test_host_bounded_sampler_checks(self):
        if not shutil.which("lua5.1"):
            self.skipTest("Lua 5.1 not installed")
        self.check_fixture(["lua5.1"], SAMPLER_FIXTURE, [str(SOURCE.parent)],
                           "AOTT_H011_RAM_SAMPLER_FIXTURE_PASS checks=1076")

    def test_optional_vendor_mips_lua_checks(self):
        if not os.environ.get("AOTT_VENDOR_ROOTFS"):
            self.skipTest("Offline vendor MIPS rootfs not supplied")
        native = VENDOR / "usr/bin/lua"
        self.assertTrue(native.is_file(), "Real vendor Lua unavailable")
        self.assertIsNotNone(shutil.which("qemu-mips-static"))
        runtime = ["qemu-mips-static", "-L", str(VENDOR), str(native)]
        self.check_fixture(runtime, MODEL_FIXTURE, [str(MODEL)],
                           "AOTT_VNEXT_PORTABLE_HISTORY_MODEL_FIXTURE_PASS checks=53")
        self.check_fixture(runtime, SAMPLER_FIXTURE, [str(SOURCE.parent)],
                           "AOTT_H011_RAM_SAMPLER_FIXTURE_PASS checks=1076")

    def test_lua_51_parses(self):
        if not shutil.which("luac5.1"):
            self.skipTest("Lua 5.1 compiler not installed")
        for path in (MODEL, SAMPLER, MODEL_FIXTURE, SAMPLER_FIXTURE):
            with self.subTest(path=path.name):
                result = subprocess.run(["luac5.1", "-p", str(path)],
                                        capture_output=True, text=True, timeout=10)
                self.assertEqual(result.returncode, 0, result.stderr)

    def test_ram_only_pure_source_without_implicit_background_service(self):
        source = SAMPLER.read_text()
        self.assertIn('require "8311.history_model"', source)
        self.assertIn("MAX_SAMPLES = 120, 720", source)
        self.assertIn("MAX_EVENTS = 128, 256", source)
        self.assertIn("observation_unavailable", source)
        self.assertIn("nonmonotonic_observation", source)
        self.assertIn("sampling_gap", source)
        self.assertIn("walltime_trust=\"unknown\"", source)
        for forbidden in ("os.execute", "io.open", "io.popen", "nixio.fs",
                          "fwenv_set", "uci:commit", "socket.", "http.",
                          "/proc/", "/dev/", "reboot(", "sleep(",
                          "gpon_sn=sample", "loid=sample", "password=sample"):
            self.assertNotIn(forbidden, source)

    def test_prototype_excluded_from_release_manifest_and_firmware(self):
        manifest = json.loads((ROOT / "MANIFEST.json").read_text())
        self.assertTrue(manifest["source_only"])
        self.assertFalse(manifest["firmware_binaries_included"])
        entries = {row["path"] for row in manifest["overlay_files"]}
        for name in ("history_model.lua", "history_sampler.lua"):
            self.assertTrue((SOURCE / name).is_file())
            self.assertNotIn("usr/lib/lua/8311/" + name, entries)
            self.assertFalse((ROOT / "overlay/usr/lib/lua/8311" / name).exists())


if __name__ == "__main__":
    unittest.main()
