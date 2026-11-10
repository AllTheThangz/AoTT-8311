"""Offline tests for the V3 P0 read-only profile and soak tools."""
from pathlib import Path
import importlib.util
import unittest

ROOT=Path(__file__).resolve().parents[1]

def load(name,filename):
    spec=importlib.util.spec_from_file_location(name,ROOT/"tools"/filename)
    module=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

profile=load("p0_profile_preflight","p0_candidate_profile_preflight.py")
soak=load("p0_soak_probe","p0_soak_readonly.py")

def pin(value):
    return ("file candidate etc/version "+str(len(value))+" "+value+"\n").encode()

BASE=(b"profile potron-prx126-aott-v1\n"
      b"target WAS-110\nvariant basic\n"
      +("component kernel 100 "+"0"*64+"\n").encode()
      +("component bootcore 100 "+"1"*64+"\n").encode()
      +("file common etc/openwrt_release 4 "+"2"*64+"\n").encode())
OLD=BASE+pin("a"*64)
NEW=BASE+pin("b"*64)

class P0CandidateProfileUnitTests(unittest.TestCase):
    def test_same_profile_has_no_candidate_delta(self):
        result=profile.check(OLD,OLD,OLD)
        self.assertTrue(result["same_candidate_runtime_pins"])
        self.assertFalse(result["requires_version_aware_device_qualification"])
        self.assertFalse(result["device_write_performed"])

    def test_cross_version_candidate_is_detected_before_write(self):
        result=profile.check(OLD,NEW,NEW)
        self.assertFalse(result["same_candidate_runtime_pins"])
        self.assertEqual(result["candidate_runtime_changed_records"],1)
        self.assertTrue(result["requires_version_aware_device_qualification"])

    def test_embedded_candidate_must_match_independent_review(self):
        with self.assertRaisesRegex(ValueError,"embedded_profile"):
            profile.check(OLD,OLD,NEW)

    def test_protected_kernel_and_common_file_changes_rejected(self):
        with self.assertRaisesRegex(ValueError,"protected_common"):
            profile.check(OLD,NEW.replace(b"component kernel 100 ",b"component kernel 200 "),
                          NEW.replace(b"component kernel 100 ",b"component kernel 200 "))

    def test_duplicates_and_bad_path_rejected(self):
        with self.assertRaisesRegex(ValueError,"duplicate"):
            profile.entries(OLD+pin("a"*64))
        with self.assertRaisesRegex(ValueError,"size"):
            profile.entries(b"X"*70000)

class P0SoakUnitTests(unittest.TestCase):
    def row(self,uptime="12.25",errors=0):
        return ("uptime="+uptime+"\nspeed=10000\ncarrier=1\n"
                +"rx_errors="+str(errors)+"\ntx_errors=0\n"
                +"rx_dropped=0\ntx_dropped=0\n"
                +"thermal0=52080\nthermal1=50880\navailable_kb=395716\npon_state=51\n"
                +"ubi_bad_peb_count=0\nubi_max_ec=11\n"
                +"ubi_reserved_for_bad=20\nubi_avail_eraseblocks=307\n")
    def test_decoding_and_no_invented_pon_state(self):
        x=soak.decode(self.row())
        self.assertEqual(x["pon_state"],51)
        self.assertEqual(x["speed"],10000)
        y=soak.decode(self.row().replace("pon_state=51","pon_state="))
        self.assertIsNone(y["pon_state"])
    def test_rejects_unexpected_secret_or_duplicate_output(self):
        with self.assertRaisesRegex(ValueError,"unknown"):
            soak.decode(self.row()+"loid=hidden\n")
        with self.assertRaisesRegex(ValueError,"duplicate"):
            soak.decode(self.row()+"carrier=1\n")
    def test_transitions_and_counter_errors(self):
        a=soak.decode(self.row())
        b=soak.decode(self.row(uptime="22.25",errors=2))
        b["pon_state"]=41
        s=soak.analyze([{"state":"observed","metrics":a},
                        {"state":"observed","metrics":b}])
        self.assertEqual(s["pon_state_transitions_observed"],1)
        self.assertEqual(s["ethernet_error_drop_deltas"]["rx_errors"],2)
        self.assertEqual(s["peak_thermal_c"],[52.08,50.88])
        self.assertEqual(s["ubi_bad_peb_growth_observed"],0)
        self.assertEqual(s["ubi_peak_erase_count_observed"],11)
        self.assertEqual(s["ubi_min_available_eraseblocks_observed"],307)
        self.assertFalse(s["three_layer_internet_verified"])
    def test_reboot_resets_counters_not_negative_deltas(self):
        a=soak.decode(self.row(uptime="800",errors=60))
        b=soak.decode(self.row(uptime="12",errors=1))
        s=soak.analyze([{"state":"observed","metrics":a},
                        {"state":"unavailable","reason":"ssh_probe_unavailable"},
                        {"state":"observed","metrics":b}])
        self.assertEqual(s["reboots_observed"],1)
        self.assertEqual(s["probe_gaps"],1)
        self.assertEqual(s["ethernet_error_drop_deltas"]["rx_errors"],0)
    def test_ubi_bad_peb_growth_and_missing_sysfs(self):
        a=soak.decode(self.row())
        b=soak.decode(self.row(uptime="22.25").replace(
            "ubi_bad_peb_count=0","ubi_bad_peb_count=2").replace(
            "ubi_max_ec=11","ubi_max_ec=13").replace(
            "ubi_avail_eraseblocks=307","ubi_avail_eraseblocks=301"))
        c=soak.decode(self.row(uptime="34.25").replace(
            "ubi_bad_peb_count=0","ubi_bad_peb_count="))
        records=[{"state":"observed","metrics":i} for i in (a,b,c)]
        summary=soak.analyze(records)
        self.assertEqual(summary["ubi_bad_peb_growth_observed"],2)
        self.assertEqual(summary["ubi_peak_erase_count_observed"],13)
        self.assertEqual(summary["ubi_min_available_eraseblocks_observed"],301)
        self.assertEqual(summary["ubi_bad_peb_samples_unavailable"],1)
        self.assertIsNone(c["ubi_bad_peb_count"])
    def test_ubi_reboot_does_not_invent_bad_peb_growth(self):
        a=soak.decode(self.row(uptime="800").replace(
            "ubi_bad_peb_count=0","ubi_bad_peb_count=4"))
        b=soak.decode(self.row(uptime="12.5"))
        summary=soak.analyze([
            {"state":"observed","metrics":a},{"state":"observed","metrics":b}])
        self.assertEqual(summary["reboots_observed"],1)
        self.assertEqual(summary["ubi_bad_peb_growth_observed"],0)

if __name__=="__main__":
    unittest.main()
