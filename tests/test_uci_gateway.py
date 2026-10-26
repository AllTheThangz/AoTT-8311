"""Sandbox the UCI-defaults routing block with mocked device primitives.

No running OpenWrt host or network configuration is read or modified.
"""
from pathlib import Path
import os
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parent.parent
UCI_DEFAULTS = ROOT / "overlay/etc/uci-defaults/zzz-8311"

class UciGatewayDefaultsTest(unittest.TestCase):
    def run_fixture(self,vlan,gateway):
        source=UCI_DEFAULTS.read_text()
        self.assertIn('uci set "network.lct.auto"', source)
        # Stop before host interface defaults, which are irrelevant here.
        first=source.split('uci set "network.lct.auto"',1)[0]
        stubs=r'''
_lib_8311() { :; }
uci() {
    if [ "$1" = get ]; then
        printf '%s\n' mock-interface
        return 0
    fi
    printf '%s\n' "$*" >> "$TEST_ACTION_LOG"
}
get_8311_lct_mac() { printf '%s\n' MOCK-MAC; }
get_8311_dns_server() { :; }
get_8311_lct_vlan() { printf '%s\n' "$TEST_VLAN"; }
get_8311_ipaddr() { printf '%s\n' 192.0.2.10; }
get_8311_netmask() { printf '%s\n' 255.255.255.0; }
get_8311_gateway() { printf '%s\n' "$TEST_GATEWAY"; }
'''
        with tempfile.TemporaryDirectory() as directory:
            log=Path(directory)/"commands"
            log.write_text("")
            env={**os.environ,"TEST_VLAN":str(vlan),"TEST_GATEWAY":gateway,
                 "TEST_ACTION_LOG":str(log)}
            p=subprocess.run(["/bin/sh","-c",stubs+"\n"+first+"\ntrue\n"],env=env,
                             capture_output=True,text=True,timeout=5)
            self.assertEqual(p.returncode,0,p.stderr)
            return log.read_text()

    def test_untagged_without_gateway_removes_stale_route(self):
        commands=self.run_fixture(0,"")
        self.assertIn("-q delete network.lct.gateway",commands)
        self.assertNotIn("set network.lct.gateway=",commands)

    def test_untagged_with_gateway_sets_next_hop(self):
        commands=self.run_fixture(0,"192.0.2.1")
        self.assertIn("set network.lct.gateway=192.0.2.1",commands)
        self.assertNotIn("-q delete network.lct.gateway",commands)

    def test_tagged_without_gateway_removes_stale_route(self):
        commands=self.run_fixture(100,"")
        self.assertIn("-q delete network.mgmt.gateway",commands)
        self.assertNotIn("set network.mgmt.gateway=",commands)

    def test_tagged_with_gateway_sets_next_hop(self):
        commands=self.run_fixture(100,"192.0.2.1")
        self.assertIn("set network.mgmt.gateway=192.0.2.1",commands)
        self.assertNotIn("-q delete network.mgmt.gateway",commands)

if __name__=="__main__":
    unittest.main()
