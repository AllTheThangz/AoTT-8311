"""End-to-end boot restoration using genuine vendor-MIPS Lua and UCI.

QEMU reads the approved vendor runtime without chroot or mounts. All changes
use random synthetic package names and private config/staging directories.
The unchanged restore Lua and vendor UCI cooperate through the validated
test-only bridge; independent cold reads prove commits reached disk.
"""
import os
import hashlib
from pathlib import Path
import secrets
import shutil
import stat
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
        cls.qemu = shutil.which("qemu-mips-static")
        if not cls.qemu:
            if required:
                raise AssertionError("QEMU is required for private vendor CLI checks")
            raise unittest.SkipTest("QEMU unavailable")
        # No root privileges, mount namespace, device nodes or cloned rootfs.
        # QEMU loads the unchanged vendor programs and libraries read-only.
        cls.lab = tempfile.TemporaryDirectory(
            prefix="aott-r8-cli-user-", dir="/var/tmp"
        )

    @classmethod
    def tearDownClass(cls):
        if getattr(cls, "lab", None):
            cls.lab.cleanup()

    def setUp(self):
        self.work = tempfile.TemporaryDirectory(
            prefix="uci-restore-", dir=self.lab.name
        )
        self.addCleanup(self.work.cleanup)
        temp = Path(self.work.name)
        self.config = temp / "config"
        self.delta = temp / "delta"
        self.cold = temp / "cold"
        for directory in (self.config, self.delta, self.cold):
            directory.mkdir(mode=0o700)
        # This vendor UCI always also searches /tmp/.uci. A random package
        # namespace plus collision checks prevents reading another caller's
        # real "system" edits while the Lua bridge retains its native contract.
        self.package = "aott_boot_" + secrets.token_hex(16)
        self.package_file = self.config / self.package
        self.package_file.write_text(
            "config system 'cfg0a'\n"
            "\toption hostname 'generic-test'\n"
            "\toption zonename 'UTC'\n"
        )
        self.package_file.chmod(0o600)
        self.original_config = self.package_file.read_bytes()
        self.original_host_stage = self.host_stage_snapshot()
        self.addCleanup(self.check_host_not_modified)
        self.assertFalse(any(self.delta.iterdir()),
                         "Synthetic UCI staging leaked across tests")
        self.assertFalse(any(self.cold.iterdir()),
                         "Cold UCI reader has pending changes")

    def qemu_call(self, tool, arguments):
        self.assertIn(tool, ("usr/bin/lua", "sbin/uci"))
        return [
            self.qemu, "-L", str(VENDOR), str(VENDOR / tool), *arguments,
        ]

    def check_default_package_absent(self):
        # QEMU may redirect an existing guest path beneath its -L prefix.
        # Neither possible default savedir may contain this fixture's name.
        for savedir in (Path("/tmp/.uci"), VENDOR / "tmp/.uci"):
            pending = savedir / self.package
            self.assertFalse(pending.is_symlink() or pending.exists(),
                             "Synthetic package collided with default UCI staging")

    def native(self, action, parameter, *, cold=False, committing=False):
        self.assertIn(action, CMDS | {"export"})
        self.assertEqual(parameter.partition(".")[0], self.package)
        self.assertEqual(committing, action == "commit")
        self.check_default_package_absent()
        # -P chooses a private savedir but also sets NOCOMMIT in this vendor
        # build. A genuine commit instead reads the private delta using -p.
        # Random package names keep the unchanged default savedir uninvolved.
        flag = "-p" if committing else "-P"
        staging = self.cold if cold else self.delta
        result = subprocess.run(
            self.qemu_call("sbin/uci", [
                "-c", str(self.config), flag, str(staging),
                "-q", action, parameter,
            ]),
            capture_output=True, text=True, timeout=12, check=False,
        )
        self.check_default_package_absent()
        self.check_host_not_modified()
        return result

    def cli(self, action, parameter, *, cold=False):
        self.assertIn(action, CMDS)
        package, dot, tail = parameter.partition(".")
        self.assertEqual(package, "system")
        self.assertFalse(any(value in parameter for value in ("\0", "\r", "\n")))
        parameter = self.package + dot + tail
        if action != "commit":
            result = self.native(action, parameter, cold=cold)
            return result.returncode, result.stdout.strip()

        self.assertFalse(cold)
        expected = self.native("export", self.package)
        self.assertEqual(expected.returncode, 0, expected.stderr)
        result = self.native("commit", parameter, committing=True)
        if result.returncode == 0:
            # Prove a real native disk commit with a new process that has no
            # private pending delta. A successful no-op commit cannot pass.
            persisted = self.native("export", self.package, cold=True)
            self.assertEqual(persisted.returncode, 0, persisted.stderr)
            self.assertEqual(persisted.stdout, expected.stdout,
                             "Vendor commit did not persist the intended settings")
            # -p reads an additional delta source without emptying it. Only
            # after cold readback may this adapter remove its OWN disposable
            # source, reproducing normal commit's consumed-delta behavior.
            pending = self.delta / self.package
            if pending.exists() or pending.is_symlink():
                self.assertFalse(pending.is_symlink())
                self.assertTrue(pending.is_file())
                pending.unlink()
            reread = self.native("export", self.package)
            self.assertEqual(reread.returncode, 0, reread.stderr)
            self.assertEqual(reread.stdout, persisted.stdout)
        return result.returncode, result.stdout.strip()

    @staticmethod
    def host_stage_snapshot():
        location = Path("/tmp/.uci")
        if location.is_symlink():
            raise AssertionError("Host UCI staging directory is a symlink")
        if not location.exists():
            return None
        if not location.is_dir():
            raise AssertionError("Host UCI staging path is not a directory")
        # Include entry metadata and link targets without following links.
        # Reads never enter unrelated subdirectories or special files.
        answer = {}
        for item in location.iterdir():
            info = item.lstat()
            entry = (
                stat.S_IFMT(info.st_mode), stat.S_IMODE(info.st_mode),
                info.st_uid, info.st_gid, info.st_size, info.st_mtime_ns,
            )
            if stat.S_ISREG(info.st_mode):
                entry += (hashlib.sha256(item.read_bytes()).hexdigest(),)
            elif stat.S_ISLNK(info.st_mode):
                entry += (os.readlink(item),)
            answer[item.name] = entry
        info = location.stat()
        return (
            stat.S_IMODE(info.st_mode), info.st_uid, info.st_gid,
            info.st_mtime_ns, answer,
        )

    def check_host_not_modified(self):
        self.assertEqual(
            self.host_stage_snapshot(), self.original_host_stage,
            "Vendor CLI unexpectedly changed the host UCI staging area"
        )

    def run_restore(self, mode="normal", fail_action=None, fail_key=None):
        argv = self.qemu_call("usr/bin/lua", [
            str(ROOT / "tests/vendor_boot_restore_bridge.lua"),
            str(ROOT / "overlay/usr/lib/lua/8311/monitor_restore.lua"), mode,
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
            self.assertEqual(
                self.cli("get", "system.cfg0a." + key, cold=True),
                (0, expected), "Committed field missing from cold read: " + key,
            )
        self.assertEqual(self.cli("changes", "system"), (0, ""))
        self.assertEqual(self.cli("get", "system.cfg0a.hostname"), (0, "generic-test"))
        status, info, events = self.run_restore()
        self.assertEqual((status, info), ("OK", "already-current"))
        self.assertFalse(any(action in ("set", "commit") for action, _ in events))

    def test_missing_record_issues_no_uci_commands(self):
        status, info, events = self.run_restore(mode="missing")
        self.assertEqual(status, "DENIED")
        self.assertIn("Persistent monitoring configuration unavailable", info)
        self.assertEqual(events, [])
        self.assertEqual(self.package_file.read_bytes(), self.original_config)

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
        self.assertEqual(self.package_file.read_bytes(), self.original_config)

    def test_failed_middle_set_reverts_uci_staging(self):
        status, info, events = self.run_restore(
            fail_action="set", fail_key="log_port")
        self.assertEqual(status, "DENIED")
        self.assertIn("staged changes reverted", info)
        self.assertTrue(any(action == "revert" for action, _ in events))
        self.assertEqual(self.cli("changes", "system"), (0, ""))
        self.assertNotEqual(self.cli("get", "system.cfg0a.log_remote")[0], 0)
        self.assertEqual(self.package_file.read_bytes(), self.original_config)

    def test_failed_commit_reverts_uci_staging(self):
        status, info, events = self.run_restore(fail_action="commit")
        self.assertEqual(status, "DENIED")
        self.assertIn("staged changes reverted", info)
        self.assertTrue(any(action == "revert" for action, _ in events))
        self.assertEqual(self.cli("changes", "system"), (0, ""))
        self.assertEqual(self.package_file.read_bytes(), self.original_config)


if __name__ == "__main__":
    unittest.main()
