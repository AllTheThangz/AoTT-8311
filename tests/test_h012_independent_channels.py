"""H-012 synthetic independent PON and host-link history qualification.

The real RAM sampler is exercised under host Lua 5.1 and, optionally, the
extracted offline MIPS vendor interpreter. No ONU or native command is used.
"""
import os
from pathlib import Path
import shutil
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]
PROTOTYPE = ROOT / "prototypes/history"
SAMPLER = PROTOTYPE / "8311/history_sampler.lua"
FIXTURE = ROOT / "tests/h012_independent_channels_fixture.lua"
VENDOR = Path(os.environ.get("AOTT_VENDOR_ROOTFS",
                             "/missing/offline/vendor-rootfs"))


class IndependentChannelHistoryTests(unittest.TestCase):
    def run_fixture(self, command):
        result = subprocess.run(
            command + [str(FIXTURE), str(PROTOTYPE)],
            cwd=ROOT, capture_output=True, text=True, timeout=25
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("AOTT_H012_INDEPENDENT_CHANNEL_FIXTURE_PASS checks=85",
                      result.stdout)

    def test_host_lua_independent_channels(self):
        if not shutil.which("lua5.1"):
            self.skipTest("Host Lua 5.1 is not installed")
        self.run_fixture(["lua5.1"])

    def test_vendor_mips_lua_independent_channels(self):
        if not os.environ.get("AOTT_VENDOR_ROOTFS"):
            self.skipTest("Offline vendor MIPS rootfs not supplied")
        native = VENDOR / "usr/bin/lua"
        self.assertTrue(native.is_file())
        self.assertIsNotNone(shutil.which("qemu-mips-static"))
        self.run_fixture(["qemu-mips-static", "-L", str(VENDOR),
                          str(native)])

    def test_lua51_syntax(self):
        if not shutil.which("luac5.1"):
            self.skipTest("Lua 5.1 compiler is not installed")
        for path in (SAMPLER, FIXTURE):
            with self.subTest(path=path.name):
                result = subprocess.run(["luac5.1", "-p", str(path)],
                                        capture_output=True, text=True,
                                        timeout=10)
                self.assertEqual(result.returncode, 0, result.stderr)

    def test_independent_validity_and_source_guards(self):
        text = SAMPLER.read_text()
        for required in (
            "pon_previous=nil, host_previous=nil",
            'local valid_pon=current.pon_state~=nil',
            'local valid_host=current.ethernet_mbps~=nil',
            'observe_channel(',
            'state.pon_previous,current.pon_state,"pon_state_change"',
            'state.host_previous,current.ethernet_mbps,"host_link_change"',
            "previous.boot==current.boot",
            "previous.source==current.source",
            "value~=previous.value",
            'emit("observation_unavailable"',
            'pon_observation=valid_pon and "observed" or "unavailable"',
            'host_link_observation=valid_host and "observed" or "unavailable"',
            'state.previous=nil',
        ):
            with self.subTest(required=required):
                self.assertIn(required, text)

    def test_no_background_process_or_live_device_mutation(self):
        source = SAMPLER.read_text()
        self.assertTrue((ROOT / "overlay/usr/lib/lua/8311/history_sampler.lua").is_file())
        self.assertIn("history_sampler.lua",
                      (ROOT / "MANIFEST.json").read_text())
        executable = "\n".join(line for line in source.splitlines()
                               if not line.lstrip().startswith("--"))
        for forbidden in ("os.execute(", "io.open(", "io.popen(", "uci:commit",
                          "fwenv_set", "socket.", "/dev/", "cron(", "reboot(",
                          "sleep(", "http.post", "requests."):
            self.assertNotIn(forbidden, executable)

    def test_fixture_does_not_claim_missing_is_down(self):
        code = FIXTURE.read_text()
        for required in (
            "pon_transition_survives_host_probe_failure",
            "independent_host_link_change",
            "no_fake_pon_recovery_after_pon_missing",
            "missing_host_not_link_down",
            "long_gap_does_not_reconstruct_transitions",
            "source_change_does_not_invent_link_flaps",
            "rejection_preserves_accepted_count",
        ):
            with self.subTest(required=required):
                self.assertIn(required, code)


if __name__ == "__main__":
    unittest.main()
