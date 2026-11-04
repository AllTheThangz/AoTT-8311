"""C-011 sensitive readback: real validators, root auth and redacted output.
No live identity, credential, ONU connection or firmware mutation is used.
"""
import os
from pathlib import Path
import re
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]
LUA = ROOT / "overlay/usr/lib/lua"
VENDOR = Path(os.environ.get("AOTT_VENDOR_ROOTFS", "/missing/vendor-rootfs"))


class IdentityContractTests(unittest.TestCase):
    def run_fixture(self, command):
        r = subprocess.run(command + [str(ROOT / "tests/effective_identity_fixture.lua"),
                                      str(ROOT)], cwd=ROOT, capture_output=True,
                           text=True, timeout=40)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertRegex(r.stdout, r"AOTT_C011_IDENTITY_PASS covered=54 checks=\d+")

    def test_host_lua_real_schema_all_54_and_identity_contract(self):
        self.run_fixture(["lua5.1"])

    def test_vendor_mips_real_schema_and_sensitive_readback(self):
        if not os.environ.get("AOTT_VENDOR_ROOTFS"):
            self.skipTest("Extracted vendor rootfs not supplied")
        self.run_fixture(["qemu-mips-static", "-L", str(VENDOR),
                          str(VENDOR / "usr/bin/lua")])

    def test_lua51_syntax(self):
        for path in (LUA / "8311/effective_identity_state.lua",
                     LUA / "8311/effective_identity_probe.lua",
                     LUA / "luci/controller/8311.lua",
                     ROOT / "tests/effective_identity_fixture.lua"):
            with self.subTest(path=path.name):
                r = subprocess.run(["luac5.1", "-p", str(path)],
                                   capture_output=True, text=True, timeout=10)
                self.assertEqual(r.returncode, 0, r.stderr)

    def test_no_mutation_or_full_environment_dump_in_probe(self):
        source = (LUA / "8311/effective_identity_probe.lua").read_text()
        for forbidden in ("fwenv_set", "fw_printenv", "fwenv_read_all", "get_8311_",
                          "io.popen", "os.execute", "/etc/shadow", "digest_text",
                          "http.formvalue", "http.content", "bankctl", "socket."):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, source)
        self.assertIn('"/usr/bin/timeout","-k","1","3"', source)
        self.assertIn('"/usr/sbin/fwenv_get","--8311",id', source)
        self.assertIn('status==1 and output==""', source)
        self.assertEqual(source.count('if not M.authorized(dispatcher,util)'), 2)

    def test_real_handler_is_admin_get_and_fixed_errors(self):
        source = (LUA / "luci/controller/8311.lua").read_text()
        self.assertEqual(source.count('{"admin", "8311", "effective_identity"}'), 1)
        handler = source.split('function action_effective_identity()', 1)[1].split(
            'function action_effective_reporting()', 1)[0]
        for required in ('"no-store, private"', '"nosniff"', '"GET"',
                         'probe.live_identity(dispatcher,util)', '405', '403', '503', '200'):
            self.assertIn(required, handler)
        self.assertNotIn('http.formvalue', handler)
        self.assertNotIn('web.reply(http,503,snapshot', handler)

    def test_entire_browser_script_preserves_strict_mode(self):
        source = (ROOT / "overlay/www/luci-static/resources/view/8311.js").read_text()
        self.assertTrue(source.lstrip().startswith('"use strict";'))
        self.assertEqual(source.count('"use strict";'), 1)

    def test_frontend_never_renders_values_or_exception_details(self):
        source = (ROOT / "overlay/www/luci-static/resources/view/8311.js").read_text()
        panel = source.split('function refreshIdentityEffective()', 1)[1].split(
            '// END IDENTITY READBACK', 1)[0]
        for forbidden in ('innerHTML', 'errorMessage(', 'localStorage', 'setInterval',
                          'console.log', 'post8311'):
            self.assertNotIn(forbidden, panel)
        for required in ('cell.textContent=label', 'td.textContent=text',
                         "cache:'no-store'", 'endpoint.origin!==window.location.origin',
                         'row.value_hash_exported!==false', 'row.value_length_exported!==false',
                         'row.runtime_effect_proven!==false', 'Object.keys(row).length!==keys.length'):
            self.assertIn(required, panel)
        view = (LUA / "luci/view/8311/config.htm").read_text()
        self.assertIn("url('admin/8311/effective_identity')", view)
        self.assertIn('id="aott-identity-effective-refresh" type="button"', view)


if __name__ == "__main__":
    unittest.main()
