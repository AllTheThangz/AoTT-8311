"""C-014 native vendor-UCI staging on disposable synthetic packages.
No production package is read, no live network apply/promotion exists.
"""
import copy
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from c014_vlan_candidate import (
    OWNER, VlanCandidateError, parse_export, plan_transition,
    revision, verify_staged_plan,
)
VENDOR = Path(os.environ.get("AOTT_VENDOR_ROOTFS", "/missing/vendor-rootfs"))
PACKAGES = {p: "aott_c014_" + p for p in ("network", "firewall")}
IP = ".".join(("192", "0", "2", "10"))
MASK = ".".join(("255", "255", "255", "0"))
MAC = ":".join(("02", "11", "22", "33", "44", "55"))
PARENT = "eth0_0_1_lct"
NETWORK = f"""config interface 'lct'
 option ifname '{PARENT}'
 option proto 'static'
 option auto '1'
 option macaddr '{MAC}'
 option ipaddr '{IP}'
 option netmask '{MASK}'
 option gateway '{IP}'
 list dns 'resolver.example.invalid'
config interface 'untouched'
 option ifname 'other_fixture'
 option proto 'none'
"""
FIREWALL = """config zone
 option name 'wan'
 option input 'REJECT'
 list network 'wan'
config zone
 option name 'lan'
 option input 'ACCEPT'
 list network 'lan'
 list network 'lct'
config rule 'untouched_rule'
 option name 'Synthetic unchanged rule'
 option src 'lan'
 option target 'ACCEPT'
"""


def state():
    return {p: parse_export("package " + PACKAGES[p] + "\n" + text, PACKAGES[p])
            for p, text in (("network", NETWORK), ("firewall", FIREWALL))}


def plan(snapshot, vlan, **kw):
    args = dict(expected_revision=revision(snapshot), parent=PARENT, zone_name="lan")
    args.update(kw)
    return plan_transition(snapshot, vlan, **args)


