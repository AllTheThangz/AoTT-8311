"""S-013 remote GUI disabled-by-default preview and rollback tests.

No actual host packet filters, ONUs, network sockets, or ISP settings
are modified. This test suite operates on synthetic policy objects.
"""
import os
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from s013_remote_gui_policy_offline import (
    PolicyError, default_policy, normalize_sources, validate_target,
    validate_request, render_disabled_candidate, qualify_offline,
    simulate_guarded_trial, probe_vendor_fw3, REQUIRED_EVIDENCE,
)

V4 = ".".join(("198", "51", "100", "14"))
V4_NEXT = ".".join(("198", "51", "100", "15"))
V4_PRIVATE = ".".join(("10", "0", "10", "2"))
V6 = "2001:db8::14"
MGMT4 = ".".join(("192", "0", "2", "10"))
MGMT6 = "fd12:3456:789a::10"
VENDOR = Path(os.environ.get("AOTT_VENDOR_ROOTFS",
                            "/missing/offline-vendor-rootfs"))


def request(sources=None, targets=None, **updates):
    value = {
        "explicit_enable": True, "operator_acknowledged": True,
        "https_port": 443,
        "ingress_zone": "wan",
        "sources": sources or {"ipv4": [V4 + "/32"], "ipv6": [V6 + "/128"]},
        "management_targets": targets or {"ipv4": MGMT4, "ipv6": MGMT6},
        "trial_seconds": 120,
    }
    value.update(updates)
    return value


def evidence(sources=None):
    s = sources or request()["sources"]
    data = {key: True for key in REQUIRED_EVIDENCE}
    for family in ("ipv4", "ipv6"):
        if s[family]:
            data["source_family_" + family + "_verified"] = True
        else:
            data["remote_" + family + "_default_denial_verified"] = True
    return data


def outcomes():
    return [
        {"at_second": 3, "source": "trusted_local", "outcome": "connected"},
        {"at_second": 8, "source": "allowlisted_remote", "outcome": "connected"},
        {"at_second": 16, "source": "unlisted_remote", "outcome": "refused"},
        {"at_second": 25, "source": "operator_confirmation", "outcome": "approved"},
    ]


