"""Cross-check the real gateway getter and UCI setup as a single startup path.

Runs against a local BusyBox MIPS binary under qemu when supplied through
AOTT_TEST_MIPS_ROOTFS. Falls back to the host sh for source CI.
No network, firmware, or device access is needed.
"""
from pathlib import Path
import os
import re
import subprocess
import tempfile
import unittest

ROOT=Path(__file__).resolve().parent.parent
LIB=ROOT/"overlay/lib/8311.sh"
UCI=ROOT/"overlay/etc/uci-defaults/zzz-8311"

class GatewayBootPathTests(unittest.TestCase):
    def simulate(self, vlan, gateway):
        content=LIB.read_text()
        match=re.search(r"^get_8311_gateway\(\) \{\n.*?^\}",content,re.S|re.M)
        self.assertIsNotNone(match)
        with tempfile.TemporaryDirectory() as tmp:
            # No access to the real device or firmware settings.
            getter=match.group(0).replace("/tmp/8311-gateway",tmp+"/gateway.cache")
            setup=UCI.read_text().split('uci set "network.lct.auto"',1)[0]
            shell=r"""
_lib_8311() { :; }
uci() {
    if [ "$1" = get ]; then echo eth0_0_1_lct; return 0; fi
    printf "%s\n" "$*" >> "$AOTT_ACTIONS"
}
fwenv_get_8311() { [ "$1" = gateway ] && printf "%s\n" "$AOTT_GATEWAY"; }
ipv4() { cat; }
get_8311_ipaddr() { echo 192.0.2.10; }
get_8311_netmask() { echo 255.255.255.0; }
get_8311_lct_mac() { echo MOCK; }
get_8311_dns_server() { :; }
get_8311_lct_vlan() { echo "$AOTT_VLAN"; }
"""
            with open(tmp+"/actions","w") as f: pass
            env={**os.environ,"AOTT_GATEWAY":gateway,"AOTT_VLAN":str(vlan),
                 "AOTT_ACTIONS":tmp+"/actions"}
            rootfs=os.environ.get("AOTT_TEST_MIPS_ROOTFS")
            if rootfs:
                runner=["qemu-mips-static","-L",rootfs,rootfs+"/bin/busybox","ash","-c"]
            else:
                runner=["/bin/sh","-c"]
            result=subprocess.run(runner+[shell+getter+"\n"+setup+"\ntrue"],
                                  text=True,capture_output=True,env=env,timeout=10)
            self.assertEqual(result.returncode,0,result.stderr)
            return Path(tmp+"/actions").read_text()

    def test_legacy_self_gateway_retained_for_untagged_and_tagged(self):
        for vlan,interface in ((0,"lct"),(100,"mgmt")):
            with self.subTest(vlan=vlan):
                output=self.simulate(vlan,"192.0.2.10")
                self.assertIn("set network.%s.gateway=192.0.2.10"%interface,output)
                self.assertNotIn("-q delete network.%s.gateway"%interface,output)

    def test_unset_gateway_is_explicitly_removed(self):
        for vlan,interface in ((0,"lct"),(100,"mgmt")):
            with self.subTest(vlan=vlan):
                output=self.simulate(vlan,"")
                self.assertIn("-q delete network.%s.gateway"%interface,output)

    def test_true_router_gateway_is_preserved(self):
        for vlan,interface in ((0,"lct"),(100,"mgmt")):
            with self.subTest(vlan=vlan):
                output=self.simulate(vlan,"192.0.2.1")
                self.assertIn("set network.%s.gateway=192.0.2.1"%interface,output)

if __name__=="__main__":
    unittest.main()
