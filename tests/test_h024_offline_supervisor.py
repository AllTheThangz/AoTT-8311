"""H-024 offline foreground-supervisor and vendor-QEMU process tests.

All filesystem changes are limited to isolated root-owned test directories.
The production procd candidate cannot spawn a process and is not installed.
"""
import os
from pathlib import Path
import secrets
import select
import shutil
import signal
import subprocess
import time
import unittest

ROOT=Path(__file__).resolve().parents[1]
SUPERVISOR=ROOT/"prototypes/supervisor"
WRAPPER=SUPERVISOR/"h024_wrapper.sh"
WORKER=SUPERVISOR/"h024_worker.lua"
PROCD=SUPERVISOR/"8311-history.init-candidate"
LOCK=ROOT/"prototypes/history/8311/history_process_lock.lua"
FIXTURE=ROOT/"tests/h022_nixio_lock_fixture.lua"
VENDOR=Path(os.environ.get("AOTT_VENDOR_ROOTFS",
                           "/offline/vendor-rootfs/unavailable"))


class OfflineSupervisorSourceChecks(unittest.TestCase):
    def test_syntax_in_host_shell_and_lua(self):
        checks=[["sh","-n",str(WRAPPER)],
                ["sh","-n",str(PROCD)]]
        if shutil.which("luac5.1"):
            checks.append(["luac5.1","-p",str(WORKER)])
        for cmd in checks:
            with self.subTest(tool=cmd[0],file=cmd[-1]):
                p=subprocess.run(cmd,capture_output=True,text=True,
                                 timeout=10)
                self.assertEqual(p.returncode,0,p.stderr)

    def test_inert_procd_candidate_emits_error_and_never_command(self):
        test='''procd_open_instance() { printf 'OPEN:%s\\n' "$*"; }; '''+\
             '''procd_set_param() { printf 'PARAM:%s\\n' "$*"; }; '''+\
             '''procd_close_instance() { echo CLOSE; }; '''+\
             '''. "$1"; start_service'''
        p=subprocess.run(["sh","-c",test,"shell",str(PROCD)],
                         capture_output=True,text=True,timeout=8)
        self.assertEqual(p.returncode,0,p.stderr)
        self.assertIn("PARAM:error H024 source-only",p.stdout)
        self.assertNotIn("PARAM:command",p.stdout)
        self.assertNotIn("PARAM:respawn",p.stdout)
        self.assertIn("USE_PROCD=1",PROCD.read_text())
        self.assertIn("START=99",PROCD.read_text())

    def test_no_firmware_manifest_or_runtime_autostart(self):
        self.assertTrue(WORKER.is_file())
        self.assertTrue(WRAPPER.is_file())
        self.assertTrue(PROCD.is_file())
        manifest=(ROOT/"MANIFEST.json").read_text()
        for filename in ("h024_worker.lua","h024_wrapper.sh",
                         "8311-history.init-candidate"):
            self.assertNotIn(filename,manifest)
        runtime=(ROOT/"overlay/etc/init.d/8311-history")
        self.assertTrue(runtime.is_file())
        deployed=runtime.read_text()
        self.assertIn('config_get enabled main enabled 0',deployed)
        self.assertIn('[ "$enabled" = "1" ] || return 0',deployed)
        self.assertNotIn("procd_set_param respawn",deployed)
        self.assertFalse((ROOT/"overlay/usr/libexec/h024_wrapper.sh").exists())

    def test_hard_synthetic_admission_and_no_live_commands(self):
        text=WORKER.read_text()
        for required in (
            'arg[1]~="offline_synthetic"',
            "nixio.getppid()~=expected_parent",
            "local session,reason=lifecycle.new(",
            'lifecycle.shutdown(session)',
            'requested_stop()',
            'nixio.nanosleep(0,200000000)',
            'for tick=0,299 do',
            '"AOTT_H024_SYNTHETIC_WORKER_READY"',
            '"AOTT_H024_SYNTHETIC_WORKER_CLOSED"',
        ):
            with self.subTest(required=required):
                self.assertIn(required,text)
        wrapper=WRAPPER.read_text()
        for required in (
            'ulimit -c 0',
            'ulimit -n 32',
            'ulimit -v 4194304',
            'nice -n 10',
            'trap shutdown TERM INT HUP',
            'kill -KILL "$child"',
            'stopfile="$runtime/stop.$$.request"',
        ):
            self.assertIn(required,wrapper)
        for prohibited in ("uci commit","fwenv_set","/dev/mtd",
                           "http.request","socket.connect",
                           "procd_set_param respawn 5 10 0"):
            self.assertNotIn(prohibited,text+"\n"+wrapper)


