"""C-011: safe, native read-only TC flower rule verification boundary.

The tests replace ONLY the path to a shell-library matcher in a
temporary copy. They never invoke the real tc binary, production ONU,
network interface, provider settings, or mutate a real rule.
"""
from __future__ import annotations
import os
from pathlib import Path
import re
import stat
import subprocess
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
WRAPPER=ROOT/"overlay/usr/sbin/8311-tc-readonly-verify.sh"
MODEL=ROOT/"overlay/usr/lib/lua/8311/effective_vlan_state.lua"
PROBE=ROOT/"overlay/usr/lib/lua/8311/effective_vlan_probe.lua"
FIXTURE=ROOT/"tests/effective_vlan_tc_fixture.lua"
VENDOR=Path(os.getenv("AOTT_VENDOR_ROOTFS","/no-offline-vendor"))


class NativeTcReadOnlyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source=WRAPPER.read_text()
        cls.sandbox=tempfile.TemporaryDirectory(prefix="aott-tc-readonly-")
        cls.root=Path(cls.sandbox.name)
        cls.mocklib=cls.root/"mock_native_matcher.sh"
        cls.mocklib.write_text("""#!/bin/sh
tc_flower_matches() {
    printf '%s\\n' "$*" >> "$AOTT_TEST_RULE_LOG"
    if [ "$AOTT_TEST_FAIL" = yes ]; then
        return 1
    fi
    return 0
}
""")
        cls.mocklib.chmod(0o600)
        needle="[ -r /lib/8311-vlans-lib.sh ] || exit 69\n. /lib/8311-vlans-lib.sh || exit 69"
        assert cls.source.count(needle)==1
        replacement=("[ -r '"+str(cls.mocklib)+"' ] || exit 69\n"
                     ". '"+str(cls.mocklib)+"' || exit 69")
        cls.stub=cls.root/"test_only_no_native_tc.sh"
        cls.stub.write_text(cls.source.replace(needle,replacement))
        cls.stub.chmod(0o700)

    @classmethod
    def tearDownClass(cls):
        cls.sandbox.cleanup()

    def run_case(self,fields,fail=False):
        log=self.root/"rules.log"
        log.write_text("")
        env=os.environ.copy()
        env["AOTT_TEST_RULE_LOG"]=str(log)
        env["AOTT_TEST_FAIL"]="yes" if fail else "no"
        p=subprocess.run(["/bin/sh",str(self.stub),*fields],
            cwd=self.root,env=env,capture_output=True,
            text=True,stdin=subprocess.DEVNULL,timeout=12)
        return p,log.read_text().splitlines()

    def test_rule_profiles_tagged_services_without_multicast(self):
        p,lines=self.run_case(["200","36","100","pmapper4354",
                               "pmapper57603","100","0"])
        self.assertEqual(p.returncode,0,p.stderr)
        self.assertEqual(p.stdout,"VERIFIED_RULES=8\n")
        self.assertEqual(len(lines),8)
        self.assertTrue(lines[0].startswith(
            "dev pmapper4354 ingress handle 0x1"))
        self.assertIn("vlan modify id 200",lines[0])
        self.assertIn("vlan modify id 100",lines[1])
        self.assertTrue(lines[4].startswith(
            "dev pmapper57603 ingress handle 0x1"))
        self.assertIn("vlan modify id 36",lines[4])
        self.assertIn("vlan modify id 100",lines[5])
        self.assertFalse(any("eth0_0_2" in line for line in lines))

    def test_untagged_internet_rules(self):
        p,lines=self.run_case(["0","36","100","pmapper4354",
                               "pmapper57603","100","0"])
        self.assertEqual(p.returncode,0,p.stderr)
        self.assertEqual(p.stdout,"VERIFIED_RULES=7\n")
        self.assertEqual(len(lines),7)
        self.assertIn("action vlan pop pass",lines[0])
        self.assertIn("action drop",lines[1])
        self.assertIn("action vlan push id 100",lines[2])

    def test_multicast_rule_count_and_selection(self):
        p,lines=self.run_case(["200","36","100","pmapper4354",
                               "pmapper57603","100","1"])
        self.assertEqual(p.returncode,0,p.stderr)
        self.assertEqual(p.stdout,"VERIFIED_RULES=9\n")
        self.assertEqual(len(lines),9)
        self.assertIn("dev eth0_0_2 egress",lines[8])
        self.assertIn("action vlan modify id 36 priority 5",lines[8])

    def test_single_service_mode_never_queries_missing_pmapper(self):
        for vlan,expected in (("0",3),("200",4)):
            with self.subTest(vlan=vlan):
                p,lines=self.run_case(
                    [vlan,"36","100","pmapper4354","-","-","0"])
                self.assertEqual(p.returncode,0,p.stderr)
                self.assertEqual(p.stdout,
                                 "VERIFIED_RULES="+str(expected)+"\n")
                self.assertEqual(len(lines),expected)
                self.assertTrue(all("pmapper57603" not in l for l in lines))

    def test_invalid_args_rejected_before_native_matcher_called(self):
        cases=[
            ["4096","36","100","pmapper4354","pmapper57603","100","0"],
            ["0","0","100","pmapper4354","pmapper57603","100","0"],
            ["200","200","100","pmapper4354","pmapper57603","100","0"],
            ["200","36","0","pmapper4354","pmapper57603","100","0"],
            ["200","36","100","eth0_0","pmapper57603","100","0"],
            ["200","36","100","pmapper4354;echo",
             "pmapper57603","100","0"],
            ["200","36","100","pmapper4354","pmapper4354","100","0"],
            ["200","36","100","pmapper4354","-","-","1"],
            ["200","36","100","pmapper4354","pmapper57603","-","0"],
            ["200","36","100","pmapper4354","pmapper57603","100","bad"],
            ["200","36","100","pmapper4354","pmapper57603","100"],
        ]
        for fields in cases:
            with self.subTest(fields=str(fields)[:50]):
                p,lines=self.run_case(fields)
                self.assertNotEqual(p.returncode,0)
                self.assertNotIn("VERIFIED_RULES=",p.stdout)
                self.assertEqual(lines,[])

    def test_native_match_failure_never_claims_all_rules_verified(self):
        p,lines=self.run_case(["200","36","100","pmapper4354",
                               "pmapper57603","100","0"],fail=True)
        self.assertNotEqual(p.returncode,0)
        self.assertEqual(p.stdout,"")
        self.assertEqual(len(lines),1)

    def test_source_has_no_mutating_commands_or_dynamic_shell(self):
        s=self.source
        self.assertIn('tc_flower_matches "$@" || exit 1',s)
        executable="\n".join(
            line.strip() for line in s.splitlines()
            if line.strip() and not line.lstrip().startswith("#"))
        self.assertNotRegex(
            executable,
            r"\btc\s+(?:filter\s+)?(?:add|del|delete|replace|flush|change)\b")
        for bad in (
            "tc_flower_ensure", "tc_flower_del", "tc_flower_replace",
            "tc_flower_clear", "fwenv_set", "fw_setenv",
            "uci commit", "uci set", "opkg install",
            "ifconfig ", "ip link set", "eval ", "source /ptconf/",
            "reboot", "sysupgrade", "iptables -A",
        ):
            with self.subTest(disallowed=bad):
                # Comments can describe excluded operations. Only
                # match executable source positions, not comments.
                source_lines=[l.strip() for l in s.splitlines()
                              if l.strip() and not l.lstrip().startswith("#")]
                self.assertNotIn(bad,"\n".join(source_lines))
        self.assertTrue(WRAPPER.stat().st_mode & stat.S_IXUSR)
        p=subprocess.run(["/bin/sh","-n",str(WRAPPER)],
                          capture_output=True,text=True,timeout=12)
        self.assertEqual(p.returncode,0,p.stderr)

    def test_pure_lua_model_validation_on_host_and_vendor_mips(self):
        cmd=["lua5.1",str(FIXTURE),str(ROOT/"overlay/usr/lib/lua")]
        host=subprocess.run(cmd,capture_output=True,text=True,timeout=20)
        self.assertEqual(host.returncode,0,host.stderr)
        self.assertIn("AOTT_C011_TC_READONLY_FIXTURE_PASS checks=75",
                      host.stdout)
        if os.getenv("AOTT_VENDOR_ROOTFS"):
            binary=VENDOR/"usr/bin/lua"
            self.assertTrue(binary.is_file())
            proc=subprocess.run(["qemu-mips-static","-L",str(VENDOR),
                                 str(binary),str(FIXTURE),
                                 str(ROOT/"overlay/usr/lib/lua")],
                                capture_output=True,text=True,timeout=25)
            self.assertEqual(proc.returncode,0,proc.stderr)
            self.assertIn("AOTT_C011_TC_READONLY_FIXTURE_PASS checks=75",
                          proc.stdout)

    def test_probe_is_gated_on_receipt_hash_and_builtin_mode(self):
        p=PROBE.read_text()
        self.assertIn("type(adapter.verify_rules)==\"function\"",p)
        self.assertIn('saved.fix_vlans=="1"',p)
        self.assertIn("current_hash==plan.topology_hash",p)
        self.assertIn('"/usr/sbin/8311-tc-readonly-verify.sh"',p)
        self.assertIn('"/usr/bin/timeout","-k","1","12"',p)
        self.assertNotIn("tc filter add",p)
        self.assertNotIn("tc filter delete",p)
        model=MODEL.read_text()
        self.assertIn("function M.parse_rule_plan(body)",model)
        self.assertIn("function M.strict_rule_evidence(output, plan)",model)
        self.assertIn("proves_subscriber_internet=false",model)
        self.assertIn("proves_hardware_offload=false",model)
        self.assertIn("rules_scope=\"builtin_owned_selectors_only\"",model)


if __name__=="__main__":
    unittest.main()