class DefaultAndValidation(unittest.TestCase):
    def test_disabled_by_default(self):
        p = default_policy()
        self.assertFalse(p["remote_gui_enabled"])
        self.assertFalse(p["automatic_activation"])
        self.assertFalse(p["fw3_uci_write"])
        self.assertFalse(p["firewall_service_reload"])
        self.assertTrue(p["no_olt_omci_or_forwarding_mutation"])
        self.assertEqual(p["source_cidrs"], {"ipv4": [], "ipv6": []})
        self.assertEqual(p["https_port"], 443)

    def test_explicit_enable_and_ack_both_required(self):
        for changes in ({"explicit_enable": False},
                        {"operator_acknowledged": False},
                        {"explicit_enable": 1},
                        {"operator_acknowledged": "yes"}):
            with self.subTest(changes=changes), self.assertRaisesRegex(
                PolicyError, "not_explicitly_authorized"):
                validate_request(request(**changes))

    def test_schema_and_unknown_config_keys_rejected(self):
        candidate = request()
        candidate["enable_ssh"] = True
        with self.assertRaisesRegex(PolicyError, "schema_mismatch"):
            validate_request(candidate)

    def test_families_are_explicit_and_nonempty(self):
        for sources in (
            {"ipv4": []},
            {"ipv4": [], "ipv6": []},
            {"ipv4": [V4 + "/32"], "ipv6": "not_list"},
        ):
            with self.subTest(sources=sources), self.assertRaises(PolicyError):
                normalize_sources(sources)

    def test_no_cidr_default_route(self):
        for family, cidr in (
            ("ipv4", ".".join(("0", "0", "0", "0")) + "/0"),
            ("ipv6", "::/0"),
        ):
            v = {"ipv4": [], "ipv6": []}
            v[family] = [cidr]
            with self.subTest(family=family), self.assertRaisesRegex(
                PolicyError, "scope_too_broad"):
                normalize_sources(v)

    def test_no_large_source_networks(self):
        for family, net in (("ipv4", ".".join(("198", "51", "100", "0")) + "/16"),
                            ("ipv6", "2001:db8::/48")):
            v = {"ipv4": [], "ipv6": []}
            v[family] = [net]
            with self.subTest(family=family), self.assertRaises(PolicyError):
                normalize_sources(v)

    def test_source_host_bits_and_ip_mismatch_rejected(self):
        with self.assertRaisesRegex(PolicyError, "source_cidr_invalid"):
            normalize_sources({"ipv4": [V4 + "/24"], "ipv6": []})
        with self.assertRaisesRegex(PolicyError, "source_ip_family_mismatch"):
            normalize_sources({"ipv4": [V6 + "/128"], "ipv6": []})

    def test_duplicate_source_rejected(self):
        with self.assertRaisesRegex(PolicyError, "duplicate_source"):
            normalize_sources({"ipv4": [V4 + "/32"] * 2, "ipv6": []})

    def test_overlapping_networks_rejected(self):
        v = {
            "ipv4": [".".join(("198", "51", "100", "0")) + "/24", V4 + "/32"],
            "ipv6": [],
        }
        with self.assertRaisesRegex(PolicyError, "overlapping"):
            normalize_sources(v)

    def test_source_cidr_omission_and_meta_rejected(self):
        for value in (V4, V4 + "/32;apply", "hostname.example.invalid/32",
                      V4 + "/32\nfoo", "fe80::1%eth0/128"):
            with self.subTest(value=value), self.assertRaises(PolicyError):
                normalize_sources({"ipv4": [value], "ipv6": []})

    def test_non_remote_sources_rejected(self):
        for family, value in (
            ("ipv4", ".".join(("127", "0", "0", "1")) + "/32"),
            ("ipv4", ".".join(("224", "0", "0", "1")) + "/32"),
            ("ipv6", "fe80::1/128"),
            ("ipv6", "ff02::1/128"),
        ):
            v = {"ipv4": [], "ipv6": []}
            v[family] = [value]
            with self.subTest(family=family, value=value), self.assertRaises(
                PolicyError):
                normalize_sources(v)

    def test_exact_approved_sources_canonical(self):
        sources = {"ipv4": [V4_NEXT + "/32", V4 + "/32"],
                   "ipv6": ["2001:0db8::14/128"]}
        result = normalize_sources(sources)
        self.assertEqual(result["ipv4"], [V4 + "/32", V4_NEXT + "/32"])
        self.assertEqual(result["ipv6"], [V6 + "/128"])

    def test_private_vpn_source_allowed_but_needs_other_admission(self):
        # A VPN or reverse-proxy deployment may legitimately present an
        # RFC1918 source address, but this does not prove network origin.
        sources = {"ipv4": [V4_PRIVATE + "/32"], "ipv6": []}
        self.assertEqual(normalize_sources(sources)["ipv4"], [V4_PRIVATE + "/32"])

    def test_custom_https_port_high_allowed_no_http_or_ssh_port(self):
        self.assertEqual(validate_request(request(https_port=8443))["port"], 8443)
        for port in (80, 22, 0, -1, 65536, True, "443"):
            with self.subTest(port=port), self.assertRaisesRegex(
                PolicyError, "https_port_out_of_bounds"):
                validate_request(request(https_port=port))

    def test_rollback_timeout_boundaries(self):
        for seconds in (0, 30, 301, "120", True):
            with self.subTest(seconds=seconds), self.assertRaisesRegex(
                PolicyError, "trial_duration"):
                validate_request(request(trial_seconds=seconds))
        for seconds in (60, 120, 300):
            self.assertEqual(validate_request(request(
                trial_seconds=seconds))["trial_seconds"], seconds)

    def test_zone_not_lan_or_shell_fragment(self):
        for zone in ("lan", "WAN-0; DROP", "", 7, "x" * 30):
            with self.subTest(zone=zone), self.assertRaisesRegex(
                PolicyError, "ingress_zone_not_qualified"):
                validate_request(request(ingress_zone=zone))

    def test_management_target_not_wildcard_loopback_or_linklocal(self):
        for target in ({"ipv4": MGMT4},
                       {"ipv4": MGMT4, "ipv6": "[::1]"},
                       {"ipv4": ".".join(("0", "0", "0", "0")), "ipv6": MGMT6},
                       {"ipv4": MGMT4, "ipv6": "fe80::1"}):
            with self.subTest(target=target), self.assertRaises(PolicyError):
                validate_target(target)

    def test_missing_target_for_requested_family_rejected(self):
        with self.assertRaisesRegex(PolicyError, "missing_management_target"):
            validate_request(request(targets={"ipv4": MGMT4, "ipv6": None}))


