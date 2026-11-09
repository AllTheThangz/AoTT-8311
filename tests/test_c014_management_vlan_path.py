"""C-014 characterization of the actual management-VLAN startup block.

Executes repository shell source against a stateful, synthetic UCI adapter.
No network device, firewall service, boot environment or live ONU is used.
Known unsafe transitions are characterized, not called fixed or qualified.
"""
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SELF = Path(__file__).resolve()
DEFAULTS = ROOT / "overlay/etc/uci-defaults/zzz-8311"
LIBRARY = ROOT / "overlay/lib/8311.sh"
SYNTH_IP = ".".join(("192", "0", "2", "10"))
SYNTH_MASK = ".".join(("255", "255", "255", "0"))
SYNTH_MAC = ":".join(("02", "11", "22", "33", "44", "55"))


def mock_uci(args):
    # Only this child-process mode handles UCI calls. It writes exclusively
    # into a separately created test fixture, never /etc/config.
    path = Path(os.environ["C014_FIXTURE_STATE"])
    if (not path.parent.name.startswith("aott-c014-test-") or
            path.parent.parent != Path("/var/tmp") or path.name != "state.json"):
        return 4
    while args and args[0] == "-q":
        args = args[1:]
    if len(args) != 2:
        return 4
    action, operand = args
    state = json.loads(path.read_text())
    key, _, value = operand.partition("=")
    if action == "get":
        if key not in state:
            return 1
        value = state[key]
        print(" ".join(value) if isinstance(value, list) else value)
        return 0
    if action == "set" and key == os.environ.get("C014_FAIL_SET"):
        return 1
    if action == "set":
        state[key] = value
    elif action in ("del", "delete"):
        for name in list(state):
            if name == key or name.startswith(key + "."):
                del state[name]
    elif action == "add_list":
        old = state.get(key, [])
        old = old if isinstance(old, list) else [old]
        if value not in old:
            old.append(value)
        state[key] = old
    elif action == "del_list":
        state[key] = [v for v in state.get(key, []) if v != value]
    elif action != "commit":
        return 4
    path.write_text(json.dumps(state, sort_keys=True))
    return 0


def network_block():
    source = DEFAULTS.read_text()
    begin = source.index("LCT_IFNAME=")
    end = source.index("# Configure LuCI", begin)
    return source[begin:end]


