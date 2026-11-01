"""Offline verification of the proposed durable r8 monitoring record.

All tests operate in fresh temporary directories, never /ptconf or a device.
"""
import importlib.util
import json
from pathlib import Path
import os
import stat
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "monitor_persist_lab", ROOT / "tools/qualify_monitor_persistence.py"
)
lab = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(lab)


class OfflineMonitoringPersistenceLabTests(unittest.TestCase):
    def test_safe_atomic_write_rotation_and_revocation(self):
        with tempfile.TemporaryDirectory(prefix="aott-monitor-test-") as d:
            directory = Path(d) / "private"
            directory.mkdir(mode=0o700)
            v = lab.synthetic_record()
            p = lab.write_atomic(directory, lab.canonical(v))
            self.assertEqual(lab.read_record(p), v)
            before = p.stat()
            self.assertEqual(stat.S_IMODE(before.st_mode), 0o600)
            self.assertEqual(before.st_nlink, 1)
            disabled = dict(v, aott_metrics="0", aott_metrics_sha256="")
            lab.write_atomic(directory, lab.canonical(disabled))
            self.assertEqual(lab.read_record(p), disabled)
            new = dict(v, aott_metrics_sha256="b"*64)
            lab.write_atomic(directory, lab.canonical(new))
            self.assertEqual(lab.read_record(p), new)

    def test_invalid_schema_and_disabled_token_rules(self):
        baseline = lab.synthetic_record()
        cases = [
            {"schema": 2},
            {"log_remote": "yes"},
            {"log_ip": "bad;value"},
            {"log_ip": "..example.com"},
            {"log_port": "0"},
            {"log_port": "65536"},
            {"log_proto": "tls"},
            {"aott_metrics": "yes"},
            {"aott_metrics_client": "192" + ".0.2.40/32"},
            {"aott_metrics_client": "224" + ".0.0.1"},
            {"aott_metrics_sha256": "a"*63},
            {"aott_metrics": "1", "aott_metrics_sha256": ""},
            {"aott_metrics": "1", "aott_metrics_client": ""},
        ]
        for patch in cases:
            with self.subTest(patch=patch):
                values = dict(baseline, **patch)
                with self.assertRaises(ValueError):
                    lab.validate(values)
        extra = dict(baseline, unknown="do-not-allow")
        with self.assertRaises(ValueError):
            lab.validate(extra)

    def test_duplicate_json_fields_rejected(self):
        with tempfile.TemporaryDirectory(prefix="aott-monitor-test-") as d:
            directory = Path(d) / "private"
            directory.mkdir(mode=0o700)
            original = lab.canonical(lab.synthetic_record()).decode().strip()
            duplicate = original.replace('"schema":1', '"schema":1,"schema":1')
            file = directory / "config.json"
            file.write_text(duplicate)
            file.chmod(0o600)
            with self.assertRaises(ValueError):
                lab.read_record(file)

    def test_link_or_unsafe_permissions_rejected(self):
        with tempfile.TemporaryDirectory(prefix="aott-monitor-test-") as d:
            directory = Path(d) / "private"
            directory.mkdir(mode=0o700)
            p = lab.write_atomic(directory, lab.canonical(lab.synthetic_record()))
            p.chmod(0o644)
            with self.assertRaises(ValueError):
                lab.read_record(p)
            p.chmod(0o600)
            symlink = directory / "copy.json"
            symlink.symlink_to(p)
            with self.assertRaises(ValueError):
                lab.read_record(symlink)
            p.unlink()
            p.symlink_to(symlink)
            with self.assertRaises(ValueError):
                lab.write_atomic(directory, lab.canonical(lab.synthetic_record()))

    def test_refuse_persistent_target_name(self):
        with tempfile.TemporaryDirectory(prefix="aott-monitor-test-") as d:
            private = Path(d) / "8311-monitoring"
            private.mkdir(mode=0o700)
            with self.assertRaises(ValueError):
                lab.write_atomic(private, lab.canonical(lab.synthetic_record()))

    def test_no_python_stores_or_infers_production_credentials(self):
        value = lab.synthetic_record()
        self.assertNotIn("collector_token", value)
        self.assertEqual(len(value["aott_metrics_sha256"]), 64)
        self.assertEqual(value["log_ip"], "collector.example.com")
        self.assertEqual(value["aott_metrics_client"], "192" + ".0.2.40")


if __name__ == "__main__":
    unittest.main()
