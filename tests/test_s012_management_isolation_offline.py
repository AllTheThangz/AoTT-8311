"""S-012 offline management listener and dual-family exposure contracts.

All addresses and probes are synthetic; no test contacts the ONU,
modifies a firewall, or changes any network interface or certificate.
"""
import ipaddress
import os
from pathlib import Path
import socket
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from s012_management_isolation_offline import (
    IsolationError, assess, parse_endpoint, parse_uhttpd_uci,
    parse_uhttpd_processes, parse_proc_tcp, read_vendor_uhttpd
)

V4 = ".".join(("192", "0", "2", "10"))
V4_EXTRA = ".".join(("192", "0", "2", "11"))
WILDCARD4 = ".".join(("0", "0", "0", "0"))
V6 = "fd12:3456:789a::10"
V6_EXTRA = "fd12:3456:789a::11"
VENDOR = Path(os.environ.get("AOTT_VENDOR_ROOTFS", "/missing/offline-vendor-rootfs"))


def bind_v4(port, value=V4):
    return f"{value}:{port}"


def bind_v6(port, value=V6):
    return f"[{value}]:{port}"


def uci(bindings=None, duplicate=False, extra_section=False):
    if bindings is None:
        bindings = [
            ("http", bind_v4(80)), ("http", bind_v6(80)),
            ("https", bind_v4(443)), ("https", bind_v6(443))
        ]
    lines = ["# synthetic UCI, not a production migration plan",
             "config uhttpd main", "\toption redirect_https 1",
             "\toption rfc1918_filter 1"]
    for protocol, address in bindings:
        lines.append(f"\tlist listen_{protocol} '{address}'")
    if duplicate:
        lines.append(f"\tlist listen_{bindings[0][0]} '{bindings[0][1]}'")
    if extra_section:
        lines += ["config uhttpd secondary",
                  "\tlist listen_https '" + bind_v4(8443, V4_EXTRA) + "'"]
    lines.extend(("config cert defaults", "\toption days 365"))
    return "\n".join(lines) + "\n"


def proc_line(family, address, port, number=0):
    raw = ipaddress.ip_address(address).packed
    local = b"".join(raw[i:i+4][::-1] for i in range(0, len(raw), 4)).hex().upper()
    # Only Linux TCP LISTEN (0A) entries are interpreted.
    return (f"   {number}: {local}:{port:04X} "
            f"{'0' * len(local)}:0000 0A 00000000:00000000 "
            f"00:00000000 00000000 0 0 123456 1 0000000000000000 100 0 0 10 0")


def proc_table(family, endpoints):
    rows = ["sl  local_address rem_address   st tx_queue rx_queue tr tm->when retrnsmt uid timeout inode"]
    for n, (address, port) in enumerate(endpoints):
        rows.append(proc_line(family, address, port, n))
    return "\n".join(rows) + "\n"


def scenario():
    binds = [
        ("http", bind_v4(80)), ("http", bind_v6(80)),
        ("https", bind_v4(443)), ("https", bind_v6(443))
    ]
    configured = uci(binds)
    command = ["/usr/sbin/uhttpd", "-q", "-p", bind_v4(80),
               "-p", bind_v6(80), "-s", bind_v4(443),
               "-s", bind_v6(443)]
    kernel = {
        "ipv4": proc_table("ipv4", [(V4, 80), (V4, 443)]),
        "ipv6": proc_table("ipv6", [(V6, 80), (V6, 443)]),
    }
    ingress = []
    for protocol, family, address, port in parse_uhttpd_uci(configured):
        ingress.append((protocol, family, address, port, "trusted", "connected"))
        ingress.append((protocol, family, address, port, "host_dataplane", "refused"))
        ingress.append((protocol, family, address, port, "upstream_wan", "refused"))
    return dict(
        uci=configured,
        management={"ipv4": [V4], "ipv6": [V6]},
        processes=[command], kernel=kernel, ingress=ingress
    )


