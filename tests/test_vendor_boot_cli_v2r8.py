"""End-to-end private vendor-MIPS boot restoration in an isolated chroot.

This optional suite clones an approved extracted vendor rootfs into a private
temporary directory. All UCI changes are confined to that chroot, never to
the host's default /tmp/.uci or any real ONU. The MIPS restore Lua module and
MIPS vendor uci CLI cooperate through a strictly validated test-only pipe.
"""
import os
import hashlib
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
VENDOR = Path(os.getenv("AOTT_VENDOR_ROOTFS", "/nonexistent/vendor/rootfs"))
FIELDS = {
    "log_remote": "1", "log_ip": "collector.example.com",
    "log_port": "5514", "log_proto": "tcp", "aott_metrics": "1",
    "aott_metrics_client": "192" + ".0.2.40",
    "aott_metrics_sha256": "a" * 64,
}
CMDS = {"get", "set", "revert", "commit", "changes"}


class VendorBootRestoreCLITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        required = os.getenv("AOTT_VENDOR_ROOTFS") is not None
        if not all((VENDOR / path).is_file() for path in (
                "usr/bin/lua", "sbin/uci", "usr/lib/lua/luci/model/uci.lua")):
            if required:
                raise AssertionError("Explicit vendor baseline incomplete")
            raise unittest.SkipTest("Optional proprietary vendor runtime absent")
        if not shutil.which("qemu-mips-static") or not shutil.which("chroot"):
            if required:
                raise AssertionError("QEMU and chroot are required for private vendor CLI checks")
            raise unittest.SkipTest("QEMU/chroot unavailable")
        if os.geteuid() != 0:
            if required:
                raise AssertionError("Offline private chroot requires root")
            raise unittest.SkipTest("No isolated chroot access")

        cls.lab = tempfile.TemporaryDirectory(prefix="aott-r8-cli-chroot-", dir="/var/tmp")
        cls.rootfs = Path(cls.lab.name) / "rootfs"
        try:
            # Vendor rootfs includes device nodes. Python copytree attempts
            # to read these special files; cp -a preserves them as nodes.
            cls.rootfs.mkdir(mode=0o700)
            subprocess.run(
                ["cp", "-a", str(VENDOR) + "/.", str(cls.rootfs) + "/"],
                check=True, capture_output=True, timeout=25,
            )
            qemu = shutil.which("qemu-mips-static")
            assert qemu
            shutil.copy2(qemu, cls.rootfs / "usr/bin/qemu-mips-static")
            (cls.rootfs / "tmp/.uci").mkdir(mode=0o700, parents=True, exist_ok=True)
            (cls.rootfs / "proc").mkdir(exist_ok=True)
            # The vendor commit path calls /proc/self/fd. Mount /proc only
            # in child private namespaces, never on the host's mount tree.
            probe = subprocess.run(
                ["unshare", "--mount", "--propagation", "private", "--", "true"],
                capture_output=True, timeout=8,
            )
            if probe.returncode:
                raise AssertionError("Private mount namespace is unavailable")
            cls.fake_tests = cls.rootfs / "tmp/aott-cli-tests"
            cls.fake_tests.mkdir(mode=0o700)
            shutil.copy2(ROOT / "tests/vendor_boot_restore_bridge.lua",
                         cls.fake_tests / "bridge.lua")
            shutil.copy2(ROOT / "overlay/usr/lib/lua/8311/monitor_restore.lua",
                         cls.fake_tests / "restore.lua")
        except Exception:
            cls.lab.cleanup()
            raise

    @classmethod
    def tearDownClass(cls):
        if getattr(cls, "lab", None):
            cls.lab.cleanup()

    def setUp(self):
        self.work = tempfile.TemporaryDirectory(
            prefix="uci-restore-", dir=self.rootfs / "tmp"
        )
        self.addCleanup(self.work.cleanup)
        temp = Path(self.work.name)
        self.config = temp / "config"
        self.config.mkdir(mode=0o700)
        (self.config / "system").write_text(
            "config system 'cfg0a'\n"
            "\toption hostname 'generic-test'\n"
            "\toption zonename 'UTC'\n"
        )
        self.internal_config = "/tmp/" + temp.name + "/config"
        self.original_host_stage = self.host_stage_snapshot()
        # Each test starts with no pending operations in the private
        # chroot-wide default UCI staging directory.
        guest = self.rootfs / "tmp/.uci"
        self.assertFalse(any(f.stat().st_size for f in guest.iterdir()
                             if f.is_file() and not f.is_symlink()),
                         "Previous synthetic UCI staging leaked across tests")


    def chroot_call(self, tool, arguments):
        # Mount namespace has private propagation. The /proc bind disappears
        # when this child exits and never mutates the host namespace.
        return [
            "unshare", "--mount", "--propagation", "private", "--",
            "/bin/sh", "-c",
            'mount --bind /proc "$1/proc"; shift; exec "$@"',
            "sh", str(self.rootfs),
            "chroot", str(self.rootfs), "/usr/bin/qemu-mips-static",
            tool, *arguments,
        ]

    def cli(self, action, parameter):
        argv = self.chroot_call("/sbin/uci", [
            "-c", self.internal_config, "-q", action, parameter
        ])
        result = subprocess.run(
            argv, capture_output=True, text=True, timeout=12, check=False
        )
        return result.returncode, result.stdout.strip()

    @staticmethod
    def host_stage_snapshot():
        location = Path("/tmp/.uci")
        if not location.is_dir():
            return None
        # The guest has its own distinct /tmp and /tmp/.uci. Hash only
        # regular files; do not read or follow unrelated host symlinks.
        answer = {}
        for item in location.iterdir():
            if item.is_file() and not item.is_symlink():
                answer[item.name] = (
                    hashlib.sha256(item.read_bytes()).hexdigest(),
                    item.stat().st_mtime_ns,
                )
        return answer

    def check_host_not_modified(self):
        self.assertEqual(
            self.host_stage_snapshot(), self.original_host_stage,
            "Vendor CLI unexpectedly changed the host UCI staging area"
        )
        # Never leave a mount on the host outside the isolated namespace.
        result = subprocess.run(["mountpoint", "-q", str(self.rootfs / "proc")],
                                capture_output=True, timeout=5)
        self.assertNotEqual(result.returncode, 0, "Private /proc bind leaked")

    def run_restore(self, mode="normal", fail_action=None, fail_key=None):
        argv = self.chroot_call("/usr/bin/lua", [
            "/tmp/aott-cli-tests/bridge.lua",
            "/tmp/aott-cli-tests/restore.lua", mode
        ])
        events = []
        result = None
        with subprocess.Popen(
            argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, text=True, bufsize=1,
        ) as process:
            for line in process.stdout:
                line = line.rstrip("\n")
                if line.startswith("RESULT\t"):
                    result = line.split("\t", 2)
                    break
                parts = line.split("\t", 2)
                self.assertEqual(parts[0], "CMD", line)
                self.assertEqual(len(parts), 3, line)
                action, parameter = parts[1:]
                self.assertIn(action, CMDS)
                events.append((action, parameter))
                if action == "set":
                    option = parameter.split("=", 1)[0]
                    self.assertTrue(option.startswith("system.@system[0]."), option)
                    self.assertIn(option.split(".")[-1], FIELDS)
                if fail_action == action and (
                        fail_key is None or fail_key in parameter):
                    code, output = 1, ""
                else:
                    code, output = self.cli(action, parameter)
                process.stdin.write(
                    ("OK\t" + output if code == 0 else "ERR") + "\n"
                )
                process.stdin.flush()
            process.stdin.close()
            exit_code = process.wait(timeout=30)
            errors = process.stderr.read()
        self.assertEqual(exit_code, 0, errors)
        self.assertIsNotNone(result, errors)
        self.check_host_not_modified()
        return result[1], result[2], events

    def test_actual_vendor_uci_boot_restore_and_repeat(self):
        status, info, events = self.run_restore()
        self.assertEqual((status, info), ("OK", "restored"))
        self.assertEqual(sum(action == "commit" for action, _ in events), 1)
        self.assertEqual(sum(action == "set" for action, _ in events), len(FIELDS))
        for key, expected in FIELDS.items():
            self.assertEqual(self.cli("get", "system.cfg0a." + key), (0, expected), key)
        self.assertEqual(self.cli("get", "system.cfg0a.hostname"), (0, "generic-test"))
        status, info, events = self.run_restore()
        self.assertEqual((status, info), ("OK", "already-current"))
        self.assertFalse(any(action in ("set", "commit") for action, _ in events))

    def test_missing_record_issues_no_uci_commands(self):
        status, info, events = self.run_restore(mode="missing")
        self.assertEqual(status, "DENIED")
        self.assertIn("Persistent monitoring configuration unavailable", info)
        self.assertEqual(events, [])

    def test_pending_unrelated_uci_edits_block_restore(self):
        self.assertEqual(self.cli("set", "system.cfg0a.hostname=pending-test")[0], 0)
        status, info, events = self.run_restore()
        self.assertEqual(status, "DENIED")
        self.assertIn("Uncommitted system settings", info)
        self.assertFalse(any(action == "set" and "log_" in value
                             for action, value in events))
        code, changes = self.cli("changes", "system")
        self.assertEqual(code, 0)
        self.assertIn("hostname", changes)
        self.assertEqual(self.cli("revert", "system")[0], 0)

    def test_failed_middle_set_reverts_uci_staging(self):
        status, info, events = self.run_restore(
            fail_action="set", fail_key="log_port")
        self.assertEqual(status, "DENIED")
        self.assertIn("staged changes reverted", info)
        self.assertTrue(any(action == "revert" for action, _ in events))
        self.assertEqual(self.cli("changes", "system"), (0, ""))
        self.assertNotEqual(self.cli("get", "system.cfg0a.log_remote")[0], 0)

    def test_failed_commit_reverts_uci_staging(self):
        status, info, events = self.run_restore(fail_action="commit")
        self.assertEqual(status, "DENIED")
        self.assertIn("staged changes reverted", info)
        self.assertTrue(any(action == "revert" for action, _ in events))
        self.assertEqual(self.cli("changes", "system"), (0, ""))


if __name__ == "__main__":
    unittest.main()
