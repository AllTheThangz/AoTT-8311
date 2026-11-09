"""Offline regression for the host-only passive PRX126 performance sampler."""
import importlib.util
import unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
TOOL=ROOT/"tools/bench_prx126_datapath_readonly.py"
spec=importlib.util.spec_from_file_location("performance_probe",TOOL)
m=importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

def sample(cpu,idle,rx,tx):
    return m.parse(
        "cpu_total=%s\ncpu_idle=%s\nlink_speed=10000\ncarrier=1\n"
        "rx_errors=0\ntx_errors=0\nrx_dropped=0\ntx_dropped=0\n"
        "thermal0=51000\nthermal1=49900\ndatapath_module=1\n"
        "mac_rx_good_bytes=%s\nmac_tx_good_bytes=%s\n" %
        (cpu,idle,rx,tx))

class PassiveProbeTests(unittest.TestCase):
    def test_two_samples_establish_measured_rates(self):
        a=sample(1000,700,100000,100000)
        b=sample(2000,1500,10100000,5100000)
        r=m.summarize(a,b,10)
        self.assertEqual(r["cpu_busy_percent"],20)
        self.assertEqual(r["observed_from_router_mbps"],8)
        self.assertEqual(r["observed_to_router_mbps"],4)
        self.assertTrue(r["vendor_datapath_module_detected"])
        self.assertFalse(r["offload_for_all_packets_proven"])
        self.assertFalse(r["isp_line_speed_proven"])
        self.assertFalse(r["live_changes_made"])

    def test_reset_is_not_rate(self):
        r=m.summarize(sample(100,50,10000,10000),
                      sample(200,110,5,3),10)
        self.assertIsNone(r["observed_from_router_mbps"])

    def test_reject_sensitive_or_malformed_fields(self):
        with self.assertRaises(m.ProbeError):
            m.parse("cpu_total=1\ncpu_idle=0\nlink_speed=10000\ncarrier=1\nsecret=23\n")
        with self.assertRaises(m.ProbeError):
            m.parse("cpu_total=1\ncpu_idle=0\nlink_speed=10000\ncarrier=1\ncarrier=1\n")
        self.assertNotIn("fwenv",m.REMOTE)
        self.assertNotIn("uci set",m.REMOTE)
        self.assertNotIn("192.168.",m.REMOTE)

    def test_no_one_sample_rate(self):
        with self.assertRaises(m.ProbeError):
            m.summarize(sample(100,50,10,20),sample(110,60,20,30),0)

if __name__=="__main__": unittest.main()