class ParseUCIAndRuntimeTests(unittest.TestCase):
    def test_vendor_style_uhttpd_sections_and_fields(self):
        found = parse_uhttpd_uci(uci())
        self.assertEqual(len(found), 4)
        self.assertIn(("https", "ipv4", V4, 443), found)
        self.assertIn(("https", "ipv6", str(ipaddress.ip_address(V6)), 443), found)

    def test_multiple_instances_included_in_risk(self):
        found = parse_uhttpd_uci(uci(extra_section=True))
        self.assertEqual(len(found), 5)
        self.assertIn(("https", "ipv4", V4_EXTRA, 8443), found)

    def test_duplicate_endpoints_refused(self):
        with self.assertRaisesRegex(IsolationError, "duplicate_uhttpd_listener"):
            parse_uhttpd_uci(uci(duplicate=True))

    def test_duplicate_main_sections_refused(self):
        with self.assertRaisesRegex(IsolationError, "duplicate_main"):
            parse_uhttpd_uci(uci() + "config uhttpd main\n")

    def test_bad_uci_listener_record_refused(self):
        with self.assertRaisesRegex(IsolationError, "malformed_uhttpd_listener"):
            parse_uhttpd_uci("config uhttpd main\nlist listen_https\n")

    def test_refuse_unparseable_uci_text(self):
        with self.assertRaisesRegex(IsolationError, "invalid_uci_syntax"):
            parse_uhttpd_uci("config uhttpd main\nlist listen_https 'unterminated\n")

    def test_config_file_size_bound(self):
        with self.assertRaisesRegex(IsolationError, "invalid_uci_input_size"):
            parse_uhttpd_uci("x" * 70000)

    def test_quoted_option_equivalent_to_list(self):
        endpoints = parse_uhttpd_uci(
            "config uhttpd main\n"
            f"option listen_https '{bind_v4(443)} {bind_v6(443)}'\n")
        self.assertEqual(len(endpoints), 2)

    def test_hostname_urls_and_shell_argument_refused(self):
        for value in ("onu.invalid:443", "http://local:443",
                      "host;touch/a:443", ".".join(("127", "0", "0", "1")) + ":0",
                      "[fe80::1%eth0]:443", "[::1]:65536"):
            with self.subTest(value=value), self.assertRaises(IsolationError):
                parse_endpoint(value, "https")

    def test_unbracketed_ipv6_refused(self):
        with self.assertRaisesRegex(IsolationError, "unsupported_listener"):
            parse_endpoint(V6 + ":443", "https")

    def test_actual_uhttpd_args_reconstructed(self):
        self.assertEqual(parse_uhttpd_processes(scenario()["processes"]),
                         parse_uhttpd_uci(uci()))

    def test_process_executable_refused(self):
        a = scenario()["processes"][0]
        with self.assertRaisesRegex(IsolationError, "executable_identity"):
            parse_uhttpd_processes([["/bin/echo", *a[1:]]])

    def test_incomplete_process_argv_refused(self):
        with self.assertRaisesRegex(IsolationError, "missing_listener"):
            parse_uhttpd_processes([["/usr/sbin/uhttpd", "-s"]])

    def test_kernel_tcp4_tcp6_listen_parse(self):
        s = scenario()["kernel"]
        self.assertIn(("ipv4", V4, 443), parse_proc_tcp(s["ipv4"], "ipv4"))
        self.assertIn(("ipv6", str(ipaddress.ip_address(V6)), 443),
                      parse_proc_tcp(s["ipv6"], "ipv6"))

    def test_non_listening_states_not_accepted(self):
        sample = proc_line("ipv4", V4, 443).replace(" 0A ", " 01 ")
        self.assertEqual(parse_proc_tcp(proc_table("ipv4", []) + sample + "\n", "ipv4"),
                         frozenset())

    def test_invalid_kernel_row_is_refused(self):
        with self.assertRaisesRegex(IsolationError, "malformed"):
            parse_proc_tcp(proc_table("ipv4", []) + " 0: NOTHEX:01BB junk 0A\n", "ipv4")


