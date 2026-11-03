"""H-022 actual cross-process fcntl advisory locking via extracted vendor nixio.

Only isolated, disposable root-owned folders under /var/tmp are touched.
No ONU, procd service, network, settings, or production lock path is used.
"""
import concurrent.futures
import os
from pathlib import Path
import secrets
import shutil
import signal
import subprocess
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
LOCK=ROOT/"prototypes/history/8311/history_process_lock.lua"
LUA=ROOT/"tests/h022_nixio_lock_fixture.lua"
VENDOR=Path(os.getenv("AOTT_VENDOR_ROOTFS",
                        "/unavailable/offline-vendor-rootfs"))


class CrossProcessLockTests(unittest.TestCase):
    def test_lua51_syntax(self):
        if not shutil.which("luac5.1"):
            self.skipTest("Lua compiler unavailable")
        for path in (LOCK,LUA,
                     ROOT/"prototypes/history/8311/history_guarded_collector.lua",
                     ROOT/"tests/h022_guarded_collector_fixture.lua"):
            with self.subTest(file=path.name):
                p=subprocess.run(["luac5.1","-p",str(path)],
                                 capture_output=True,text=True,timeout=10)
                self.assertEqual(p.returncode,0,p.stderr)

    def test_no_production_service_or_device_mutation(self):
        code=LOCK.read_text()
        self.assertFalse(
            (ROOT/"overlay/usr/lib/lua/8311/history_process_lock.lua").exists()
        )
        self.assertNotIn("history_process_lock.lua",
                         (ROOT/"MANIFEST.json").read_text())
        for required in (
            'local PRODUCTION_DIR="/run/aott-history"',
            'local LOCK_BASENAME="collector.lock"',
            'local HELD={}',
            '"collector_held_by_other_process"',
            '"collector_already_owned_in_process"',
            '"collector_lock_identity_changed"',
            '"unsafe_collector_directory"',
            '"unsafe_lock_file"',
            'fd:lock("tlock")',
            'not same_object(opened,after)',
            'st.uid==0',
            'st.gid==0',
            'st.modedec==700',
            'st.modedec==600',
            'st.nlink==1',
            'lock_file_is_never_unlinked=true',
            'function M.release(handle)',
            'filesystem_safety_not_hardware_qualified=true',
        ):
            with self.subTest(required=required):
                self.assertIn(required,code)
        active="\n".join(x for x in code.splitlines()
                         if not x.lstrip().startswith("--"))
        for forbidden in ("os.execute(", " io.open(", "io.popen(",
                          "socket.", "uci:commit", "fwenv_set",
                          "fs.unlink(", "fs.rmdir(", "fs.rename(",
                          "luci.http", "/usr/bin/pon", "/dev/mtd"):
            self.assertNotIn(forbidden,active)

    def setUp(self):
        self.private=None
        self.holders=[]
        # Keep syntax/source safety checks active in public CI even without
        # the separately extracted vendor ABI or privileged test runtime.
        if self._testMethodName in (
                "test_lua51_syntax",
                "test_no_production_service_or_device_mutation",
                "test_guarded_source_has_no_unqualified_runtime_entrypoint"):
            return
        if not os.getenv("AOTT_VENDOR_ROOTFS"):
            self.skipTest("No extracted vendor rootfs")
        if os.geteuid()!=0:
            self.skipTest("Isolated root-owned lock test needs root")
        if not shutil.which("qemu-mips-static") or not (VENDOR/"usr/bin/lua").is_file() or not (VENDOR/"usr/lib/lua/nixio.so").is_file():
            self.skipTest("MIPS nixio runtime unavailable")
        self.private=Path("/var/tmp/aott-h022-lock-test-"+secrets.token_hex(8))
        self.private.mkdir(mode=0o700)
        self.assertEqual(self.private.stat().st_uid,0)
        self.assertEqual(self.private.stat().st_mode & 0o777,0o700)

    def tearDown(self):
        for p in self.holders:
            if p.poll() is None:
                p.kill()
            try:
                p.communicate(timeout=5)
            except subprocess.TimeoutExpired:
                p.kill()
                p.wait(timeout=5)
        if self.private is not None:
            self.private.chmod(0o700)
            shutil.rmtree(self.private)

    def command(self,action,path=None):
        return [
            "qemu-mips-static","-L",str(VENDOR),
            str(VENDOR/"usr/bin/lua"),
            str(LUA),str(VENDOR),str(LOCK),action,
            str(self.private if path is None else path),
        ]

    def run_fixture(self,action,path=None):
        p=subprocess.run(self.command(action,path),
                         capture_output=True,text=True,timeout=10,cwd=ROOT)
        self.assertEqual(p.returncode,0,p.stderr)
        return p.stdout

    def hold(self,action="hold"):
        p=subprocess.Popen(self.command(action),cwd=ROOT,
                           stdin=subprocess.PIPE,stdout=subprocess.PIPE,
                           stderr=subprocess.PIPE,text=True,bufsize=1)
        self.holders.append(p)
        self.assertEqual(p.stdout.readline().strip(),
                         "AOTT_H022_LOCK_ACQUIRED")
        return p

    def release(self,p):
        p.stdin.write("\n")
        p.stdin.flush()
        stdout,stderr=p.communicate(timeout=10)
        self.assertEqual(p.returncode,0,stderr)
        return stdout

    def test_single_process_ownership_and_stable_lock_inode(self):
        output=self.run_fixture("own")
        self.assertIn("AOTT_H022_LOCK_ACQUIRED",output)
        self.assertIn("AOTT_H022_LOCK_RELEASED",output)
        file=self.private/"collector.lock"
        self.assertTrue(file.is_file())
        self.assertEqual(file.stat().st_mode & 0o777,0o600)
        inode=file.stat().st_ino
        self.assertIn("AOTT_H022_TRY_GRANTED",self.run_fixture("try"))
        self.assertEqual(file.stat().st_ino,inode)

    def test_other_process_cannot_acquire_while_owner_holds(self):
        owner=self.hold()
        lock_file=self.private/"collector.lock"
        inode=lock_file.stat().st_ino
        self.assertIn("AOTT_H022_TRY_BUSY",self.run_fixture("try"))
        with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
            outputs=list(pool.map(lambda _:self.run_fixture("try"),range(12)))
        self.assertTrue(all("AOTT_H022_TRY_BUSY" in s for s in outputs))
        self.assertEqual(lock_file.stat().st_ino,inode)
        self.assertIn("AOTT_H022_LOCK_RELEASED",self.release(owner))
        self.assertIn("AOTT_H022_TRY_GRANTED",self.run_fixture("try"))
        self.assertEqual(lock_file.stat().st_ino,inode)

    def test_sigkill_process_exit_releases_kernel_lock(self):
        owner=self.hold()
        self.assertIn("AOTT_H022_TRY_BUSY",self.run_fixture("try"))
        owner.send_signal(signal.SIGKILL)
        owner.wait(timeout=10)
        self.assertIn("AOTT_H022_TRY_GRANTED",self.run_fixture("try"))

    def test_clean_exit_releases_kernel_lock(self):
        owner=self.hold("hold_exit")
        self.assertIn("AOTT_H022_TRY_BUSY",self.run_fixture("try"))
        output=self.release(owner)
        self.assertIn("AOTT_H022_EXIT_WITH_FD_LOCK",output)
        self.assertIn("AOTT_H022_TRY_GRANTED",self.run_fixture("try"))

    def test_fail_closed_for_untrusted_parent_permissions(self):
        self.private.chmod(0o777)
        try:
            self.assertIn("AOTT_H022_REJECTED_DIRECTORY",
                          self.run_fixture("reject_directory"))
        finally:
            self.private.chmod(0o700)
        self.assertFalse((self.private/"collector.lock").exists())

    def test_fail_closed_for_symlink_and_wrong_mode(self):
        outside=self.private/"inert-sentinel"
        outside.write_text("no write permitted")
        locked=self.private/"collector.lock"
        locked.symlink_to(outside)
        self.assertIn("AOTT_H022_REJECTED_LOCK",
                      self.run_fixture("reject_lock"))
        self.assertEqual(outside.read_text(),"no write permitted")
        locked.unlink()
        locked.write_text("")
        locked.chmod(0o644)
        self.assertIn("AOTT_H022_REJECTED_LOCK",
                      self.run_fixture("reject_lock"))
        self.assertEqual(locked.stat().st_mode & 0o777,0o644)

    def test_fail_closed_for_hardlinked_lock(self):
        lock=self.private/"collector.lock"
        lock.write_text("")
        lock.chmod(0o600)
        mirror=self.private/"other-link"
        os.link(lock,mirror)
        self.assertIn("AOTT_H022_REJECTED_LOCK",
                      self.run_fixture("reject_lock"))
        self.assertEqual(lock.stat().st_nlink,2)

    def test_fixed_directory_policy_blocks_unrelated_paths(self):
        paths=("/etc","/tmp",str(self.private)+"/subdir",
               "/var/tmp/arbitrary","/run")
        for path in paths:
            with self.subTest(path=path):
                self.assertIn("AOTT_H022_REJECTED_PATH",
                              self.run_fixture("reject_path",path))


    def guarded_command(self,action):
        return [
            "qemu-mips-static","-L",str(VENDOR),
            str(VENDOR/"usr/bin/lua"),
            str(ROOT/"tests/h022_guarded_collector_fixture.lua"),
            str(VENDOR),str(ROOT/"prototypes/history"),
            str(ROOT/"overlay/usr/lib/lua"),
            action,str(self.private),
        ]

    def run_guarded(self,action):
        p=subprocess.run(self.guarded_command(action),
                         capture_output=True,text=True,cwd=ROOT,timeout=12)
        self.assertEqual(p.returncode,0,p.stderr)
        return p.stdout

    def hold_guarded(self,action="guarded_hold"):
        p=subprocess.Popen(self.guarded_command(action),cwd=ROOT,
                           stdin=subprocess.PIPE,stdout=subprocess.PIPE,
                           stderr=subprocess.PIPE,text=True,bufsize=1)
        self.holders.append(p)
        self.assertEqual(p.stdout.readline().strip(),
                         "AOTT_H022_GUARDED_READY")
        return p

    def test_guarded_h021_collector_and_cross_process_contention(self):
        holder=self.hold_guarded()
        self.assertIn("AOTT_H022_GUARDED_BUSY",
                      self.run_guarded("guarded_try"))
        self.assertIn("AOTT_H022_GUARDED_RELEASED",self.release(holder))
        after=self.run_guarded("guarded_try")
        self.assertIn("AOTT_H022_GUARDED_READY",after)
        self.assertIn("AOTT_H022_GUARDED_RELEASED",after)
        self.assertTrue((self.private/"collector.lock").is_file())

    def test_guarded_h021_collector_crash_releases_kernel_lock(self):
        holder=self.hold_guarded()
        self.assertIn("AOTT_H022_GUARDED_BUSY",
                      self.run_guarded("guarded_try"))
        holder.send_signal(signal.SIGKILL)
        holder.wait(timeout=10)
        self.assertIn("AOTT_H022_GUARDED_READY",
                      self.run_guarded("guarded_try"))

    def test_guarded_h021_and_direct_lock_use_same_inode(self):
        holder=self.hold()
        self.assertIn("AOTT_H022_GUARDED_BUSY",
                      self.run_guarded("guarded_try"))
        self.assertIn("AOTT_H022_LOCK_RELEASED",self.release(holder))
        self.assertIn("AOTT_H022_GUARDED_READY",
                      self.run_guarded("guarded_try"))

    def test_guarded_source_has_no_unqualified_runtime_entrypoint(self):
        code=(ROOT/"prototypes/history/8311/history_guarded_collector.lua").read_text()
        for required in (
            'mode~="offline_synthetic"',
            '"hardware_admission_not_qualified"',
            'lock.acquire(directory)',
            'collector.new_independent(',
            'lock.release(owner)',
            'function M.tick(handle,now,provider)',
            'function M.export_json(handle,range,limit)',
            'function M.export_csv(handle,range,limit)',
            'function M.close(handle)',
            'exclusive_kernel_owner=true',
            'source_only_not_deployed=true',
        ):
            self.assertIn(required,code)
        self.assertFalse((ROOT/"overlay/usr/lib/lua/8311/history_guarded_collector.lua").exists())
        self.assertNotIn("history_guarded_collector.lua",
                         (ROOT/"MANIFEST.json").read_text())

if __name__=="__main__":
    unittest.main()
