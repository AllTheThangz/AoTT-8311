"""H-027: actual vendor-MIPS lifecycle-to-IPC owner-aware handoff.

All PON and host values are fixed synthetic callbacks. Tests spawn
separate MIPS Lua processes using the extracted vendor nixio, fcntl and
jsonc libraries in root-owned disposable host directories.
"""
import concurrent.futures
import os
from pathlib import Path
import secrets
import shutil
import signal
import subprocess
import unittest

ROOT=Path(__file__).resolve().parents[1]
SOURCE=ROOT/"prototypes/history"
OVERLAY=ROOT/"overlay/usr/lib/lua"
FIXTURE=ROOT/"tests/h027_lifecycle_snapshot_fixture.lua"
VENDOR=Path(os.environ.get("AOTT_VENDOR_ROOTFS",
                           "/missing/offline-vendor-rootfs"))


class LifecycleSnapshotSourceTests(unittest.TestCase):
    def test_host_lua_syntax(self):
        if not shutil.which("luac5.1"):
            self.skipTest("Lua compiler unavailable")
        for file in (
            SOURCE/"8311/history_process_lock.lua",
            SOURCE/"8311/history_snapshot_ipc.lua",
            SOURCE/"8311/history_http_readonly.lua",
            SOURCE/"8311/history_lifecycle.lua",
            SOURCE/"8311/history_luci_route_candidate.lua",
            ROOT/"tests/h027_luci_route_fixture.lua",
            FIXTURE,
        ):
            with self.subTest(path=file.name):
                r=subprocess.run(["luac5.1","-p",str(file)],
                                 capture_output=True,text=True,timeout=10)
                self.assertEqual(r.returncode,0,r.stderr)

    def test_production_inactive_and_lifecycle_bound(self):
        life=(SOURCE/"8311/history_lifecycle.lua").read_text()
        lock=(SOURCE/"8311/history_process_lock.lua").read_text()
        ipc=(SOURCE/"8311/history_snapshot_ipc.lua").read_text()
        http=(SOURCE/"8311/history_http_readonly.lua").read_text()
        for fragment in (
            "function M.configure_snapshot(token,directory,mode)",
            '"snapshot_configuration_frozen"',
            'p.snapshots_published=p.snapshots_published+1',
            'p.snapshot_last_clock=now',
            'value.history_status=="reboot"',
            'p.snapshot_publish_failures=p.snapshot_publish_failures+1',
            '"snapshot_publish_failed"',
            '"snapshot_start_invalidation_unverified"',
            '"snapshot_invalidation_failed"',
            'source_only_not_deployed=true',
            'live_history_endpoint_installed=false',
        ):
            self.assertIn(fragment,life)
        for fragment in (
            'function M.writer_present(directory)',
            'fd:lock("tlock")',
            'errno==11 or errno==13',
            '"no_guarded_writer"',
            '"indeterminate_lock_contention"',
        ):
            self.assertIn(fragment,lock)
        for fragment in (
            'function M.read_guarded(directory,lock_directory,mode)',
            'lock.writer_present(lock_directory)',
            'guard_owner_checked_before_and_after=true',
            'function M.invalidate(handle,directory,mode)',
            '"snapshot_invalidation_inode_changed"',
            '"snapshot_invalidation_unverified"',
        ):
            self.assertIn(fragment,ipc)
        self.assertIn('function M.serve_guarded_offline_ipc(',http)
        self.assertIn('bridge.read_guarded(',http)
        luci=(SOURCE/"8311/history_luci_route_candidate.lua").read_text()
        for fragment in (
            'function M.prepare(dispatcher,http,util,snapshot_dir,lock_dir)',
            'function M.write(dispatcher,http,util,snapshot_dir,lock_dir)',
            'ctx.authsession',
            'ctx.authuser~="root"',
            'session.values.username~="root"',
            'pcall(util.ubus,"session","get"',
            'pcall(util.ubus,"session","access"',
            'endpoint.serve_guarded_offline_ipc({',
        ):
            self.assertIn(fragment,luci)

    def test_no_implicit_live_endpoint_or_deployment(self):
        manifest=(ROOT/"MANIFEST.json").read_text()
        deployed=(OVERLAY/"luci/controller/8311.lua").read_text()
        self.assertNotIn("history_data",deployed)
        for name in ("history_lifecycle.lua","history_snapshot_ipc.lua",
                     "history_process_lock.lua","history_http_readonly.lua",
                     "history_luci_route_candidate.lua"):
            self.assertNotIn(name,manifest)
            self.assertFalse((OVERLAY/"8311"/name).exists())
        for path in (
            SOURCE/"8311/history_lifecycle.lua",
            SOURCE/"8311/history_snapshot_ipc.lua",
            SOURCE/"8311/history_process_lock.lua",
        ):
            text=path.read_text()
            self.assertNotIn("fwenv_set",text)
            self.assertNotIn("uci:commit",text)
            self.assertNotIn("/dev/mtd",text)