class DisabledRulePreview(unittest.TestCase):
    def test_disabled_fw3_source_rules_only_input_no_forward(self):
        result = render_disabled_candidate(request())
        self.assertEqual(result["summary"]["active_rules"], 0)
        self.assertFalse(result["summary"]["enabled"])
        self.assertTrue(result["summary"]["source_only"])
        self.assertTrue(result["summary"]["no_network_write"])
        self.assertEqual(result["summary"]["candidate_rules"], 2)
        for rule in result["rules"]:
            self.assertEqual(rule["enabled"], "0")
            self.assertEqual(rule["proto"], "tcp")
            self.assertEqual(rule["dest_port"], "443")
            self.assertEqual(rule["target"], "ACCEPT")
            self.assertEqual(rule["src"], "wan")
            self.assertNotIn("dest", rule)
            self.assertNotIn("forward", rule)
        text = result["disabled_uci_text"]
        self.assertEqual(text.count("config rule"), 2)
        self.assertEqual(text.count("option enabled '0'"), 2)
        self.assertNotIn("config forwarding", text)
        self.assertNotIn("config redirect", text)
        self.assertNotIn("iptables", text)
        self.assertNotIn("fw3 reload", text)

    def test_v4_only_one_rule_stays_disabled(self):
        sources = {"ipv4": [V4 + "/32"], "ipv6": []}
        result = render_disabled_candidate(request(sources=sources))
        self.assertEqual(result["summary"]["candidate_rules"], 1)
        self.assertEqual(result["rules"][0]["family"], "ipv4")

    def test_remote_ipv6_v6_rule_is_syntactically_scoped(self):
        sources = {"ipv4": [], "ipv6": [V6 + "/128"]}
        result = render_disabled_candidate(request(sources=sources))
        self.assertEqual(result["rules"][0]["family"], "ipv6")
        self.assertEqual(result["rules"][0]["src_ip"], V6 + "/128")
        self.assertEqual(result["rules"][0]["dest_ip"], MGMT6)

    def test_wide_source_never_renders(self):
        sources = {"ipv4": [], "ipv6": ["::/0"]}
        with self.assertRaises(PolicyError):
            render_disabled_candidate(request(sources=sources))