class ManagementVlanCharacterization(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="aott-c014-test-", dir="/var/tmp")
        self.state_path = Path(self.temp.name) / "state.json"
        self.state_path.write_text(json.dumps({
            "network.lct": "interface", "network.lct.ifname": "eth0_0_1_lct",
            "network.lct.proto": "static", "network.lct.ipaddr": SYNTH_IP,
            "network.lct.netmask": SYNTH_MASK,
            "firewall.@zone[0].name": "lan",
            "firewall.@zone[0].network": ["lan", "lct"],
        }))
        self.state_path.chmod(0o600)

    def tearDown(self):
        self.temp.cleanup()

    def run_source(self, vlan, fail_set=""):
        preamble = '''
uci() { "$C014_PYTHON" "$C014_TEST" --uci-stub "$@"; }
get_8311_lct_mac() { printf '%s\\n' "$C014_MAC"; }
get_8311_iphost_mac() { printf '%s\\n' "$C014_MAC"; }
get_8311_gateway() { printf '\\n'; }
get_8311_dns_server() { printf '\\n'; }
get_8311_lct_vlan() { printf '%s\\n' "$C014_VLAN"; }
get_8311_ipaddr() { printf '%s\\n' "$C014_IP"; }
get_8311_netmask() { printf '%s\\n' "$C014_MASK"; }
'''
        env = dict(os.environ, C014_PYTHON=sys.executable, C014_TEST=str(SELF),
            C014_FIXTURE_STATE=str(self.state_path), C014_VLAN=str(vlan),
            C014_IP=SYNTH_IP, C014_MASK=SYNTH_MASK, C014_MAC=SYNTH_MAC,
            C014_FAIL_SET=fail_set)
        result = subprocess.run(["sh"], input=preamble + network_block(),
                                env=env, text=True, capture_output=True, timeout=20)
        return result, json.loads(self.state_path.read_text())

    def test_fresh_untagged_source_keeps_lct_address(self):
        result, state = self.run_source(0)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(state["network.lct.ipaddr"], SYNTH_IP)
        self.assertNotIn("network.mgmt", state)
        self.assertNotIn("network.lct_vlan", state)

    def test_fresh_tagged_source_builds_vlan_and_moves_ip(self):
        result, state = self.run_source(123)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(state["network.lct_vlan.vid"], "123")
        self.assertEqual(state["network.lct_vlan.ifname"], "eth0_0_1_lct")
        self.assertEqual(state["network.mgmt.ipaddr"], SYNTH_IP)
        self.assertNotIn("network.lct.ipaddr", state)
        self.assertIn("mgmt", state["firewall.@zone[0].network"])

    def test_current_tagged_to_untagged_repeat_leaves_stale_interface(self):
        self.run_source(123)
        result, state = self.run_source(0)
        self.assertEqual(result.returncode, 0)
        # Reproduced source gap, not desired safe behavior. Whether a real
        # boot inherits this state depends on the board's persistence path.
        self.assertEqual(state["network.lct.ipaddr"], SYNTH_IP)
        self.assertEqual(state["network.mgmt.ipaddr"], SYNTH_IP)
        self.assertEqual(state["network.lct_vlan.vid"], "123")
        self.assertIn("mgmt", state["firewall.@zone[0].network"])

    def test_current_vlan_write_failure_is_not_propagated(self):
        result, state = self.run_source(123, "network.lct_vlan.vid")
        self.assertEqual(result.returncode, 0)
        self.assertNotIn("network.lct_vlan.vid", state)
        self.assertEqual(state["network.mgmt.ipaddr"], SYNTH_IP)
        self.assertNotIn("network.lct.ipaddr", state)

    def test_current_zone_assignment_uses_position_not_zone_name(self):
        state = json.loads(self.state_path.read_text())
        state["firewall.@zone[0].name"] = "wan"
        state["firewall.@zone[1].name"] = "lan"
        state["firewall.@zone[1].network"] = ["lan", "lct"]
        self.state_path.write_text(json.dumps(state))
        result, state = self.run_source(123)
        self.assertEqual(result.returncode, 0)
        self.assertIn("mgmt", state["firewall.@zone[0].network"])
        self.assertNotIn("mgmt", state["firewall.@zone[1].network"])

    def test_current_vlan_setter_only_logs(self):
        source = LIBRARY.read_text()
        function = re.search(r"(?ms)^set_8311_lct_vlan\(\) \{\n.*?^\}", source).group()
        code = "to_console() { cat; }\n" + function + "\nset_8311_lct_vlan 123\n"
        result = subprocess.run(["sh"], input=code, capture_output=True,
                                text=True, timeout=5)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout.strip(), "Setting LCT VLAN: 123")
        for forbidden in ("uci ", "ip link", "pon ", "ethtool", "fwenv_set"):
            self.assertNotIn(forbidden, function)

    def test_current_invalid_vlan_override_falls_back_to_zero(self):
        function = re.search(r"(?ms)^get_8311_lct_vlan\(\) \{\n.*?^\}",
                             LIBRARY.read_text()).group()
        for value in ("", "not-an-integer", "-1", "4096"):
            with self.subTest(value=value):
                code = "fwenv_get_8311() { printf '%s\\n' " + shlex.quote(value) + "; }\n"
                result = subprocess.run(["sh"], input=code + function + "\nget_8311_lct_vlan\n",
                                        text=True, capture_output=True, timeout=5)
                self.assertEqual(result.returncode, 0)
                self.assertEqual(result.stdout.strip(), "0")

    def test_management_vlan_control_is_exposed_only_through_guarded_transaction(self):
        source = (ROOT / "overlay/usr/lib/lua/luci/controller/8311.lua").read_text()
        active = "\n".join(line for line in source.splitlines()
                           if not line.lstrip().startswith("--"))
        self.assertIn('id="lct_vlan"', active)
        field = active.split('id="lct_vlan"',1)[1].split("},{",1)[0]
        self.assertIn('min=0', field)
        self.assertIn('max=4094', field)
        self.assertIn("timed confirmation", field)
        for route in ("management_apply","management_confirm"):
            self.assertIn(f'"{route}"', active)
        transaction=(ROOT/"overlay/usr/lib/lua/8311/management_transaction.lua").read_text()
        self.assertIn("management_confirmation_timeout",transaction)
        self.assertIn("provider.restore",transaction)
        self.assertIn("runtime.live(request)",transaction)
        self.assertIn("hardware_qualified=false",
            (ROOT/"overlay/usr/lib/lua/8311/management_preflight.lua").read_text())
        # The historical startup script remains characterized here. Production
        # live mutation is not delegated to this non-transactional block.
        self.assertNotIn("ifup", network_block())


if __name__ == "__main__":
    if sys.argv[1:2] == ["--uci-stub"]:
        raise SystemExit(mock_uci(sys.argv[2:]))
    unittest.main()
