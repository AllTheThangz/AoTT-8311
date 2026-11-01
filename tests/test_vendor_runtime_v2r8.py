"""Optional offline vendor-runtime compatibility tests for v2r8.

Point AOTT_VENDOR_ROOTFS at a privately authorized, extracted PRX126 rootfs.
The public CI intentionally does not include proprietary firmware objects.
All fixtures are synthetic. Nothing contacts, flashes or reboots an ONU.
"""
import os
from pathlib import Path
import shutil
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]
VENDOR = Path(os.getenv("AOTT_VENDOR_ROOTFS", "/nonexistent/vendor/rootfs"))
MONITOR = ROOT / "overlay/usr/lib/lua/8311/monitoring.lua"


class VendorMonitoringIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        required = os.getenv("AOTT_VENDOR_ROOTFS") is not None
        files = (
            "usr/lib/lua/luci/model/uci.lua",
            "usr/lib/lua/luci/sgi/uhttpd.lua",
            "usr/bin/lua",
        )
        if not all((VENDOR / path).is_file() for path in files):
            if required:
                raise AssertionError("Explicit vendor rootfs is missing required runtime inputs")
            raise unittest.SkipTest("Compatible private vendor rootfs was not supplied")

    def command(self, args):
        result = subprocess.run(args, cwd=ROOT, capture_output=True,
                                text=True, timeout=20, check=False)
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        return result.stdout

    def test_actual_vendor_uci_lua_on_host(self):
        if not shutil.which("lua5.1"):
            self.skipTest("Host Lua 5.1 unavailable")
        out = self.command([
            "lua5.1", str(ROOT / "tests/vendor_uci_monitoring_fixture.lua"),
            str(VENDOR / "usr/lib/lua/luci/model/uci.lua"), str(MONITOR)])
        self.assertIn("VENDOR_LUCI_UCI_MONITORING_OFFLINE_PASS", out)

    def test_actual_vendor_uhttpd_lua_on_host(self):
        if not shutil.which("lua5.1"):
            self.skipTest("Host Lua 5.1 unavailable")
        out = self.command([
            "lua5.1", str(ROOT / "tests/vendor_uhttpd_metrics_fixture.lua"),
            str(VENDOR / "usr/lib/lua/luci/sgi/uhttpd.lua")])
        self.assertIn("VENDOR_UHTTPD_ENVIRONMENT_OFFLINE_PASS", out)

    def target(self, script, vendor_file, extra=()):
        if not shutil.which("qemu-mips-static"):
            self.skipTest("Target MIPS user-mode emulator unavailable")
        if not (VENDOR / "usr/bin/lua").is_file():
            self.skipTest("Vendor MIPS Lua interpreter unavailable")
        return self.command([
            "qemu-mips-static", "-L", str(VENDOR), str(VENDOR / "usr/bin/lua"),
            str(ROOT / script), str(VENDOR / vendor_file),
            *[str(a) for a in extra]])

    def test_actual_vendor_uci_lua_in_mips_qemu(self):
        out = self.target("tests/vendor_uci_monitoring_fixture.lua",
                          "usr/lib/lua/luci/model/uci.lua", (MONITOR,))
        self.assertIn("VENDOR_LUCI_UCI_MONITORING_OFFLINE_PASS", out)

    def test_actual_vendor_uhttpd_lua_in_mips_qemu(self):
        out = self.target("tests/vendor_uhttpd_metrics_fixture.lua",
                          "usr/lib/lua/luci/sgi/uhttpd.lua")
        self.assertIn("VENDOR_UHTTPD_ENVIRONMENT_OFFLINE_PASS", out)


if __name__ == "__main__":
    unittest.main()