class AdmissionAndRollback(unittest.TestCase):
    def test_full_synthetic_source_admission_is_not_live_approval(self):
        s = request()
        result = qualify_offline(s, evidence(s["sources"]))
        self.assertEqual(result["status"],
                         "SOURCE_TRIAL_PLAN_READY_NOT_DEPLOYED")
        self.assertFalse(result["remote_gui_enabled"])
        self.assertEqual(result["active_rules"], 0)
        self.assertTrue(result["hardware_reachability_unverified"])
        self.assertTrue(result["source_only_not_deployed"])
        self.assertEqual(result["configured_ipv4_sources"], 1)
        self.assertEqual(result["configured_ipv6_sources"], 1)
        self.assertNotIn(V4, str(result))
        self.assertNotIn(MGMT4, str(result))

    def test_missing_guard_blocks(self):
        for field in REQUIRED_EVIDENCE:
            e = evidence()
            del e[field]
            with self.subTest(field=field):
                receipt = qualify_offline(request(), e)
                self.assertEqual(receipt["status"], "SOURCE_BLOCKED")
                self.assertIn(field, receipt["missing_guards"])

    def test_false_guard_blocks(self):
        e = evidence()
        e["independent_alternate_recovery_verified"] = False
        receipt = qualify_offline(request(), e)
        self.assertIn("independent_alternate_recovery_verified",
                      receipt["missing_guards"])

    def test_omitted_v6_remote_default_deny_must_be_verified(self):
        src = {"ipv4": [V4 + "/32"], "ipv6": []}
        e = evidence(src)
        del e["remote_ipv6_default_denial_verified"]
        receipt = qualify_offline(request(sources=src), e)
        self.assertIn("remote_ipv6_default_denial_verified",
                      receipt["missing_guards"])

    def test_omitted_v4_remote_default_deny_must_be_verified(self):
        src = {"ipv4": [], "ipv6": [V6 + "/128"]}
        e = evidence(src)
        del e["remote_ipv4_default_denial_verified"]
        receipt = qualify_offline(request(sources=src), e)
        self.assertIn("remote_ipv4_default_denial_verified",
                      receipt["missing_guards"])

    def test_malformed_evidence_never_enables(self):
        for value in ("verified", True, [], 999, None):
            with self.subTest(value=value):
                result = qualify_offline(request(), value)
                self.assertEqual(result["status"], "SOURCE_BLOCKED")
                self.assertFalse(result["remote_gui_enabled"])

    def test_absent_evidence_never_enables(self):
        result = qualify_offline(request(), None)
        self.assertEqual(result["status"], "SOURCE_BLOCKED")
        self.assertFalse(result["remote_gui_enabled"])

    def test_valid_model_requires_local_remote_and_denial(self):
        result = simulate_guarded_trial(request(), evidence(), outcomes())
        self.assertEqual(result["status"],
                         "SOURCE_TRIAL_VERIFIED_SYNTHETIC_ONLY")
        self.assertFalse(result["rollback_required"])
        self.assertFalse(result["no_live_commit_performed"] is False)
        self.assertTrue(result["real_wan_connectivity_unverified"])

    def test_missing_ack_without_live_trial(self):
        req = request()
        req["operator_acknowledged"] = False
        with self.assertRaises(PolicyError):
            simulate_guarded_trial(req, evidence(), outcomes())

    def test_probe_success_without_final_operator_confirmation_rolls_back(self):
        observed = [row for row in outcomes()
                    if row["source"] != "operator_confirmation"]
        result = simulate_guarded_trial(request(), evidence(), observed)
        self.assertEqual(result["status"], "SOURCE_TRIAL_ROLLBACK_MODEL")
        self.assertTrue(result["rollback_required"])

    def test_early_operator_confirmation_rolls_back(self):
        observed = [
            {"at_second": 1, "source": "operator_confirmation", "outcome": "approved"},
            *outcomes(),
        ]
        result = simulate_guarded_trial(request(), evidence(), observed)
        self.assertEqual(result["reason"], "unexpected_trial_evidence")
        self.assertTrue(result["rollback_required"])

    def test_timeout_model_requires_rollback(self):
        logs = outcomes() + [{"at_second": 121, "source": "trusted_local",
                              "outcome": "connected"}]
        result = simulate_guarded_trial(request(), evidence(), logs)
        self.assertEqual(result["status"], "SOURCE_TRIAL_ROLLBACK_MODEL")
        self.assertTrue(result["rollback_required"])

    def test_missing_local_confirmation_rolls_back(self):
        records = [row for row in outcomes() if row["source"] != "trusted_local"]
        result = simulate_guarded_trial(request(), evidence(), records)
        self.assertTrue(result["rollback_required"])

    def test_missing_negative_remote_probe_rolls_back(self):
        records = [row for row in outcomes() if row["source"] != "unlisted_remote"]
        result = simulate_guarded_trial(request(), evidence(), records)
        self.assertTrue(result["rollback_required"])

    def test_unexpected_unallowlisted_success_rolls_back(self):
        values = outcomes()
        values[-1]["outcome"] = "connected"
        result = simulate_guarded_trial(request(), evidence(), values)
        self.assertTrue(result["rollback_required"])
        self.assertEqual(result["reason"], "unexpected_trial_evidence")

    def test_explicit_negative_fails_full_preflight(self):
        e = evidence()
        e["no_broad_input_accept_override_verified"] = None
        receipt = simulate_guarded_trial(request(), e, outcomes())
        self.assertEqual(receipt["status"], "SOURCE_TRIAL_BLOCKED")
        self.assertFalse(receipt["rollback_required"])

    def test_second_operator_confirmation_refused(self):
        observed = outcomes() + [{
            "at_second": 27, "source": "operator_confirmation", "outcome": "approved"
        }]
        result = simulate_guarded_trial(request(), evidence(), observed)
        self.assertEqual(result["reason"], "unexpected_postconfirmation_activity")
        self.assertTrue(result["rollback_required"])

    def test_invalid_trial_clock_refused(self):
        logs = outcomes()
        logs[1]["at_second"] = 3
        with self.assertRaisesRegex(PolicyError, "trial_clock"):
            simulate_guarded_trial(request(), evidence(), logs)

    def test_invalid_trial_payload_refused(self):
        with self.assertRaisesRegex(PolicyError, "trial_receipt_schema"):
            simulate_guarded_trial(request(), evidence(),
                                   [{"at_second": 1, "source": "trusted_local"}])