class CandidatePlanTests(unittest.TestCase):
    def test_tagged_then_untagged_semantically_restores_original(self):
        before = state()
        tagged = plan(before, 123)["after"]
        self.assertEqual(plan(tagged, 0)["after"], before)
        self.assertNotIn("ipaddr", tagged["network"]["lct"]["options"])
        self.assertEqual(tagged["network"]["mgmt"]["options"]["gateway"], IP)
        self.assertEqual(tagged["network"]["mgmt"]["options"]["dns"], ["resolver.example.invalid"])
        self.assertEqual(state(), before)

    def test_same_state_and_vlan_are_noops(self):
        before = state()
        self.assertEqual(plan(before, 0)["operations"], [])
        tagged = plan(before, 123)["after"]
        self.assertEqual(plan(tagged, 123)["operations"], [])

    def test_tag_change_only_changes_owned_device_vid(self):
        tagged = plan(state(), 123)["after"]
        result = plan(tagged, 456)
        self.assertEqual(result["operations"], [("set", "network.lct_vlan.vid=456")])
        self.assertEqual(plan(result["after"], 0)["after"], state())

    def test_zone_is_found_by_name_and_membership_not_first_position(self):
        before = state()
        after = plan(before, 123)["after"]
        self.assertEqual(after["firewall"]["@zone[0]"], before["firewall"]["@zone[0]"])
        self.assertEqual(after["firewall"]["@zone[1]"]["options"]["network"], ["lan", "lct", "mgmt"])
        self.assertEqual(after["firewall"]["untouched_rule"], before["firewall"]["untouched_rule"])
        self.assertEqual(after["network"]["untouched"], before["network"]["untouched"])

    def test_scalar_zone_membership_remains_scalar_on_roundtrip(self):
        before = state()
        before["firewall"]["@zone[1]"]["options"]["network"] = "lan lct"
        tagged = plan(before, 123)["after"]
        self.assertEqual(tagged["firewall"]["@zone[1]"]["options"]["network"], "lan lct mgmt")
        self.assertEqual(plan(tagged, 0)["after"], before)

    def test_absent_gateway_and_dns_stay_absent_after_roundtrip(self):
        before = state()
        for field in ("gateway", "dns"):
            del before["network"]["lct"]["options"][field]
        self.assertEqual(plan(plan(before, 123)["after"], 0)["after"], before)

    def test_invalid_vlan_never_falls_back_to_zero(self):
        for value in (True, None, "123", "invalid", -1, 4095, 4096):
            with self.subTest(value=value), self.assertRaises(VlanCandidateError):
                plan(state(), value)

    def test_stale_revision_and_unknown_parent_refused(self):
        for changes in ({"expected_revision": "0" * 64}, {"parent": "unknown"}, {"zone_name": "wan"}):
            with self.subTest(changes=changes), self.assertRaises(VlanCandidateError):
                plan(state(), 123, **changes)

    def test_legacy_unowned_interfaces_are_not_adopted_or_deleted(self):
        for name in ("mgmt", "lct_vlan"):
            with self.subTest(name=name):
                before = state()
                before["network"][name] = {"type": "interface", "options": {"proto": "static"}}
                with self.assertRaisesRegex(VlanCandidateError, "ownership"):
                    plan(before, 0)

    def test_owned_interface_extra_options_and_mismatched_mac_refused(self):
        for key, value in (("mtu", "1400"), ("macaddr", "not-the-parent")):
            before = plan(state(), 123)["after"]
            before["network"]["mgmt"]["options"][key] = value
            with self.subTest(key=key), self.assertRaises(VlanCandidateError):
                plan(before, 0)

    def test_foreign_reference_prevents_deletion(self):
        before = plan(state(), 123)["after"]
        before["network"]["route"] = {"type": "route", "options": {"interface": "mgmt"}}
        with self.assertRaisesRegex(VlanCandidateError, "foreign_management_reference"):
            plan(before, 0)

    def test_ambiguous_zones_and_extra_membership_refused(self):
        before = state()
        before["firewall"]["@zone[0]"]["options"]["network"].append("lct")
        with self.assertRaisesRegex(VlanCandidateError, "multiple_zones"):
            plan(before, 123)
        before = state()
        before["firewall"]["duplicate"] = copy.deepcopy(before["firewall"]["@zone[1]"])
        with self.assertRaisesRegex(VlanCandidateError, "not_unique"):
            plan(before, 123)

    def test_ipv6_or_unqualified_lct_options_do_not_get_silently_moved(self):
        before = state()
        before["network"]["lct"]["options"]["ip6assign"] = "64"
        with self.assertRaisesRegex(VlanCandidateError, "lct_profile_unqualified"):
            plan(before, 123)

    def test_malformed_exports_refused(self):
        for text in ("", "package wrong\n", "package aott_c014_network\nconfig interface 'oops\n",
                     "package aott_c014_network\nconfig interface 'lct'\noption proto 'static'\noption proto 'dhcp'\n"):
            with self.subTest(size=len(text)), self.assertRaises(VlanCandidateError):
                parse_export(text, PACKAGES["network"])

    def test_no_production_adapter_or_overlay_install(self):
        source = (ROOT / "tools/c014_vlan_candidate.py").read_text()
        for token in ("subprocess", "os.system", "open(", "ifup", "fwenv_set", "socket"):
            self.assertNotIn(token, source)
        self.assertNotIn("c014_vlan_candidate", (ROOT / "MANIFEST.json").read_text())
        with self.assertRaisesRegex(VlanCandidateError, "private_candidate_adapter_required"):
            verify_staged_plan(plan(state(), 123), object())


