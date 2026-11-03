"""C-012 full-schema save-contract tests, using synthetic values only.

The real Lua 5.1 controller is loaded with mock native dependencies, and the
same isolated fixture optionally runs on the offline vendor MIPS Lua runtime.
These tests never access a live ONU, firmware environment, UCI or network.
They prove source validation and simulated persistence, not hardware effect.
"""
import os
from pathlib import Path
import shutil
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests/c012_config_contract_fixture.lua"
CONFIG = ROOT / "overlay/usr/lib/lua/8311/config.lua"
CONTROLLER = ROOT / "overlay/usr/lib/lua/luci/controller/8311.lua"
VENDOR = Path(os.environ.get("AOTT_VENDOR_ROOTFS",
                             "/offline-vendor-rootfs-unavailable"))


class C012ConfigurationContractTests(unittest.TestCase):
    def run_fixture(self, argv):
        result = subprocess.run(
            argv + [str(FIXTURE), str(CONFIG), str(CONTROLLER)],
            capture_output=True, text=True, timeout=35, check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("54 fields, 54 positive writes, 5 sensitive fields",
                      result.stdout)
        self.assertIn("failure/guard cases PASS", result.stdout)

    def test_native_lua_full_real_schema_and_mock_writer(self):
        if not shutil.which("lua5.1"):
            self.skipTest("Lua 5.1 is not installed")
        self.run_fixture(["lua5.1"])

    def test_offline_vendor_mips_lua_full_real_schema(self):
        if not os.environ.get("AOTT_VENDOR_ROOTFS"):
            self.skipTest("Offline vendor rootfs was not supplied")
        native = VENDOR / "usr/bin/lua"
        self.assertTrue(native.is_file(), "Vendor MIPS Lua missing")
        self.run_fixture(["qemu-mips-static", "-L", str(VENDOR),
                          str(native)])

    def test_fixture_loads_real_schema_without_embedded_customer_values(self):
        script = FIXTURE.read_text()
        self.assertIn("controller.fwenvs_8311", script)
        self.assertIn("config.prepare(snap,form_good)", script)
        self.assertIn("config.apply(snap,planned)", script)
        self.assertIn("fwenv_read_all=function()", script)
        self.assertIn("fw_setenv=setter(", script)
        self.assertNotIn("os.execute(", script)
        self.assertNotIn("io.popen(", script)
        self.assertNotIn("socket.", script)

    def test_actual_backend_and_controller_compile(self):
        if not shutil.which("luac5.1"):
            self.skipTest("Lua compiler is not installed")
        for path in (CONFIG, CONTROLLER, FIXTURE):
            with self.subTest(path=path.name):
                result = subprocess.run(
                    ["luac5.1", "-p", str(path)],
                    capture_output=True, text=True, timeout=10,
                )
                self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