class VendorMipsLifecycleSnapshotTests(unittest.TestCase):
    def setUp(self):
        self.snapshot_dir=None
        self.lock_dir=None
        self.children=[]
        if not os.environ.get("AOTT_VENDOR_ROOTFS"):
            self.skipTest("No extracted offline vendor rootfs")
        if os.geteuid()!=0:
            self.skipTest("Root-owned test directories require root")
        if not shutil.which("qemu-mips-static"):
            self.skipTest("MIPS interpreter emulator missing")
        if not (VENDOR/"usr/bin/lua").is_file() or not (
                VENDOR/"usr/lib/lua/nixio.so").is_file() or not (
                VENDOR/"usr/lib/lua/luci/jsonc.so").is_file():
            self.skipTest("Vendor MIPS Lua/nixio/jsonc incomplete")
        self.lock_dir=Path("/var/tmp/aott-h022-lock-test-"+secrets.token_hex(8))
        self.snapshot_dir=Path("/var/tmp/aott-h026-ipc-test-"+secrets.token_hex(8))
        self.lock_dir.mkdir(mode=0o700)
        self.snapshot_dir.mkdir(mode=0o700)

    def tearDown(self):
        for p in self.children:
            if p.poll() is None:
                p.kill()
            try:
                p.communicate(timeout=4)
            except subprocess.TimeoutExpired:
                p.kill()
                p.wait(timeout=4)
        for folder in (self.lock_dir,self.snapshot_dir):
            if folder and folder.exists():
                folder.chmod(0o700)
                shutil.rmtree(folder)

    def cmd(self,mode):
        return [
            "qemu-mips-static","-L",str(VENDOR),str(VENDOR/"usr/bin/lua"),
            str(FIXTURE),str(VENDOR),str(SOURCE),str(OVERLAY),
            str(self.lock_dir),str(self.snapshot_dir),mode,
        ]

    def run_luci(self,mode):
        command=[
            "qemu-mips-static","-L",str(VENDOR),str(VENDOR/"usr/bin/lua"),
            str(ROOT/"tests/h027_luci_route_fixture.lua"),str(VENDOR),
            str(SOURCE),str(OVERLAY),str(self.lock_dir),
            str(self.snapshot_dir),mode,
        ]
        p=subprocess.run(command,cwd=ROOT,capture_output=True,text=True,
                         timeout=14)
        self.assertEqual(p.returncode,0,p.stderr)
        expected=97 if mode=="active" else 94
        self.assertIn(
            f"AOTT_H027_LUCI_SOURCE_GATE_PASS checks={expected}",p.stdout)
        return p.stdout

    def run_mode(self,mode):
        p=subprocess.run(self.cmd(mode),cwd=ROOT,
                         capture_output=True,text=True,timeout=16)
        self.assertEqual(p.returncode,0,p.stderr)
        return p.stdout

    def begin(self,mode="hold"):
        child=subprocess.Popen(
            self.cmd(mode),cwd=ROOT,stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,stderr=subprocess.PIPE,
            text=True,bufsize=1)
        self.children.append(child)
        target=("AOTT_H027_START_WITHOUT_SNAPSHOT" if mode=="start_only_hold"
                else "AOTT_H027_SOURCE_PUBLISH_READY")
        self.assertIn(target,child.stdout.readline().strip())
        return child

    def release(self,p):
        p.stdin.write("\n")
        p.stdin.flush()
        stdout,stderr=p.communicate(timeout=10)
        self.assertEqual(p.returncode,0,stderr)
        return stdout

    def test_inert_luci_authentication_gate_without_active_collector(self):
        self.run_luci("inactive")
        self.assertFalse((self.snapshot_dir/"snapshot.json").exists())

    def test_inert_luci_authentication_gate_with_active_collector(self):
        writer=self.begin()
        self.run_luci("active")
        self.assertIn("AOTT_H027_SOURCE_STOP_PASS",self.release(writer))
        self.run_luci("inactive")

    def test_lifecycle_publishes_and_stops_revoking_cache(self):
        output=self.run_mode("run")
        self.assertIn("AOTT_H027_SOURCE_PUBLISH_READY",output)
        self.assertIn("AOTT_H027_SOURCE_STOP_PASS",output)
        self.assertFalse((self.snapshot_dir/"snapshot.json").exists())
        self.assertEqual(
            sorted(p.name for p in self.snapshot_dir.iterdir()),[])
        self.assertTrue((self.lock_dir/"collector.lock").is_file())
        self.assertIn("AOTT_H027_READER_DENIED",
                      self.run_mode("reader_denied"))

    def test_separate_process_reads_only_while_writer_alive(self):
        writer=self.begin()
        file=self.snapshot_dir/"snapshot.json"
        self.assertTrue(file.is_file())
        self.assertEqual(file.stat().st_mode & 0o777,0o600)
        self.assertIn("AOTT_H027_READER_PASS",self.run_mode("reader"))
        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as pool:
            results=list(pool.map(
                lambda _:self.run_mode("reader"),range(10)))
        self.assertTrue(all("AOTT_H027_READER_PASS" in x for x in results))
        self.assertIn("AOTT_H027_SOURCE_STOP_PASS",self.release(writer))
        self.assertFalse(file.exists())
        self.assertIn("AOTT_H027_READER_DENIED",
                      self.run_mode("reader_denied"))

    def test_unclean_exit_leaves_bytes_but_kernel_gate_blocks(self):
        writer=self.begin("crash")
        self.assertIn("AOTT_H027_READER_PASS",self.run_mode("reader"))
        stdout=self.release(writer)
        self.assertIn("AOTT_H027_UNCLEAN_EXIT_WITH_CACHE",stdout)
        self.assertTrue((self.snapshot_dir/"snapshot.json").is_file())
        self.assertIn("AOTT_H027_READER_DENIED",
                      self.run_mode("reader_denied"))

    def test_sigkill_does_not_leave_servable_history(self):
        writer=self.begin()
        self.assertIn("AOTT_H027_READER_PASS",self.run_mode("reader"))
        writer.send_signal(signal.SIGKILL)
        writer.wait(timeout=8)
        self.assertTrue((self.snapshot_dir/"snapshot.json").is_file())
        self.assertIn("AOTT_H027_READER_DENIED",
                      self.run_mode("reader_denied"))

    def test_restart_revokes_crashed_writer_cache_before_new_sample(self):
        writer=self.begin("crash")
        self.release(writer)
        leftover=self.snapshot_dir/"snapshot.json"
        self.assertTrue(leftover.is_file())
        replacement=self.begin("start_only_hold")
        self.assertFalse(leftover.exists())
        self.assertIn("AOTT_H027_READER_DENIED",
                      self.run_mode("reader_denied"))
        self.assertIn("AOTT_H027_SOURCE_STOP_PASS",
                      self.release(replacement))

    def test_interrupted_regular_stage_recovered_with_new_owner(self):
        first=self.run_mode("corrupt_stage")
        self.assertIn("AOTT_H027_PUBLISH_FAILURE_SAFE",first)
        self.assertTrue((self.snapshot_dir/"snapshot.json.new").is_file())
        second=self.run_mode("run")
        self.assertIn("AOTT_H027_SOURCE_STOP_PASS",second)
        self.assertFalse((self.snapshot_dir/"snapshot.json.new").exists())
        self.assertFalse((self.snapshot_dir/"snapshot.json").exists())
        self.assertIn("AOTT_H027_READER_DENIED",
                      self.run_mode("reader_denied"))

    def test_untrusted_symlink_stage_blocks_new_collector(self):
        protected=self.snapshot_dir/"inert-sentinel"
        protected.write_text("UNCHANGED")
        (self.snapshot_dir/"snapshot.json.new").symlink_to(protected)
        self.assertIn("AOTT_H027_UNSAFE_STAGE_BLOCKS_START",
                      self.run_mode("unsafe_stage"))
        self.assertEqual(protected.read_text(),"UNCHANGED")
        self.assertTrue((self.snapshot_dir/"snapshot.json.new").is_symlink())
        self.assertIn("AOTT_H027_READER_DENIED",
                      self.run_mode("reader_denied"))

    def test_failed_publish_goes_cooldown_and_drops_servable_data(self):
        output=self.run_mode("corrupt_stage")
        self.assertIn("AOTT_H027_PUBLISH_FAILURE_SAFE",output)
        self.assertFalse((self.snapshot_dir/"snapshot.json").exists())
        self.assertTrue((self.snapshot_dir/"snapshot.json.new").is_file())
        self.assertIn("AOTT_H027_READER_DENIED",
                      self.run_mode("reader_denied"))

    def test_failed_invalidation_closes_lock_and_marks_unsafe(self):
        output=self.run_mode("invalid_stop")
        self.assertIn("AOTT_H027_INVALID_STOP_SAFE",output)
        path=self.snapshot_dir/"snapshot.json"
        self.assertTrue(path.is_file())
        self.assertEqual(path.stat().st_mode & 0o777,0o644)
        self.assertIn("AOTT_H027_READER_DENIED",
                      self.run_mode("reader_denied"))

    def test_verified_reboot_restarts_snapshot_epoch(self):
        output=self.run_mode("reboot")
        self.assertIn("AOTT_H027_SOURCE_STOP_PASS",output)
        self.assertIn("checks=",output)
        self.assertFalse((self.snapshot_dir/"snapshot.json").exists())

    def test_no_writer_lock_file_is_never_proof_of_service(self):
        (self.lock_dir/"collector.lock").write_text("")
        (self.lock_dir/"collector.lock").chmod(0o600)
        self.assertIn("AOTT_H027_READER_DENIED",
                      self.run_mode("reader_denied"))
        self.assertEqual((self.lock_dir/"collector.lock").stat().st_size,0)


if __name__=="__main__":
    unittest.main()
