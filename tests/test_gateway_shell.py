"""Offline sh / UCI-defaults regression checks; never touch a real ONU."""
from pathlib import Path
import os
import re
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parent.parent
LIB = ROOT / "overlay/lib/8311.sh"
UCI_DEFAULTS = ROOT / "overlay/etc/uci-defaults/zzz-8311"
NET_INIT = ROOT / "overlay/etc/init.d/_8311-netinit.sh"

class ManagementGatewayShellTest(unittest.TestCase):
    def run_getter(self, saved=None, own_address="192.0.2.10"):
        text = LIB.read_text()
        match = re.search(r"^get_8311_gateway\(\) \{\n.*?^\}", text, re.M | re.S)
        self.assertIsNotNone(match, "Gateway getter source function missing")
        getter = match.group(0)
        with tempfile.TemporaryDirectory() as directory:
            cache = Path(directory) / "gateway-cache"
            original = "/tmp/8311-gateway"
            self.assertGreaterEqual(getter.count(original), 2)
            getter = getter.replace(original, str(cache))
            script = r'''
fwenv_get_8311() {
    [ "$1" = gateway ] || return 1
    [ "$TEST_PRESENT" = 1 ] || return 1
    printf '%s\n' "$TEST_VALUE"
}
get_8311_ipaddr() { printf '%s\n' "$TEST_SELF"; }
ipv4() {
    IFS= read -r v || [ -n "$v" ]
    case "$v" in ""|*[!0-9.]*) return 1 ;; esac
    printf '%s\n' "$v"
}
'''
            script += getter + "\nget_8311_gateway\n"
            env = {**os.environ, "TEST_PRESENT":"1" if saved is not None else "0",
                   "TEST_VALUE":saved or "", "TEST_SELF":own_address}
            p = subprocess.run(["/bin/sh", "-c", script], env=env, capture_output=True,
                               text=True, timeout=5)
            self.assertEqual(p.returncode, 0, p.stderr)
            self.assertEqual(p.stderr, "")
            return p.stdout

    def test_unset_has_no_default_route(self):
        self.assertEqual(self.run_getter(None), "")

    def test_legacy_self_gateway_has_no_default_route(self):
        self.assertEqual(self.run_getter("192.0.2.10"), "")

    def test_real_router_gateway_is_preserved(self):
        self.assertEqual(self.run_getter("192.0.2.1"), "192.0.2.1\n")

    def test_invalid_gateway_fails_closed(self):
        self.assertEqual(self.run_getter("invalid.invalid"), "")

    def test_default_scripts_delete_stale_routes(self):
        text = UCI_DEFAULTS.read_text()
        self.assertIn('uci -q delete "network.mgmt.gateway"', text)
        self.assertIn('uci -q delete "network.lct.gateway"', text)
        self.assertIn('uci set "network.mgmt.gateway"="$LCT_GATEWAY"', text)
        self.assertIn('uci set "network.lct.gateway"="$LCT_GATEWAY"', text)
        self.assertNotIn('uci set "network.lct.gateway"="$(get_8311_gateway)"', text)
        self.assertNotIn('uci set "network.mgmt.gateway"="$(get_8311_gateway)"', text)

    def test_netinit_skips_unset_gateway(self):
        text = NET_INIT.read_text()
        self.assertIn('[ -n "$LCT_GATEWAY" ] && set_8311_gateway "$LCT_GATEWAY"', text)

if __name__ == "__main__":
    unittest.main()