class SourceIsolationDecisionTests(unittest.TestCase):
    def test_both_families_fully_covered_but_not_hardware_qualified(self):
        r = assess(**scenario())
        self.assertEqual(r["status"], "SOURCE_ELIGIBLE_NOT_HARDWARE_QUALIFIED")
        self.assertEqual(r["family_coverage"], ["ipv4", "ipv6"])
        self.assertTrue(r["live_hardware_isolation_unverified"])
        self.assertTrue(r["real_trusted_untrusted_probes_still_required"])
        self.assertEqual(r["configured_listener_count"], 4)
        self.assertFalse(r["violation_codes"])
        self.assertFalse(r["missing_evidence"])
        self.assertNotIn(V4, str(r))
        self.assertNotIn(V6, str(r))

    def test_ipv4_wildcard_rejected_even_if_filter_is_on(self):
        s = scenario()
        s["uci"] = uci([("https", bind_v4(443, WILDCARD4))])
        r = assess(**s)
        self.assertEqual(r["status"], "SOURCE_POLICY_REJECTED")
        self.assertIn("wildcard_management_listener", r["violation_codes"])

    def test_ipv6_wildcard_rejected_even_if_https(self):
        s = scenario()
        s["uci"] = uci([("https", bind_v6(443, "::"))])
        r = assess(**s)
        self.assertIn("wildcard_management_listener", r["violation_codes"])

    def test_untrusted_host_dataplane_connection_rejected(self):
        s = scenario()
        e = s["ingress"]
        for i, item in enumerate(e):
            if item[4] == "host_dataplane" and item[1] == "ipv4":
                e[i] = (*item[:5], "connected")
                break
        self.assertIn("untrusted_ingress_connected",
                      assess(**s)["violation_codes"])

    def test_untrusted_upstream_ipv6_connection_rejected(self):
        s = scenario()
        e = s["ingress"]
        for i, item in enumerate(e):
            if item[4] == "upstream_wan" and item[1] == "ipv6":
                e[i] = (*item[:5], "connected")
                break
        self.assertIn("untrusted_ingress_connected",
                      assess(**s)["violation_codes"])

    def test_trusted_management_access_refused_is_not_eligible(self):
        s = scenario()
        e = s["ingress"]
        for i, item in enumerate(e):
            if item[4] == "trusted":
                e[i] = (*item[:5], "refused")
                break
        self.assertIn("trusted_management_path_unreachable",
                      assess(**s)["violation_codes"])

    def test_missing_untrusted_evidence_is_not_success(self):
        s = scenario()
        s["ingress"] = [x for x in s["ingress"] if x[4] != "upstream_wan"]
        r = assess(**s)
        self.assertEqual(r["status"], "SOURCE_EVIDENCE_INCOMPLETE")
        self.assertIn("missing_untrusted_ingress_upstream_wan",
                      r["missing_evidence"])

    def test_no_independent_management_ip_not_eligible(self):
        s = scenario()
        s["management"] = {"ipv4": [], "ipv6": []}
        r = assess(**s)
        self.assertNotEqual(r["status"], "SOURCE_ELIGIBLE_NOT_HARDWARE_QUALIFIED")

    def test_runtime_wildcard_expansion_is_refused(self):
        s = scenario()
        proc = s["processes"][0]
        proc[proc.index(bind_v4(443))] = bind_v4(443, WILDCARD4)
        self.assertIn("configured_runtime_listener_mismatch",
                      assess(**s)["violation_codes"])

    def test_extra_kernel_listener_same_port_is_refused(self):
        s = scenario()
        s["kernel"]["ipv4"] = proc_table(
            "ipv4", [(V4, 80), (V4, 443), (WILDCARD4, 443)])
        self.assertIn("additional_kernel_listener_same_port",
                      assess(**s)["violation_codes"])

    def test_missing_kernel_ipv6_is_incomplete(self):
        s = scenario()
        s["kernel"]["ipv6"] = None
        self.assertIn("missing_kernel_ipv6", assess(**s)["missing_evidence"])

    def test_not_all_families_verified_is_incomplete(self):
        s = scenario()
        del s["kernel"]["ipv6"]
        self.assertIn("incomplete_kernel_family_evidence",
                      assess(**s)["missing_evidence"])

    def test_missing_live_process_is_incomplete(self):
        s = scenario()
        s["processes"] = None
        self.assertEqual(assess(**s)["status"], "SOURCE_EVIDENCE_INCOMPLETE")

    def test_management_listener_only_on_loopback_is_not_qualified(self):
        loopback = ".".join(("127", "0", "0", "1"))
        s = scenario()
        s["uci"] = uci([("https", bind_v4(443, loopback))])
        self.assertIn("verified_management_https_listener",
                      assess(**s)["missing_evidence"])

    def test_nonmanagement_ip_bind_is_blocked(self):
        s = scenario()
        s["uci"] = uci([("https", bind_v4(443, V4_EXTRA))])
        self.assertIn("non_management_listener", assess(**s)["violation_codes"])

    def test_ipv6_absence_not_silently_assumed_safe(self):
        s = scenario()
        s["uci"] = uci([("https", bind_v4(443))])
        s["processes"] = [["/usr/sbin/uhttpd", "-s", bind_v4(443)]]
        s["kernel"] = {
            "ipv4": proc_table("ipv4", [(V4, 443)]),
            "ipv6": proc_table("ipv6", []),
        }
        s["ingress"] = [x for x in s["ingress"] if
                        x[:4] == ("https", "ipv4", V4, 443)]
        r = assess(**s)
        self.assertIn("ipv6_listener_absence_not_qualified", r["missing_evidence"])
        r2 = assess(**s, ipv6_disabled_verified=True)
        self.assertEqual(r2["status"], "SOURCE_ELIGIBLE_NOT_HARDWARE_QUALIFIED")

    def test_ipv4_absence_not_claimed_safe(self):
        s = scenario()
        s["uci"] = uci([("https", bind_v6(443))])
        s["processes"] = [["/usr/sbin/uhttpd", "-s", bind_v6(443)]]
        s["kernel"] = {"ipv4": proc_table("ipv4", []),
                       "ipv6": proc_table("ipv6", [(V6, 443)])}
        s["ingress"] = [x for x in s["ingress"] if
                        x[:4] == ("https", "ipv6", str(ipaddress.ip_address(V6)), 443)]
        self.assertIn("ipv4_listener_absence_not_qualified",
                      assess(**s)["missing_evidence"])

    def test_ipv6_linklocal_without_scope_is_blocked(self):
        s = scenario()
        s["uci"] = uci([("https", bind_v6(443, "fe80::10"))])
        self.assertIn("unqualified_listener_address",
                      assess(**s)["violation_codes"])

    def test_kernel_header_required(self):
        with self.assertRaisesRegex(IsolationError, "invalid_kernel"):
            parse_proc_tcp("", "ipv4")

    def test_ipv6_disabled_claim_conflicts_with_listener(self):
        self.assertIn("ipv6_disabled_but_listener_configured",
                      assess(**scenario(), ipv6_disabled_verified=True)[
                          "violation_codes"])

    def test_duplicate_or_unknown_ingress_not_evidence(self):
        s = scenario()
        s["ingress"].append(s["ingress"][0])
        self.assertIn("duplicate_ingress_evidence", assess(**s)["violation_codes"])
        s2 = scenario()
        s2["ingress"][0] = (*s2["ingress"][0][:5], "filtered")
        self.assertIn("invalid_ingress_record", assess(**s2)["violation_codes"])

    def test_decisions_do_not_contain_ips_or_port_numbers(self):
        r = assess(**scenario())
        report = str(r)
        self.assertNotIn(V4, report)
        self.assertNotIn(V6, report)
        self.assertNotIn(":443", report)
        self.assertNotIn(":80", report)
        self.assertTrue(r["no_network_or_device_mutation"])
        self.assertTrue(r["no_firewall_or_uci_apply"])

    def test_source_only_not_installed(self):
        root = ROOT
        script = (root / "tools/s012_management_isolation_offline.py").read_text()
        manifest = (root / "MANIFEST.json").read_text()
        deployed = (root / "overlay/usr/lib/lua/luci/controller/8311.lua").read_text()
        self.assertNotIn("s012_management_isolation_offline", manifest)
        self.assertNotIn("s012_management_isolation_offline", deployed)
        self.assertNotIn("subprocess.run(", script)
        self.assertNotIn("socket.connect(", script)
        self.assertNotIn("uci commit", script)
        self.assertNotIn("iptables -A", script)


@unittest.skipUnless(
    os.environ.get("AOTT_VENDOR_ROOTFS") and
    (VENDOR / "etc/config/uhttpd").is_file(),
    "Extracted vendor rootfs unavailable; hardware reading not authorized",
)
class VendorExtractedSourceTests(unittest.TestCase):
    def test_extracted_vendor_source_wildcard_bind_is_rejected(self):
        cfg = read_vendor_uhttpd(str(VENDOR))
        r = assess(cfg)
        self.assertEqual(r["status"], "SOURCE_POLICY_REJECTED")
        self.assertIn("wildcard_management_listener", r["violation_codes"])
        self.assertGreaterEqual(r["configured_ipv4_listeners"], 2)
        self.assertGreaterEqual(r["configured_ipv6_listeners"], 2)
        self.assertTrue(r["live_hardware_isolation_unverified"])
        self.assertNotIn(V4, str(r))

    def test_extracted_source_has_http_and_https(self):
        found = parse_uhttpd_uci(read_vendor_uhttpd(str(VENDOR)))
        self.assertEqual({x[0] for x in found}, {"http", "https"})
        self.assertEqual({x[1] for x in found}, {"ipv4", "ipv6"})


if __name__ == "__main__":
    unittest.main()
