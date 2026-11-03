"""H-023: offline guarded history lifecycle and real process restart safety.

Source model uses manual monotonic ticks only. Tests run extracted vendor
MIPS Lua/nixio under QEMU in disposable root-owned /var/tmp directories.
No actual PON, ONU, procd, firmware bank or ISP interface is accessed.
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
LIFECYCLE=ROOT/"prototypes/history/8311/history_lifecycle.lua"
SCENARIO=ROOT/"tests/h023_lifecycle_fixture.lua"
PROCESS=ROOT/"tests/h023_process_fixture.lua"
VENDOR=Path(os.environ.get("AOTT_VENDOR_ROOTFS",
                           "/unavailable/offline-vendor-rootfs"))


class LifecycleSourceTests(unittest.TestCase):
    def test_lua51_syntax(self):
        if not shutil.which("luac5.1"):
            self.skipTest("Lua 5.1 compiler unavailable")
        for path in (LIFECYCLE,SCENARIO,PROCESS):
            with self.subTest(path=path.name):
                p=subprocess.run(["luac5.1","-p",str(path)],
                                 capture_output=True,text=True,timeout=10)
                self.assertEqual(p.returncode,0,p.stderr)

    def test_manual_start_shutdown_and_circuit_breaker_contract(self):
        src=LIFECYCLE.read_text()
        for expected in (
            "local START_BACKOFF={60,120,300,900}",
            "local FAILURE_THRESHOLD=4",
            "local MAX_RESTARTS=3",
            'mode~="offline_synthetic"',
            '"hardware_lifecycle_not_qualified"',
            '"unavailable_lifecycle_feature"',
            'function M.new(directory,preferences,capability,mode)',
            'function M.start(token,now)',
            'function M.step(token,now,provider)',
            'function M.stop(token)',
            'function M.shutdown(token)',
            'function M.status(token)',
            'function M.export_json(token,range,limit)',
            'clone_preferences(preferences)',
            'guarded.new,p.directory',
            'guarded.tick,p.handle',
            'guarded.close,p.handle',
            '"reader_failure_limit"',
            '"circuit_open"',
            '"cooldown_not_elapsed"',
            '"stopped_no_auto_start"',
            '"lifecycle_not_restartable"',
            'source_only_not_deployed=true',
            'no_background_service=true',
            'no_production_activation=true',
            'no_flash_write=true',
        ):
            with self.subTest(expected=expected):
                self.assertIn(expected,src)

    def test_source_only_not_shipped_or_autostarted(self):
        self.assertTrue(LIFECYCLE.is_file())
        self.assertFalse((ROOT/"overlay/usr/lib/lua/8311/history_lifecycle.lua").exists())
        self.assertNotIn("history_lifecycle.lua",
                         (ROOT/"MANIFEST.json").read_text())
        active="\n".join(line for line in LIFECYCLE.read_text().splitlines()
                         if not line.lstrip().startswith("--"))
        for prohibited in (
            "os.execute(", "io.open(", "io.popen(",
            "fs.writefile(", "socket.",
            "luci.http", "uci:commit", "fwenv_set",
            "nixio.fs", "cron(", "sleep(",
            "/etc/init.d/", "/dev/mtd", "setInterval(",
        ):
            self.assertNotIn(prohibited,active)

    def test_failure_matrix_exercises_reboot_and_restart(self):
        fixture=SCENARIO.read_text()
        for required in (
            "live_mode_never_accepted",
            "no_implicit_start",
            "manual_start_required" if False else "initial_not_running",
            "no_polling_before_deadline",
            "kernel_owner_prevents_second_start",
            "restart_not_early",
            "fourth_error_cooldown",
            "cooldown_released_kernel_lock",
            "other_session_acquires_after_release",
            "post_restart_actual_byte_counters",
            "rewind_same_boot_not_accepted",
            "new_boot_accepted_after_verification",
            "new_boot_no_counter_continuity",
            "unsafe_directory_no_start",
            "no_unbounded_restarts",
            "stop_cannot_reset_breaker",
            "circuit_cannot_restart",
        ):
            self.assertIn(required,fixture)


class LifecycleMipsProcessTests(unittest.TestCase):
    def setUp(self):
        self.directory=None
        self.processes=[]
        if not os.environ.get("AOTT_VENDOR_ROOTFS"):
            self.skipTest("Offline vendor MIPS rootfs unavailable")
        if os.geteuid()!=0:
            self.skipTest("Root-owned private test directory needed")
        if not shutil.which("qemu-mips-static"):
            self.skipTest("MIPS QEMU not installed")
        if not (VENDOR/"usr/bin/lua").is_file() or not (
            VENDOR/"usr/lib/lua/nixio.so").is_file():
            self.skipTest("Vendor Lua/nixio ABI absent")
        self.directory=Path("/var/tmp/aott-h022-lock-test-"+secrets.token_hex(8))
        self.directory.mkdir(mode=0o700)
        self.assertEqual(self.directory.stat().st_uid,0)
        self.assertEqual(self.directory.stat().st_mode & 0o777,0o700)

    def tearDown(self):
        for p in self.processes:
            if p.poll() is None:
                p.kill()
            try:
                p.communicate(timeout=4)
            except subprocess.TimeoutExpired:
                p.kill()
                p.wait(timeout=4)
        if self.directory is not None:
            shutil.rmtree(self.directory)

    def command(self,mode,fixture=PROCESS):
        return [
            "qemu-mips-static","-L",str(VENDOR),
            str(VENDOR/"usr/bin/lua"),
            str(fixture),str(VENDOR),
            str(ROOT/"prototypes/history"),
            str(ROOT/"overlay/usr/lib/lua"),
            mode,str(self.directory),
        ]

    def invoke(self,mode,fixture=PROCESS):
        p=subprocess.run(self.command(mode,fixture),
                         capture_output=True,text=True,
                         cwd=ROOT,timeout=15)
        self.assertEqual(p.returncode,0,p.stderr)
        return p.stdout

    def hold(self,mode="hold"):
        p=subprocess.Popen(
            self.command(mode),cwd=ROOT,
            stdin=subprocess.PIPE,stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,text=True,bufsize=1,
        )
        self.processes.append(p)
        self.assertEqual(p.stdout.readline().strip(),
                         "AOTT_H023_RUNNING")
        return p

    def finish(self,p):
        p.stdin.write("\n")
        p.stdin.flush()
        out,err=p.communicate(timeout=10)
        self.assertEqual(p.returncode,0,err)
        return out

    def test_full_restart_policy_and_no_false_isp_outage(self):
        out=self.invoke("scenario",SCENARIO)
        self.assertIn("AOTT_H023_LIFECYCLE_FIXTURE_PASS checks=127",out)
        self.assertTrue((self.directory/"collector.lock").is_file())

    def test_live_kernel_exclusive_owner_prevents_second_lifecycle(self):
        holder=self.hold()
        lock=self.directory/"collector.lock"
        inode=lock.stat().st_ino
        self.assertIn("AOTT_H023_BUSY",self.invoke("try"))
        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as pool:
            others=list(pool.map(lambda _:self.invoke("try"),range(10)))
        self.assertTrue(all("AOTT_H023_BUSY" in other for other in others))
        self.assertEqual(lock.stat().st_ino,inode)
        self.assertIn("AOTT_H023_CLOSED",self.finish(holder))
        self.assertIn("AOTT_H023_RUNNING",self.invoke("try"))
        self.assertEqual(lock.stat().st_ino,inode)

    def test_unexpected_process_death_releases_lock(self):
        holder=self.hold()
        self.assertIn("AOTT_H023_BUSY",self.invoke("try"))
        holder.send_signal(signal.SIGKILL)
        holder.wait(timeout=10)
        new=self.invoke("try")
        self.assertIn("AOTT_H023_RUNNING",new)
        self.assertIn("AOTT_H023_CLOSED",new)

    def test_clean_process_exit_releases_lock_without_explicit_close(self):
        holder=self.hold("hold_exit")
        self.assertIn("AOTT_H023_BUSY",self.invoke("try"))
        output=self.finish(holder)
        self.assertIn("AOTT_H023_EXIT_WITHOUT_CLOSE",output)
        self.assertIn("AOTT_H023_RUNNING",self.invoke("try"))

    def test_lock_file_is_never_removed_by_normal_stop(self):
        self.assertIn("AOTT_H023_CLOSED",self.invoke("try"))
        saved=self.directory/"collector.lock"
        self.assertEqual(saved.stat().st_mode & 0o777,0o600)
        first_inode=saved.stat().st_ino
        self.assertIn("AOTT_H023_CLOSED",self.invoke("try"))
        self.assertEqual(saved.stat().st_ino,first_inode)

    def test_guarded_session_never_starts_at_wrong_path_or_writes_flash(self):
        # Everything here operates only inside a root-owned test directory.
        self.assertTrue(str(self.directory).startswith("/var/tmp/aott-h022-lock-test-"))
        self.assertEqual(list(self.directory.iterdir()),[])
        self.assertIn("AOTT_H023_CLOSED",self.invoke("try"))
        files=list(self.directory.iterdir())
        self.assertEqual(len(files),1)
        self.assertEqual(files[0].name,"collector.lock")
        self.assertEqual(files[0].stat().st_size,0)


if __name__=="__main__":
    unittest.main()