class PrivateVendorUci:
    disposable_fixture = True

    def __init__(self, root, config, packages, fail_at=None):
        self.root, self.config, self.packages = root, config, packages
        self.delta = root / (config.name + "_delta")
        self.empty = root / (config.name + "_cold")
        self.delta.mkdir(mode=0o700)
        self.empty.mkdir(mode=0o700)
        self.fail_at, self.mutations = fail_at, 0
        self.base = ["qemu-mips-static", "-L", str(VENDOR), str(VENDOR / "sbin/uci"),
                     "-c", str(config)]

    def run(self, argv, commit=False, cold=False):
        assert self.root.parent == Path("/var/tmp") and self.root.name.startswith("aott-c014-native-test-")
        assert self.config.parent == self.root and self.delta.parent == self.root
        # Vendor UCI also searches its default delta directory. Random per-test
        # package names and refusal of any default-path collision prevent reads
        # of another caller's pending settings. No real package is referenced.
        if any((Path("/tmp/.uci") / p).exists() for p in self.packages.values()):
            raise VlanCandidateError("default_delta_collision")
        path = self.empty if cold else self.delta
        # -P selects a private savedir but ALSO disables commits in this UCI.
        # Only the commit process uses -p to read the private delta without
        # setting NOCOMMIT. Every commit is checked via a new no-delta reader.
        flag = "-p" if commit else "-P"
        result = subprocess.run(self.base + [flag, str(path)] + argv,
                                capture_output=True, text=True, timeout=5)
        if any((Path("/tmp/.uci") / p).exists() for p in self.packages.values()):
            raise VlanCandidateError("unexpected_default_delta")
        return result

    def package_snapshot(self, package, cold=False):
        native = self.packages[package]
        read = self.run(["export", native], cold=cold)
        if read.returncode:
            raise VlanCandidateError("native_export_failed")
        return parse_export(read.stdout, native)

    def snapshot(self):
        return {p: self.package_snapshot(p) for p in self.packages}

    def persisted_snapshot(self):
        return {p: self.package_snapshot(p, cold=True) for p in self.packages}

    def command(self, op):
        self.mutations += 1
        if self.mutations == self.fail_at:
            # Produce a real native-UCI error, not a fabricated return code.
            return self.run(["set", self.packages["network"] + ".no_such_section.field=value"]).returncode == 0
        verb, operand = op
        package, dot, tail = operand.partition(".")
        if package not in self.packages or verb not in ("set", "delete", "add_list", "commit"):
            raise VlanCandidateError("unexpected_fixture_operation")
        if verb != "commit":
            return self.run([verb, self.packages[package] + dot + tail]).returncode == 0
        expected = self.package_snapshot(package)
        if self.run(["commit", self.packages[package]], commit=True).returncode:
            return False
        if self.package_snapshot(package, cold=True) != expected:
            return False
        # -p consumes an additional delta source but does not empty it. Only
        # after cold readback may THIS disposable adapter clear its own copy.
        delta = self.delta / self.packages[package]
        if delta.exists():
            assert delta.is_file() and not delta.is_symlink()
            delta.unlink()
        return self.package_snapshot(package) == expected


@unittest.skipUnless(os.environ.get("AOTT_VENDOR_ROOTFS") and
                     (VENDOR / "sbin/uci").is_file() and shutil.which("qemu-mips-static"),
                     "Extracted vendor UCI and MIPS QEMU required")
class NativeVendorCandidateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="aott-c014-native-test-", dir="/var/tmp")
        self.root = Path(self.temp.name)
        self.root.chmod(0o700)
        self.original = self.root / "original"
        self.original.mkdir(mode=0o700)
        import secrets
        namespace = "aott_c014_" + secrets.token_hex(8)
        self.packages = {p: namespace + "_" + p for p in ("network", "firewall")}
        for name, text in (("network", NETWORK), ("firewall", FIREWALL)):
            path = self.original / self.packages[name]
            path.write_text(text)
            path.chmod(0o600)
        self.original_bytes = {p.name: p.read_bytes() for p in self.original.iterdir()}
        self.adapters = 0

    def tearDown(self):
        self.assertEqual({p.name: p.read_bytes() for p in self.original.iterdir()}, self.original_bytes)
        self.temp.cleanup()

    def stage(self, source=None, fail_at=None):
        self.adapters += 1
        path = self.root / ("candidate_" + str(self.adapters))
        shutil.copytree(source or self.original, path)
        path.chmod(0o700)
        return PrivateVendorUci(self.root, path, self.packages, fail_at)

    def test_vendor_P_commit_zero_exit_is_not_persistence(self):
        stage = self.stage()
        before = stage.persisted_snapshot()
        self.assertTrue(stage.command(("set", "network.untouched.proto=static")))
        result = stage.run(["commit", stage.packages["network"]])
        self.assertEqual(result.returncode, 0)
        self.assertNotEqual(stage.snapshot(), before)
        self.assertEqual(stage.persisted_snapshot(), before)

    def test_real_vendor_roundtrip_and_unrelated_preservation(self):
        stage = self.stage()
        before = stage.snapshot()
        first = plan(before, 123)
        receipt = verify_staged_plan(first, stage)
        self.assertEqual(receipt["status"], "SOURCE_NATIVE_UCI_CANDIDATE_VALIDATED")
        self.assertFalse(receipt["live_promote_available"])
        self.assertNotIn(IP, str(receipt))
        second = self.stage(stage.config)
        verify_staged_plan(plan(second.snapshot(), 0), second)
        self.assertEqual(second.snapshot(), before)

    def test_real_tag_to_tag_then_idempotent_replay(self):
        stage = self.stage()
        verify_staged_plan(plan(stage.snapshot(), 123), stage)
        verify_staged_plan(plan(stage.snapshot(), 456), stage)
        same = plan(stage.snapshot(), 456)
        self.assertEqual(same["operations"], [])
        verify_staged_plan(same, stage)
        self.assertEqual(stage.snapshot()["network"]["lct_vlan"]["options"]["vid"], "456")

    def test_every_native_mutation_and_commit_failure_is_refused(self):
        initial = self.stage().snapshot()
        proposed = plan(initial, 123)
        for step in range(1, len(proposed["operations"]) + 3):
            with self.subTest(native_step=step):
                stage = self.stage(fail_at=step)
                with self.assertRaisesRegex(VlanCandidateError, "candidate_(mutation|commit)_failed"):
                    verify_staged_plan(proposed, stage)
                self.assertEqual(stage.mutations, step)
        self.assertGreater(len(proposed["operations"]), 10)

    def test_native_inverse_failure_also_preserves_tagged_source(self):
        tagged = self.stage()
        verify_staged_plan(plan(tagged.snapshot(), 123), tagged)
        bytes_before = {p.name: p.read_bytes() for p in tagged.config.iterdir()}
        proposed = plan(tagged.snapshot(), 0)
        for step in range(1, len(proposed["operations"]) + 3):
            with self.subTest(inverse_step=step):
                candidate = self.stage(tagged.config, fail_at=step)
                with self.assertRaisesRegex(VlanCandidateError, "candidate_(mutation|commit)_failed"):
                    verify_staged_plan(proposed, candidate)
                self.assertEqual(candidate.mutations, step)
                self.assertEqual({p.name: p.read_bytes() for p in tagged.config.iterdir()}, bytes_before)

    def test_native_scalar_membership_and_no_optional_route_roundtrip(self):
        stage = self.stage()
        stage.command(("set", "firewall.@zone[1].network=lan lct"))
        stage.command(("delete", "network.lct.gateway"))
        stage.command(("delete", "network.lct.dns"))
        stage.command(("commit", "network"))
        stage.command(("commit", "firewall"))
        before = stage.snapshot()
        verify_staged_plan(plan(before, 123), stage)
        inverse = self.stage(stage.config)
        verify_staged_plan(plan(inverse.snapshot(), 0), inverse)
        self.assertEqual(inverse.snapshot(), before)

    def test_native_legacy_interface_collision_refused_before_writes(self):
        stage = self.stage()
        self.assertTrue(stage.command(("set", "network.mgmt=interface")))
        self.assertTrue(stage.command(("commit", "network")))
        with self.assertRaisesRegex(VlanCandidateError, "ownership"):
            plan(stage.snapshot(), 0)

    def test_candidate_changed_after_preview_refused(self):
        stage = self.stage()
        proposed = plan(stage.snapshot(), 123)
        stage.command(("set", "network.untouched.proto=static"))
        with self.assertRaisesRegex(VlanCandidateError, "stale_candidate_revision"):
            verify_staged_plan(proposed, stage)

    def test_success_exit_with_bad_readback_does_not_validate(self):
        stage = self.stage()
        proposed = plan(stage.snapshot(), 123)
        original_snapshot = stage.persisted_snapshot
        def corrupt_final_readback():
            result = original_snapshot()
            result["network"]["lct_vlan"]["options"]["vid"] = "999"
            return result
        stage.persisted_snapshot = corrupt_final_readback
        with self.assertRaisesRegex(VlanCandidateError, "candidate_readback_mismatch"):
            verify_staged_plan(proposed, stage)


if __name__ == "__main__":
    unittest.main()
