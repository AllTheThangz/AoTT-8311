"""H-011 one-shot native reader, strictly synthetic on host and vendor MIPS.

No test calls the running ONU. The mock provider refuses any path or command
outside the fixed read-only whitelist. No firmware overlay changes are required.
"""
import os
from pathlib import Path
import shutil
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]
PROTOTYPE = ROOT / "prototypes/history"
OVERLAY_LUA = ROOT / "overlay/usr/lib/lua"
MODULE = PROTOTYPE / "8311/history_native_probe.lua"
FIXTURE = ROOT / "tests/history_native_probe_fixture.lua"
VENDOR = Path(os.environ.get("AOTT_VENDOR_ROOTFS",
                             "/unavailable/offline-vendor-rootfs"))


class OneShotNativeSourceTests(unittest.TestCase):
    def run_fixture(self, args):
        cmd = args + [str(FIXTURE), str(PROTOTYPE), str(OVERLAY_LUA)]
        result = subprocess.run(cmd, capture_output=True, text=True,
                                timeout=30, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("AOTT_H011_NATIVE_ONE_SHOT_FIXTURE_PASS checks=211",
                      result.stdout)

    def test_host_lua_source_fixture(self):
        if not shutil.which("lua5.1"):
            self.skipTest("Host Lua 5.1 unavailable")
        self.run_fixture(["lua5.1"])

    def test_vendor_mips_runtime_fixture(self):
        if not os.environ.get("AOTT_VENDOR_ROOTFS"):
            self.skipTest("No offline vendor MIPS rootfs supplied")
        self.assertIsNotNone(shutil.which("qemu-mips-static"))
        native = VENDOR / "usr/bin/lua"
        self.assertTrue(native.is_file())
        self.run_fixture(["qemu-mips-static", "-L", str(VENDOR),
                          str(native)])

    def test_lua_51_compilation(self):
        if not shutil.which("luac5.1"):
            self.skipTest("Lua 5.1 compiler unavailable")
        for path in (MODULE, FIXTURE):
            with self.subTest(file=path.name):
                result = subprocess.run(["luac5.1", "-p", str(path)],
                                        capture_output=True, text=True,
                                        timeout=10, check=False)
                self.assertEqual(result.returncode, 0, result.stderr)

    def test_no_firmware_overlay_and_no_automatic_runtime(self):
        self.assertTrue(MODULE.is_file())
        self.assertFalse((ROOT / "overlay/usr/lib/lua/8311/history_native_probe.lua").exists())
        text = (ROOT / "MANIFEST.json").read_text()
        self.assertNotIn("history_native_probe.lua", text)
        self.assertIn('\"source_only\": true', text)
        self.assertIn('\"firmware_binaries_included\": false', text)
        for path in (ROOT / "overlay/etc/init.d", ROOT / "overlay/etc/rc.d"):
            if path.is_dir():
                for file in path.rglob("*"):
                    if file.is_file():
                        self.assertNotIn("history_native_probe", file.read_text(errors="replace"))

    def test_fixed_readonly_command_and_kernel_source_contract(self):
        src = MODULE.read_text()
        for literal in ('"/proc/sys/kernel/random/boot_id"',
                        '"/proc/uptime"', '"/sys/class/net/eth0_0/speed"',
                        '"/usr/bin/timeout","-k","1","3","/usr/bin/pon","psg"',
                        '"/usr/bin/timeout","-k","1","4"',
                        '"/usr/sbin/ethtool","-S","eth0_0"',
                        'require "8311.history_sampler"',
                        'require "8311.effective_pon_state"',
                        'counter_model.counter_delta("0",value)',
                        'boot_changed_during_observation',
                        'observation_window_out_of_bounds',
                        'proves_subscriber_internet = false',
                        'no_device_write = true'):
            with self.subTest(required=literal):
                self.assertIn(literal, src)
        self.assertNotIn('io.open(', src)
        self.assertNotIn('os.execute(', src)
        self.assertNotIn('io.popen(', src)
        self.assertNotIn('"/bin/sh"', src)
        self.assertNotIn('"/bin/bash"', src)
        self.assertNotIn('fwenv_get', src)
        self.assertNotIn('fwenv_set', src)
        self.assertNotIn('uci:set', src)
        self.assertNotIn('uci:commit', src)
        self.assertNotIn('http.post', src)
        self.assertNotIn('socket.', src)

    def test_only_explicit_bounded_invocation_and_sanitized_receipt(self):
        src = MODULE.read_text()
        self.assertIn("function M.read_once(provider)", src)
        self.assertIn("function M.collect_one(state, provider)", src)
        self.assertIn("function M.native_once(state)", src)
        self.assertIn("history.ingest(state, snapshot)", src)
        self.assertIn('type(provider.read) ~= "function"', src)
        self.assertIn('type(provider.run) ~= "function"', src)
        self.assertIn("type(output) ~= \"string\" or #output > maximum", src)
        self.assertIn("return {", src)
        self.assertIn("samples_retained = receipt.samples_retained", src)
        self.assertNotIn("print(", src)
        self.assertNotIn("setInterval", src)
        self.assertNotIn("while true", src)
        executable = "\n".join(line for line in src.splitlines()
                               if not line.lstrip().startswith("--"))
        self.assertNotIn("cron", executable.lower())


if __name__ == "__main__":
    unittest.main()
