"""Offline vendor management exposure and r8 collector guard contracts.

No firewall is modified, and there are no probes against real addresses.
"""
import os
from pathlib import Path
import re
import unittest

ROOT=Path(__file__).resolve().parents[1]
VENDOR=Path(os.getenv("AOTT_VENDOR_ROOTFS","/nonexistent/vendor/rootfs"))


class ManagementAccessContractTests(unittest.TestCase):
    def test_collector_is_restricted_in_app_even_with_wildcard_listener(self):
        monitor=(ROOT/"overlay/usr/lib/lua/8311/monitoring.lua").read_text()
        controller=(ROOT/"overlay/usr/lib/lua/luci/controller/8311.lua").read_text()
        self.assertIn('getenv("HTTPS")',monitor)
        self.assertIn('getenv("REMOTE_ADDR")',monitor)
        self.assertIn('getenv("SERVER_ADDR")',monitor)
        self.assertIn('HTTP_X_AOTT_METRICS_TOKEN',monitor)
        self.assertIn("trusted_local_address(u, local_addr)",monitor)
        self.assertIn("store.same_live(saved)",monitor)
        self.assertIn('collector_authorized(http.getenv)',controller)
        self.assertNotIn('getenv("HTTP_X_FORWARDED_FOR")',monitor)
        self.assertNotIn('getenv("QUERY_STRING")',monitor)

    def test_no_new_public_firewall_accept_rules(self):
        overlay=ROOT/"overlay"
        self.assertFalse((overlay/"etc/config/firewall").exists())
        for candidate in (overlay/"etc/uci-defaults/zzz-8311",
                          overlay/"etc/init.d/8311-monitoring"):
            text=candidate.read_text()
            self.assertNotIn("iptables -I",text)
            self.assertNotIn("firewall.@rule",text)

    def test_audit_requires_real_firewall_and_older_bank_checks(self):
        audit=(ROOT/"docs/V2R8-MANAGEMENT-ACL-AUDIT.md").read_text()
        self.assertIn("wildcard",audit)
        self.assertIn("untrusted/WAN",audit)
        self.assertIn("effective iptables/firewall",audit)
        self.assertIn("previous firmware bank",audit)
        self.assertIn("not proof",audit.lower())

    def test_actual_vendor_baseline_has_wildcard_web_and_wan_reject(self):
        f=VENDOR/"etc/config/firewall"
        h=VENDOR/"etc/config/uhttpd"
        if not (f.is_file() and h.is_file()):
            if os.getenv("AOTT_VENDOR_ROOTFS"):
                self.fail("Explicit vendor firewall and uhttpd configs unavailable")
            self.skipTest("Optional proprietary firmware baseline unavailable")
        data=h.read_text()
        self.assertIn("listen_http",data)
        self.assertIn("listen_https",data)
        self.assertIn("0" + ".0.0.0:80",data)
        self.assertIn("0" + ".0.0.0:443",data)
        self.assertIn("redirect_https",data)
        zones=f.read_text().split("config zone")
        wan=next((zone for zone in zones if re.search(
            r"option name\s+wan(?:\s|$)",zone)),None)
        self.assertIsNotNone(wan)
        self.assertRegex(wan,r"option input\s+REJECT")


if __name__=="__main__":
    unittest.main()
