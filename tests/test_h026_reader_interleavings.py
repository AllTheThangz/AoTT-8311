"""Deterministic snapshot interleavings, not timing-dependent sleep tests.

The test parent republishes only after the actual vendor-MIPS reader reports
its barrier. All data is synthetic and all filesystem access is disposable.
"""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import select
import shutil
import subprocess
import unittest

import test_h026_snapshot_ipc as ipc_tests

ROOT=Path(__file__).resolve().parents[1]
FIXTURE=ROOT/"tests/h026_reader_interleaving_fixture.lua"


class InterleavingSyntaxTests(unittest.TestCase):
    def test_fixture_is_lua51(self):
        if not shutil.which("luac5.1"):
            self.skipTest("Host Lua compiler missing")
        out=subprocess.run(["luac5.1","-p",str(FIXTURE)],capture_output=True,
                           text=True,timeout=5)
        self.assertEqual(out.returncode,0,out.stderr)


class VendorReaderInterleavingTests(unittest.TestCase):
    def setUp(self):
        self.helper=ipc_tests.VendorMipsSnapshotProcessTests()
        self.helper.setUp()
        self.children=[]
        self.helper.invoke("publish")

    def tearDown(self):
        try:
            for child in self.children:
                if child.poll() is None:
                    child.kill()
                child.communicate(timeout=5)
        finally:
            self.helper.tearDown()

    def force_interleaving(self,mode,point,expected_marker):
        command=["qemu-mips-static","-L",str(ipc_tests.VENDOR),
                 str(ipc_tests.VENDOR/"usr/bin/lua"),str(FIXTURE),
                 str(ipc_tests.VENDOR),str(ipc_tests.HISTORY),str(ipc_tests.OVERLAY),
                 str(self.helper.snapshot_dir),mode]
        child=subprocess.Popen(command,cwd=ROOT,stdin=subprocess.PIPE,
                               stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
        self.children.append(child)
        self.assertTrue(select.select([child.stdout],[],[],10)[0],
                        "Reader failed to reach the explicit barrier")
        self.assertEqual(child.stdout.readline().strip(),"AOTT_H026_READER_READY:"+point)
        self.helper.invoke("republish")
        output,error=child.communicate("continue\n",timeout=15)
        self.assertEqual(child.returncode,0,error)
        self.assertIn(expected_marker,output)
        self.assertIn("AOTT_H026_CROSS_PROCESS_READ_PASS",self.helper.invoke("read"))

    def test_new_publication_between_distinct_reads_is_not_corruption(self):
        self.force_interleaving("between_reads","first_read_complete",
                                "AOTT_H026_DISTINCT_GENERATIONS_PASS")

    def test_replacement_between_stat_and_open_is_refused(self):
        self.force_interleaving("before_open","before_open",
                                "AOTT_H026_MID_READ_REFUSAL_PASS")

    def test_replacement_before_final_stat_is_refused(self):
        self.force_interleaving("before_final_stat","before_final_stat",
                                "AOTT_H026_MID_READ_REFUSAL_PASS")

    def test_http_replacement_before_open_returns_only_generic_503(self):
        self.force_interleaving("http_before_open","before_open",
                                "AOTT_H026_MID_READ_REFUSAL_PASS")

    def test_http_replacement_before_final_stat_returns_only_generic_503(self):
        self.force_interleaving("http_before_final_stat","before_final_stat",
                                "AOTT_H026_MID_READ_REFUSAL_PASS")

    def test_concurrent_fixture_does_not_treat_any_unavailable_as_success(self):
        target=self.helper.snapshot_dir/ipc_tests.SNAPSHOT
        valid=target.read_bytes()
        for label in ("missing","corrupt","unsafe_permissions"):
            with self.subTest(case=label):
                target.write_bytes(valid)
                target.chmod(0o600)
                if label=="missing":
                    target.unlink()
                elif label=="corrupt":
                    target.write_bytes(b'{"private":"SYNTHETIC_DO_NOT_ECHO"}')
                else:
                    target.chmod(0o644)
                result=subprocess.run(self.helper.command("read_concurrent"),cwd=ROOT,
                    capture_output=True,text=True,timeout=15)
                self.assertNotEqual(result.returncode,0)
                self.assertIn("only_verified_race_refusal",result.stderr)
                self.assertNotIn("SYNTHETIC_DO_NOT_ECHO",result.stdout+result.stderr)
                self.assertNotIn("AOTT_H026_CONCURRENT_READ_VALID",result.stdout)
        target.write_bytes(valid)
        target.chmod(0o600)
        self.helper.invoke("read")

    def test_repeated_concurrent_readers_accept_whole_generations_or_exact_refusal(self):
        successes=0
        with ThreadPoolExecutor(max_workers=8) as pool:
            for round_number in range(8):
                futures=[pool.submit(self.helper.invoke,"read_concurrent") for _ in range(8)]
                self.helper.invoke("republish" if round_number%2==0 else "publish")
                for future in futures:
                    output=future.result(timeout=15)
                    self.assertRegex(output,
                        r"AOTT_H026_CONCURRENT_READ_(VALID samples=[34]|REFUSED code="
                        r"snapshot_(inode_changed|readback_unverified))")
                    successes+=int("AOTT_H026_CONCURRENT_READ_VALID" in output)
        self.assertGreater(successes,0,"Permanent refusal is not a successful reader")
        self.helper.invoke("read")


if __name__=="__main__":
    unittest.main()
