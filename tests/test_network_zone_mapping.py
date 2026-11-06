"""Offline-only firewall mapping diagnostics, no device or network traffic."""
import importlib.util
from pathlib import Path
import unittest

ROOT=Path(__file__).resolve().parents[1]
source=ROOT/"tools/audit_network_zone_mapping.py"
spec=importlib.util.spec_from_file_location("aott_zone_audit",source)
mod=importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

NETWORK="network.loopback=interface\nnetwork.lct=interface\nnetwork.iphost1=interface\n"
WAN_REJECT=(
    "firewall.@defaults[0].input='ACCEPT'\n"
    "firewall.@zone[0].name='lan'\n"
    "firewall.@zone[0].network='lct'\n"
    "firewall.@zone[0].input='ACCEPT'\n"
    "firewall.@zone[1].name='wan'\n"
    "firewall.@zone[1].network='wan' 'wan6'\n"
    "firewall.@zone[1].input='REJECT'\n"
)
UNMAPPED_PLAN=(
    'iptables -t filter -A INPUT -i mgmt -j zone_lan_input\n'
    'iptables -t filter -A zone_wan_input -j zone_wan_src_REJECT\n'
)
BOUND_PLAN=(
    'iptables -t filter -A INPUT -i uplink -j zone_wan_input\n'
    'iptables -t filter -A INPUT -i mgmt -j zone_lan_input\n'
)

class ZoneMappingTests(unittest.TestCase):
    def test_unbound_wan_zone_is_rejected_not_declared_wan_safe(self):
        result=mod.assess(NETWORK,WAN_REJECT,UNMAPPED_PLAN)
        self.assertEqual(result["status"],"CONFIGURATION_REVIEW_REQUIRED")
        self.assertTrue(result["global_default_input_accept"])
        self.assertTrue(result["wan_input_reject_configured"])
        self.assertEqual(result["wan_zone_interface_references_unresolved"],2)
        self.assertEqual(result["wan_zone_interface_references_defined"],0)
        self.assertTrue(result["wan_zone_has_no_defined_interfaces"])
        self.assertFalse(result["generated_ipv4_wan_input_jump_present"])
        self.assertFalse(result["kernel_rules_readback_verified"])
        self.assertFalse(result["external_exposure_tested"])
        self.assertFalse(result["live_device_modified"])

    def test_defined_wan_interfaces_with_matching_plan_are_only_config_consistent(self):
        networks=NETWORK+"network.wan=interface\nnetwork.wan6=interface\n"
        result=mod.assess(networks,WAN_REJECT,BOUND_PLAN)
        self.assertEqual(result["status"],"CONFIGURATION_CONSISTENT_KERNEL_UNVERIFIED")
        self.assertTrue(result["generated_ipv4_wan_input_jump_present"])
        self.assertEqual(result["wan_zone_interface_references_unresolved"],0)
        self.assertFalse(result["kernel_rules_readback_verified"])

    def test_missing_plan_does_not_claim_kernel_readback(self):
        networks=NETWORK+"network.wan=interface\nnetwork.wan6=interface\n"
        result=mod.assess(networks,WAN_REJECT)
        self.assertEqual(result["status"],"CONFIGURATION_CONSISTENT_KERNEL_UNVERIFIED")
        self.assertIsNone(result["generated_ipv4_wan_input_jump_present"])

    def test_invalid_missing_or_multiple_zone_metadata_fails_closed(self):
        bad=[
            ("",WAN_REJECT),
            (NETWORK,""),
            (NETWORK,WAN_REJECT.replace("firewall.@defaults[0].input='ACCEPT'\n","")),
            (NETWORK,WAN_REJECT+"firewall.@defaults[1].input='REJECT'\n"),
            (NETWORK,WAN_REJECT.replace("firewall.@zone[1].name='wan'",
                                         "firewall.@zone[1].name='lan'")),
            (NETWORK,WAN_REJECT+"firewall.@zone[2].name='wan'\n"),
        ]
        for network,firewall in bad:
            with self.subTest(name=repr(firewall[:70])):
                with self.assertRaises(ValueError):
                    mod.assess(network,firewall)

    def test_accept_policy_or_no_fw3_hook_requires_review(self):
        networks=NETWORK+"network.wan=interface\nnetwork.wan6=interface\n"
        accept=WAN_REJECT.replace(
            "firewall.@zone[1].input='REJECT'",
            "firewall.@zone[1].input='ACCEPT'")
        self.assertEqual(mod.assess(networks,accept,BOUND_PLAN)["status"],
                         "CONFIGURATION_REVIEW_REQUIRED")
        self.assertEqual(mod.assess(networks,WAN_REJECT,UNMAPPED_PLAN)["status"],
                         "CONFIGURATION_REVIEW_REQUIRED")

if __name__=="__main__":
    unittest.main()