class VendorSourceAndInactivity(unittest.TestCase):
    def test_disabled_by_default_local_model(self):
        source = (ROOT / "tools/s013_remote_gui_policy_offline.py").read_text()
        manifest = (ROOT / "MANIFEST.json").read_text()
        deployed = (
            ROOT / "overlay/usr/lib/lua/luci/controller/8311.lua").read_text()
        self.assertNotIn("s013_remote_gui_policy_offline", manifest)
        self.assertNotIn("s013_remote_gui_policy_offline", deployed)
        self.assertNotIn("subprocess.run(", source)
        self.assertNotIn("subprocess.Popen(", source)
        self.assertNotIn("os.system(", source)
        self.assertNotIn("os.exec", source)
        self.assertNotIn("os.replace(", source)
        self.assertNotIn("iptables -A ", source)
        self.assertNotIn("uci commit ", source)

    @unittest.skipUnless(
        os.environ.get("AOTT_VENDOR_ROOTFS") and
        (Path(os.environ.get("AOTT_VENDOR_ROOTFS", "/missing")) /
         "sbin/fw3").is_file(),
        "Offline vendor rootfs not provided",
    )
    def test_extracted_vendor_fw3_and_wan_reject(self):
        result = probe_vendor_fw3(str(Path(os.environ["AOTT_VENDOR_ROOTFS"])))
        self.assertEqual(result["status"], "SOURCE_VENDOR_FW3_PRESENT")
        self.assertTrue(result["wan_input_reject_in_extracted_source"])
        self.assertTrue(result["runtime_filter_rules_unverified"])

    def test_vendor_probe_never_guesses_supported_fw3(self):
        with self.assertRaisesRegex(PolicyError, "offline_rootfs_required"):
            probe_vendor_fw3("/etc")
        with self.assertRaisesRegex(PolicyError, "vendor_fw3_not_found"):
            probe_vendor_fw3("/var/tmp/definitely-not-a-rootfs")


if __name__ == "__main__":
    unittest.main()
