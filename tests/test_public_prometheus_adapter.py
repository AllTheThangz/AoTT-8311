"""External Prometheus adapter tests. No sockets or vendor firmware required."""
import importlib.util
import io
import json
from pathlib import Path
import os
import stat
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "examples/monitoring/prometheus_json_adapter.py"
spec = importlib.util.spec_from_file_location("aott_external_exporter", SRC)
adapter = importlib.util.module_from_spec(spec)
spec.loader.exec_module(adapter)
URL = "https://onu.example.net/cgi-bin/luci/8311/metrics"
TOKEN = "a" * 64


class FakeResponse:
    def __init__(self, value, status=200):
        self.status = status
        self.content = value
    def __enter__(self):
        return self
    def __exit__(self, *args):
        return False
    def read(self, limit):
        return self.content[:limit]


class ExternalPrometheusAdapterTests(unittest.TestCase):
    def test_only_exact_https_metrics_path_is_accepted(self):
        self.assertEqual(adapter.validate_endpoint(URL), URL)
        for path in (
            "http://onu.example.net/cgi-bin/luci/8311/metrics",
            "https://user:" + "pass" + "@" + "onu.example.net/cgi-bin/luci/8311/metrics",
            URL + "?token=secret",
            URL + "#fragment",
            "https://onu.example.net/cgi-bin/luci/admin/8311/metrics",
            "https://onu.example.net/metrics",
        ):
            with self.subTest(path=path):
                with self.assertRaises(ValueError):
                    adapter.validate_endpoint(path)

    def test_metrics_schema_has_only_known_numeric_fields(self):
        sample = {
            "rx_power_dBm": -13.82,
            "ploam_state": 51,
            "cpu1_tempC": None,
            "tx_power_dBm": True,
            "untrusted_peer_ip": "192" + ".0.2.123",
            "tx_bias_mA": float("nan"),
            "optic_tempC": float("inf"),
            "module_voltage": 3.3,
        }
        text = adapter.as_prometheus(sample, True).decode("ascii")
        self.assertIn("aott8311_collection_success 1", text)
        self.assertIn("aott8311_optic_receive_dbm -13.82", text)
        self.assertIn("aott8311_pon_registration_state 51", text)
        self.assertIn("aott8311_optic_supply_volts 3.3", text)
        self.assertNotIn("untrusted_peer_ip", text)
        self.assertNotIn("192" + ".0.2.123", text)
        self.assertNotIn("aott8311_cpu1_temperature_celsius ", text)
        self.assertNotIn("aott8311_optic_laser_bias_milliamps ", text)
        self.assertNotIn("aott8311_optic_transmit_dbm ", text)

    def test_success_and_minimum_interval_prevent_excessive_pon_reads(self):
        invocations = []
        now = [100.0]
        def fake_fetch(request, timeout, context):
            invocations.append((request, timeout, context))
            payload = json.dumps({"rx_power_dBm": -14.0, "ploam_state": 51}).encode()
            return FakeResponse(payload)
        exporter = adapter.CachedExporter(URL, TOKEN, poll_interval=60,
            fetch=fake_fetch, clock=lambda: now[0], context=object())
        result = exporter.response().decode()
        self.assertIn("aott8311_collection_success 1", result)
        self.assertIn("aott8311_optic_receive_dbm -14", result)
        self.assertEqual(len(invocations), 1)
        self.assertEqual(invocations[0][1], 5)
        self.assertEqual(invocations[0][0].get_header("X-aott-metrics-token"), TOKEN)
        for _ in range(100):
            now[0] += 0.1
            self.assertEqual(exporter.response().decode(), result)
        self.assertEqual(len(invocations), 1)
        now[0] += 51
        exporter.response()
        self.assertEqual(len(invocations), 2)

    def test_invalid_json_http_errors_and_network_errors_fail_closed(self):
        bad_payloads = [
            (b"{broken",200),
            (b"[]" ,200),
            (b"x" * (adapter.MAX_JSON+1),200),
            (b"{}" ,403),
        ]
        for payload,status in bad_payloads:
            with self.subTest(status=status, bytes=len(payload)):
                exporter = adapter.CachedExporter(URL,TOKEN,fetch=lambda req,timeout,context: FakeResponse(payload,status))
                text=exporter.response().decode()
                self.assertIn("aott8311_collection_success 0",text)
                self.assertNotIn("aott8311_optic_receive_dbm",text)
        def fail(*args,**kwargs):
            raise OSError("SENSITIVE_TEST_DATA_SHOULD_NOT_LEAK")
        exporter = adapter.CachedExporter(URL,TOKEN,fetch=fail)
        text = exporter.response().decode()
        self.assertIn("aott8311_collection_success 0",text)
        self.assertNotIn("SENSITIVE_TEST_DATA",text)
        self.assertNotIn(URL,text)
        self.assertNotIn(TOKEN,text)

    def test_huge_numeric_field_is_skipped_without_crash(self):
        data={"rx_power_dBm": int("9" * 900), "ploam_state": 51}
        rendered=adapter.as_prometheus(data, True).decode("ascii")
        self.assertIn("aott8311_collection_success 1",rendered)
        self.assertNotIn("aott8311_optic_receive_dbm ",rendered)
        self.assertIn("aott8311_pon_registration_state 51",rendered)

    def test_interval_cannot_exceed_device_budget(self):
        with self.assertRaises(ValueError):
            adapter.CachedExporter(URL,TOKEN,poll_interval=0.5)
        with self.assertRaises(ValueError):
            adapter.CachedExporter(URL,"not-a-token")

    def test_secret_file_is_regular_owned_private_and_nosymlink(self):
        with tempfile.TemporaryDirectory() as base:
            root=Path(base)
            file=root/"collector-token"
            file.write_text(TOKEN+"\n")
            file.chmod(0o600)
            self.assertEqual(adapter.read_token_file(file),TOKEN)
            file.chmod(0o644)
            with self.assertRaises(ValueError):
                adapter.read_token_file(file)
            file.chmod(0o600)
            linked=root/"linked-token"
            linked.symlink_to(file)
            with self.assertRaises(OSError):
                adapter.read_token_file(linked)

    def test_all_vendor_json_names_mapped_and_no_runtime_bundle(self):
        source=(ROOT/"overlay/usr/lib/lua/8311/tools.lua").read_text()
        fragment=source.split("function metric_names()",1)[1].split("end",1)[0]
        for key in adapter.FIELDS:
            self.assertIn('"' + key + '"',fragment)
        self.assertEqual(len(adapter.FIELDS),8)
        self.assertNotIn("no_certificate_check",SRC.read_text())
        self.assertIn('("127" + ".0.0.1", args.port)',SRC.read_text())


if __name__ == "__main__":
    unittest.main()
