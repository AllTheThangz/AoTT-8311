"""H-025 hardware-admission screening and offline ABI contracts.

Loads real Lua-generated sanitized synthetic metrics and exercises the
unattested input evaluator. Does NOT connect to any actual ONU.
"""
import copy
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "prototypes/history"
OVERLAY = ROOT / "overlay/usr/lib/lua"
FIXTURE = ROOT / "tests/h025_resource_probe_fixture.lua"
ABI = ROOT / "tools/h025_reference_abi.py"
SCREEN = ROOT / "tools/h025_screen_evidence.py"
VENDOR = Path(os.environ.get("AOTT_VENDOR_ROOTFS",
                             "/unavailable/offline-vendor-rootfs"))
sys.path.insert(0, str(ROOT / "tools"))
import h025_reference_abi as abi
import h025_screen_evidence as model


def synthetic_snapshot() -> dict:
    proc = subprocess.run(
        ["lua5.1", str(FIXTURE), str(SOURCE), str(OVERLAY), "emit_json"],
        cwd=ROOT, capture_output=True, text=True, timeout=15,
    )
    if proc.returncode:
        raise AssertionError(proc.stderr)
    matches = [line.split("=", 1)[1] for line in proc.stdout.splitlines()
               if line.startswith("AOTT_H025_SANITIZED_SAMPLE=")]
    if len(matches) != 1:
        raise AssertionError("Expected one Lua resource snapshot")
    return json.loads(matches[0])


def sample_set(snapshot):
    return {
        "schema": 1,
        "evidence_origin": model.ORIGIN,
        "phase_samples": {
            "idle": [copy.deepcopy(snapshot) for _ in range(5)],
            "load": [copy.deepcopy(snapshot) for _ in range(10)],
            "recovery": [copy.deepcopy(snapshot) for _ in range(3)],
        },
    }


