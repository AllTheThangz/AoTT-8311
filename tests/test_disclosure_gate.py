"""Negative privacy tests for public source and documentation."""
import importlib.util
import pathlib
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"
sys.path.insert(0, str(TOOLS))
from check_disclosure import check_text, scan


class DisclosureGateTests(unittest.TestCase):
    def problems(self, text, relative="docs/example.md"):
        return {item[0] for item in check_text(relative, text)}

    def test_public_ipv4_rejected(self):
        address = ".".join(map(str, (9, 4, 5, 6)))
        self.assertIn("embedded_site_or_public_ipv4", self.problems("WAN=" + address))

    def test_private_management_ipv4_rejected(self):
        address = ".".join(map(str, (10, 31, 41, 51)))
        self.assertIn("embedded_site_or_public_ipv4", self.problems("gateway=" + address))

    def test_documentation_ranges_are_not_subscriber_identifiers(self):
        address = ".".join(map(str, (192, 0, 2, 22)))
        self.assertNotIn("embedded_site_or_public_ipv4", self.problems("example=" + address))

    def test_hardware_mac_rejected_even_for_example(self):
        address = ":".join(("02", "ab", "cd", "11", "22", "33"))
        self.assertIn("hardware_mac_address", self.problems("MAC=" + address))

    def test_subscriber_serial_rejected(self):
        serial = "ADTN" + "1234" + "ABCD"
        self.assertIn("subscriber_onu_identity", self.problems("Serial=" + serial))

    def test_embedded_email_rejected(self):
        email = "person" + "@" + "private" + "." + "invalid"
        self.assertIn("embedded_personal_email", self.problems("Contact: " + email))

    def test_an_external_domain_not_on_allowlist_fails(self):
        hostname = "management." + "unreviewed" + ".com"
        self.assertIn("unreviewed_hostname_or_domain", self.problems("Host: " + hostname))

    def test_embedded_private_home_path_fails(self):
        path = "/home/" + "exampleuser" + "/"
        self.assertIn("personal_home_directory", self.problems("config=" + path))

    def test_upstream_copyright_notice_preserved(self):
        address = "author" + "@" + "midlink" + "." + "org"
        notice = " Copyright 2008 Example Author <" + address + ">"
        self.assertNotIn(
            "embedded_personal_email",
            self.problems(notice, "overlay/usr/lib/lua/luci/view/admin_status/index.htm"),
        )
        self.assertIn("embedded_personal_email", self.problems(notice))

    def test_screenshots_and_metadata_carriers_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            (root / "screenshot.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 12)
            _, problems = scan(root)
            labels = {issue[1] for issue in problems}
            self.assertIn("screenshot_or_media_requires_separate_review", labels)
            self.assertIn("binary_data", labels)

    def test_keys_rejected(self):
        header = "-----BEGIN " + "PRIVATE " + "KEY-----"
        self.assertIn("credential_or_key_material", self.problems(header))


if __name__ == "__main__":
    unittest.main()