class OfflineSupervisorProcessTests(unittest.TestCase):
    def setUp(self):
        self.directory=None
        self.processes=[]
        if not os.environ.get("AOTT_VENDOR_ROOTFS"):
            self.skipTest("Offline extracted vendor rootfs not provided")
        if os.geteuid()!=0:
            self.skipTest("Root required for private lock directory")
        if not shutil.which("qemu-mips-static"):
            self.skipTest("QEMU user-mode unavailable")
        if not (VENDOR/"usr/bin/lua").is_file() or not (
            VENDOR/"usr/lib/lua/nixio.so").is_file():
            self.skipTest("Vendor Lua/nixio missing")
        self.directory=Path("/var/tmp/aott-h022-lock-test-"+secrets.token_hex(8))
        self.directory.mkdir(mode=0o700)

    def tearDown(self):
        for p in self.processes:
            if p.poll() is None:
                p.terminate()
            try:
                p.communicate(timeout=8)
            except subprocess.TimeoutExpired:
                p.kill()
                p.communicate(timeout=4)
        if self.directory is not None:
            shutil.rmtree(self.directory)

    def command(self,mode="offline_synthetic"):
        return ["/bin/sh",str(WRAPPER),mode,
                shutil.which("qemu-mips-static"),str(VENDOR),
                str(ROOT/"prototypes/history"),
                str(ROOT/"overlay/usr/lib/lua"),
                str(self.directory),str(WORKER)]

    def begin(self):
        p=subprocess.Popen(self.command(),cwd=ROOT,stdin=subprocess.DEVNULL,
                           stdout=subprocess.PIPE,stderr=subprocess.PIPE,
                           text=True,bufsize=1)
        self.processes.append(p)
        deadline=time.monotonic()+9
        while time.monotonic()<deadline:
            if p.poll() is not None:
                out,err=p.communicate(timeout=2)
                self.fail("Worker exited before ready: "+out+" "+err)
            if select.select([p.stdout],[],[],0.2)[0]:
                line=p.stdout.readline().strip()
                if line=="AOTT_H024_SYNTHETIC_WORKER_READY":
                    return p
                if line:
                    self.fail("Unexpected readiness line: "+line)
        self.fail("Worker never acquired guarded collector")

    def try_kernel_lock(self):
        cmd=["qemu-mips-static","-L",str(VENDOR),
             str(VENDOR/"usr/bin/lua"),str(FIXTURE),
             str(VENDOR),str(LOCK),"try",str(self.directory)]
        p=subprocess.run(cmd,cwd=ROOT,capture_output=True,text=True,timeout=9)
        self.assertEqual(p.returncode,0,p.stderr)
        return p.stdout

    def child_pid(self,wrapper):
        parent=Path("/proc")/str(wrapper.pid)/"task"/str(wrapper.pid)/"children"
        deadline=time.monotonic()+3
        while time.monotonic()<deadline:
            if parent.exists():
                children=parent.read_text().split()
                if children:return int(children[0])
            time.sleep(0.03)
        self.fail("QEMU child PID not discoverable")

    def eventual_release(self):
        for _ in range(30):
            if "AOTT_H022_TRY_GRANTED" in self.try_kernel_lock():
                return
            time.sleep(0.15)
        self.fail("Kernel lock remained held after source worker exit")

    def test_cooperative_sigterm_and_release(self):
        p=self.begin()
        self.assertIn("AOTT_H022_TRY_BUSY",self.try_kernel_lock())
        p.send_signal(signal.SIGTERM)
        out,err=p.communicate(timeout=10)
        self.assertEqual(p.returncode,0,err)
        self.assertIn("AOTT_H024_SYNTHETIC_WORKER_CLOSED",out)
        self.assertIn("AOTT_H024_OFFLINE_WRAPPER_STOPPED",out)
        self.eventual_release()
        self.assertEqual(sorted(x.name for x in self.directory.iterdir()),
                         ["collector.lock"])

    def test_hup_and_interrupt_also_request_bounded_shutdown(self):
        for sig in (signal.SIGHUP,signal.SIGINT):
            with self.subTest(signal=sig):
                p=self.begin()
                p.send_signal(sig)
                out,err=p.communicate(timeout=10)
                self.assertEqual(p.returncode,0,err)
                self.assertIn("AOTT_H024_SYNTHETIC_WORKER_CLOSED",out)
                self.eventual_release()

    def test_sigkill_wrapper_cannot_leave_orphan_collector(self):
        p=self.begin()
        child=self.child_pid(p)
        self.assertIn("AOTT_H022_TRY_BUSY",self.try_kernel_lock())
        p.kill()
        p.wait(timeout=5)
        self.eventual_release()
        self.assertTrue((self.directory/"collector.lock").is_file())
        # A child may be briefly a zombie if PID 1 has not reaped it,
        # but it cannot still own the kernel advisory lock.
        if (Path("/proc")/str(child)/"stat").exists():
            state=(Path("/proc")/str(child)/"stat").read_text().split()[2]
            self.assertEqual(state,"Z")

    def test_sigkill_worker_has_no_respawn(self):
        p=self.begin()
        os.kill(self.child_pid(p),signal.SIGKILL)
        out,err=p.communicate(timeout=10)
        self.assertNotEqual(p.returncode,0)
        self.assertIn("AOTT_H024_OFFLINE_WORKER_EXITED_NONZERO",err)
        self.assertNotIn("AOTT_H024_SYNTHETIC_WORKER_READY",out)
        self.eventual_release()

    def test_second_supervisor_denied_while_first_owns_lock(self):
        p=self.begin()
        contender=subprocess.run(self.command(),cwd=ROOT,
                                  capture_output=True,text=True,timeout=10)
        self.assertNotEqual(contender.returncode,0)
        self.assertIn("AOTT_H024_SOURCE_WORKER_STOP:owner_busy",contender.stderr)
        self.assertIsNone(p.poll())
        self.assertIn("AOTT_H022_TRY_BUSY",self.try_kernel_lock())
        p.terminate()
        out,err=p.communicate(timeout=10)
        self.assertEqual(p.returncode,0,err)
        self.eventual_release()

    def test_emulator_child_low_priority_and_file_descriptor_limits(self):
        p=self.begin()
        child=self.child_pid(p)
        self.assertGreaterEqual(os.getpriority(os.PRIO_PROCESS,child),10)
        data=(Path("/proc")/str(child)/"limits").read_text()
        open_files=next(line for line in data.splitlines()
                        if line.startswith("Max open files"))
        self.assertIn("32",open_files)
        addr=next(line for line in data.splitlines()
                  if line.startswith("Max address space"))
        self.assertIn(str(4194304*1024),addr)
        self.assertIn("AOTT_H022_TRY_BUSY",self.try_kernel_lock())
        p.send_signal(signal.SIGTERM)
        p.communicate(timeout=10)

    def test_refuse_non_offline_mode_without_starting(self):
        p=subprocess.run(self.command("production"),
                         cwd=ROOT,capture_output=True,text=True,timeout=5)
        self.assertNotEqual(p.returncode,0)
        self.assertIn("H024_SOURCE_ONLY_MODE_REQUIRED",p.stderr)
        self.assertEqual(list(self.directory.iterdir()),[])


if __name__=="__main__":
    unittest.main()