class H025ResourceProbeTests(unittest.TestCase):
    def test_host_lua_and_exact_224_assertions(self):
        if not shutil.which("lua5.1"):
            self.skipTest("Host Lua 5.1 unavailable")
        result = subprocess.run(
            ["lua5.1", str(FIXTURE), str(SOURCE), str(OVERLAY)],
            cwd=ROOT, capture_output=True, text=True, timeout=15,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("AOTT_H025_RESOURCE_SOURCE_FIXTURE_PASS checks=224",
                      result.stdout)

    def test_offline_vendor_mips_and_exact_224_assertions(self):
        if not os.environ.get("AOTT_VENDOR_ROOTFS"):
            self.skipTest("Extracted vendor MIPS rootfs unavailable")
        self.assertTrue((VENDOR / "usr/bin/lua").is_file())
        self.assertIsNotNone(shutil.which("qemu-mips-static"))
        result = subprocess.run(
            ["qemu-mips-static", "-L", str(VENDOR),
             str(VENDOR / "usr/bin/lua"),
             str(FIXTURE), str(SOURCE), str(OVERLAY)],
            cwd=ROOT, capture_output=True, text=True, timeout=20,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("AOTT_H025_RESOURCE_SOURCE_FIXTURE_PASS checks=224",
                      result.stdout)

    def test_lua51_syntax(self):
        if not shutil.which("luac5.1"):
            self.skipTest("Lua compiler unavailable")
        for name in ("prototypes/history/8311/h025_resource_probe.lua",
                     "tests/h025_resource_probe_fixture.lua"):
            with self.subTest(filename=name):
                result = subprocess.run(
                    ["luac5.1", "-p", str(ROOT / name)],
                    capture_output=True, text=True, timeout=10)
                self.assertEqual(result.returncode, 0, result.stderr)

    def test_source_preflight_is_read_only_not_installed(self):
        source = (SOURCE / "8311/h025_resource_probe.lua").read_text()
        self.assertNotIn("h025_resource_probe.lua",
                         (ROOT / "MANIFEST.json").read_text())
        self.assertFalse(
            (ROOT / "overlay/usr/lib/lua/8311/h025_resource_probe.lua").exists())
        for required in (
            'mode~="offline_synthetic"',
            '"direct_target_not_authorized"',
            'local MEM_PATH="/proc/meminfo"',
            'local CPU_PATH="/proc/stat"',
            'local SELF_PATH="/proc/self/status"',
            'local TEMP_PATH="/sys/class/thermal/thermal_zone0/temp"',
            'native.read_once(provider)',
            'hardware_qualified=false',
            'approved_for_service_start=false',
            'measured_on_production_board=false',
            'boot_epoch_identity_exported=false',
            'raw_eth_counters_exported=false',
        ):
            self.assertIn(required, source)
        active = "\n".join(line for line in source.splitlines()
                           if not line.lstrip().startswith("--"))
        for forbidden in ("os.execute(", "io.open(", "io.popen(",
                          "socket.", "nixio.exec", "uci:commit",
                          "fwenv_set", "fs.writefile(", "/dev/mtd",
                          "setInterval(", "cron("):
            self.assertNotIn(forbidden, active)


class H025EvidenceScreenTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not shutil.which("lua5.1"):
            raise unittest.SkipTest("Host Lua unavailable for actual sample")
        cls.snapshot = synthetic_snapshot()

    def data(self):
        return sample_set(self.snapshot)

    def test_synthetic_good_reports_only_candidate_not_hardware_pass(self):
        d = model.screen(self.data())
        self.assertEqual(d["screen_status"],
                         "reported_values_in_hypothetical_range")
        self.assertTrue(d["candidate_numeric_in_range"])
        self.assertEqual(d["issues"], [])
        self.assertFalse(d["hardware_qualified"])
        self.assertFalse(d["direct_hardware_authorized"])
        self.assertFalse(d["production_activation_approved"])
        self.assertFalse(d["forwarding_and_isp_availability_qualified"])
        self.assertFalse(d["native_cpu_ram_thermal_qualified"])
        self.assertTrue(d["requires_separately_authorized_direct_target_readback"])
        self.assertEqual(d["phases"]["load"]["sample_count"], 10)
        self.assertEqual(d["phases"]["recovery"]["required_minimum"], 3)

    def test_cpu_memory_rss_temp_and_window_limits_all_fail_closed(self):
        cases = (
            ("cpu_busy_fraction", .92, "cpu_load_exceeds_candidate_load"),
            ("mem_available_kib", 8192, "memory_headroom_below_candidate_load"),
            ("current_process_rss_kib", 10000, "process_rss_exceeds_candidate_load"),
            ("thermal_zone0_millidegc", 90000, "thermal_exceeds_candidate_load"),
            ("native_observation_window_seconds", 12,
             "observation_duration_exceeds_candidate_load"),
        )
        for field, val, reason in cases:
            with self.subTest(field=field):
                data = self.data()
                data["phase_samples"]["load"][2][field] = val
                d = model.screen(data)
                self.assertFalse(d["candidate_numeric_in_range"])
                self.assertIn(reason, d["issues"])
                self.assertFalse(d["hardware_qualified"])
                self.assertFalse(d["production_activation_approved"])

    def test_missing_sensor_and_cpu_samples_are_not_zeros(self):
        for field, state in (
            ("cpu_busy_fraction", "cpu_sample_status"),
            ("mem_total_kib", "memory_sample_status"),
            ("mem_available_kib", "memory_sample_status"),
            ("thermal_zone0_millidegc", "temperature_sample_status"),
            ("current_process_rss_kib", "process_memory_status"),
        ):
            with self.subTest(field=field):
                data = self.data()
                sample = data["phase_samples"]["idle"][0]
                sample[field] = None
                sample[state] = "unavailable"
                if field in ("mem_total_kib","mem_available_kib"):
                    sample["mem_total_kib"] = None
                    sample["mem_available_kib"] = None
                result = model.screen(data)
                self.assertFalse(result["candidate_numeric_in_range"])
                self.assertIn("unavailable_" + field + "_idle",
                              result["issues"])
                self.assertFalse(result["hardware_qualified"])

    def test_omitted_lua_nil_optional_field_means_unknown(self):
        data = self.data()
        example = data["phase_samples"]["recovery"][0]
        del example["thermal_zone0_millidegc"]
        example["temperature_sample_status"] = "unavailable"
        result = model.screen(data)
        self.assertFalse(result["candidate_numeric_in_range"])
        self.assertIn("unavailable_thermal_zone0_millidegc_recovery",
                      result["issues"])

    def test_provenance_boot_identity_and_private_fields_rejected(self):
        alterations = (
            ("serial", "FAKE_PRIVATE_ID"),
            ("raw_counter", "12345"),
            ("auth_token", "DO_NOT_EXPORT"),
        )
        for key, val in alterations:
            with self.subTest(key=key):
                data = self.data()
                data["phase_samples"]["load"][0][key] = val
                with self.assertRaisesRegex(ValueError,
                                            "unexpected_sample_fields"):
                    model.screen(data)

    def test_hardware_claims_cannot_be_spoofed(self):
        for field in model.REQUIRED_FALSE:
            with self.subTest(field=field):
                d = self.data()
                d["phase_samples"]["load"][0][field] = True
                with self.assertRaisesRegex(
                    ValueError,"forbidden_qualification_assertion"):
                    model.screen(d)
        d = self.data()
        d["evidence_origin"] = "direct_authorized"
        with self.assertRaisesRegex(ValueError,"only_unattested_evidence"):
            model.screen(d)

    def test_missing_phase_sample_count_never_qualifies(self):
        data = self.data()
        data["phase_samples"]["recovery"] = data[
            "phase_samples"]["recovery"][:1]
        result = model.screen(data)
        self.assertFalse(result["candidate_numeric_in_range"])
        self.assertIn("insufficient_samples_recovery",result["issues"])

    def test_outage_not_inferred_from_pon_and_host_missing(self):
        for key in ("pon_observation", "host_link_observation",
                    "host_counters_observation"):
            with self.subTest(key=key):
                data = self.data()
                row=data["phase_samples"]["idle"][0]
                row[key] = "unavailable"
                if key=="pon_observation":
                    row["actual_pon_state"]=None
                if key=="host_link_observation":
                    row["observed_host_link_mbps"]=None
                result = model.screen(data)
                self.assertFalse(result["candidate_numeric_in_range"])
                self.assertFalse(result["forwarding_and_isp_availability_qualified"])

    def test_invalid_types_bool_as_int_nan_and_bad_fields_rejected(self):
        pairs=(
            ("native_observation_window_seconds",float("nan")),
            ("cpu_busy_fraction",float("inf")),
            ("mem_total_kib",True),
            ("source_interface","unknown_device"),
            ("pon_observation","all_connected_to_internet"),
        )
        for field,val in pairs:
            with self.subTest(field=field):
                d=self.data()
                d["phase_samples"]["idle"][0][field]=val
                with self.assertRaises(ValueError):
                    model.screen(d)

    def test_cli_rejects_duplicate_keys_and_nonfinite_constants(self):
        with tempfile.TemporaryDirectory() as t:
            path=Path(t)/"untrusted.json"
            for literal in (
                '{"schema":1,"schema":1}',
                '{"schema":NaN}',
                '{"schema":Infinity}',
            ):
                with self.subTest(literal=literal):
                    path.write_text(literal,encoding="utf-8")
                    result=subprocess.run(
                        [sys.executable,str(SCREEN),"--input",str(path)],
                        capture_output=True,text=True,timeout=10,
                    )
                    self.assertEqual(result.returncode,2)
                    denied=json.loads(result.stdout)
                    self.assertFalse(denied["hardware_qualified"])
                    self.assertFalse(denied["production_activation_approved"])

    def test_cli_bounded_file_and_no_external_target(self):
        with tempfile.TemporaryDirectory() as t:
            path=Path(t)/"synthetic-evidence.json"
            path.write_text(json.dumps(self.data()),encoding="utf-8")
            r=subprocess.run([sys.executable,str(SCREEN),"--input",str(path)],
                             capture_output=True,text=True,timeout=10)
            self.assertEqual(r.returncode,0,r.stderr)
            d=json.loads(r.stdout)
            self.assertFalse(d["production_activation_approved"])
            self.assertTrue(d["candidate_numeric_in_range"])
            r=subprocess.run([sys.executable,str(SCREEN),"--input",
                              str(path), "--target", "any"],
                             capture_output=True,text=True,timeout=10)
            self.assertNotEqual(r.returncode,0)
            self.assertIn("unrecognized arguments",r.stderr)
            path.write_text("{" + "x"*model.MAX_INPUT_BYTES + "}",
                            encoding="utf-8")
            r=subprocess.run([sys.executable,str(SCREEN),"--input",str(path)],
                             capture_output=True,text=True,timeout=10)
            self.assertEqual(r.returncode,2)
            d=json.loads(r.stdout)
            self.assertFalse(d["hardware_qualified"])
            self.assertFalse(d["production_activation_approved"])


class H025ReferenceABITests(unittest.TestCase):
    def test_reference_rootfs_if_supplied(self):
        if not os.getenv("AOTT_VENDOR_ROOTFS"):
            self.skipTest("Offline vendor firmware rootfs unavailable")
        r=abi.preflight(VENDOR)
        self.assertTrue(r["all_required_binary_checks_passed"],r["issues"])
        self.assertEqual(r["reference_abi"],"mips32_big_endian")
        self.assertEqual(len(r["binary_checks"]),5)
        self.assertFalse(r["executed_native_pon_or_ethtool"])
        self.assertFalse(r["hardware_qualified"])

    def test_invalid_elf_reference_never_becomes_hardware_pass(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t)
            for relative in abi.REQUIRED_MIPS:
                file=root/relative
                file.parent.mkdir(parents=True,exist_ok=True)
                file.write_bytes(b"NOT_MIPS")
                file.chmod(0o755)
            busybox=root/"bin/busybox"
            target=root/"usr/bin/timeout"
            target.symlink_to("../../bin/busybox")
            response=abi.preflight(root)
            self.assertFalse(response["all_required_binary_checks_passed"])
            self.assertGreaterEqual(len(response["issues"]),5)
            self.assertFalse(response["hardware_qualified"])
            self.assertFalse(response["production_activation_approved"])
            self.assertEqual(abi.inspect_elf(busybox),
                             (False,"not_elf"))


if __name__ == "__main__":
    unittest.main()
