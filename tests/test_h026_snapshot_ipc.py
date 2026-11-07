"""H-026: actual vendor-MIPS, cross-process cached history transfer tests.

The collector and renderer run only under extracted vendor Lua/nixio in
isolated root-owned test directories. No active stick, ISP, network or LuCI
endpoint is touched. Source validation also runs without vendor images.
"""
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import secrets
import shutil
import subprocess
import unittest

ROOT=Path(__file__).resolve().parents[1]
HISTORY=ROOT/"prototypes/history"
OVERLAY=ROOT/"overlay/usr/lib/lua"
SHAPE=ROOT/"tests/h026_projection_shape_fixture.lua"
IPC=ROOT/"tests/h026_ipc_fixture.lua"
VENDOR=Path(os.getenv("AOTT_VENDOR_ROOTFS",
                      "/missing/offline-vendor-rootfs"))
SNAPSHOT="snapshot.json"
STAGED="snapshot.json.new"


class HistoryApiSourceTests(unittest.TestCase):
    def test_lua_syntax(self):
        if not shutil.which("luac5.1"):
            self.skipTest("Host Lua 5.1 compiler missing")
        for source in (
            HISTORY/"8311/history_snapshot_shape.lua",
            HISTORY/"8311/history_snapshot_ipc.lua",
            HISTORY/"8311/history_http_readonly.lua",
            SHAPE,IPC,
        ):
            with self.subTest(filename=source.name):
                out=subprocess.run(["luac5.1","-p",str(source)],
                    capture_output=True,text=True,timeout=10)
                self.assertEqual(out.returncode,0,out.stderr)

    def test_host_projector_schema_contract(self):
        if not shutil.which("lua5.1"):
            self.skipTest("Host Lua interpreter unavailable")
        result=subprocess.run(
            ["lua5.1",str(SHAPE),str(HISTORY)],
            cwd=ROOT,capture_output=True,text=True,timeout=12,
        )
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertIn("AOTT_H026_PROJECTION_SHAPE_PASS checks=57",
                      result.stdout)

    def test_source_not_shipped_or_anonymous(self):
        manifest=(ROOT/"MANIFEST.json").read_text()
        for basename in (
            "history_snapshot_shape.lua","history_snapshot_ipc.lua",
            "history_http_readonly.lua",
        ):
            self.assertIn(basename,manifest)
            self.assertTrue((OVERLAY/"8311"/basename).is_file())
        controller=(OVERLAY/"luci/controller/8311.lua").read_text()
        self.assertNotIn("history_data",controller)
        self.assertNotIn('entry({"8311", "history',controller)
        gateway=(HISTORY/"8311/history_http_readonly.lua").read_text()
        for expected in (
            'request.method~="GET"',
            'request.route~="/admin/8311/history_data"',
            "pcall(verify_admin)",
            "if not ok or authorized~=true",
            'canonical.encode_checked_projection(decoded)',
            'rebuilt~=raw',
            '"Cache-Control"]="no-store, private, max-age=0"',
            '"X-Content-Type-Options"]="nosniff"',
            '\"Content-Security-Policy\"',
            '\"Referrer-Policy\"',
            '"Vary"]="Cookie"',
            "no_on_demand_native_poll=true",
        ):
            with self.subTest(expected=expected):
                self.assertIn(expected,gateway)

    def test_snapshot_strict_private_path_and_owner_lock(self):
        source=(HISTORY/"8311/history_snapshot_ipc.lua").read_text()
        for expected in (
            "function M.publish(handle,directory,mode)",
            "function M.read(directory,mode)",
            "function M.discard_stale_stage(handle,directory,mode)",
            'mode=="offline_synthetic"',
            'type(st)=="table" and st.type=="dir"',
            "st.modedec==700",
            'st.modedec==600 and st.nlink==1',
            "same(state,opened)",
            "same(opened,after)",
            '"snapshot_stage_sync_failed"',
            "fd:sync()",
            "fs.rename(stage,final)",
            "guarded.export_json(handle,\"hour\",100)",
            '"exclusive_collector_owner_required"',
            '\"stale_snapshot_stage_blocks_publish\"',
            '"snapshot_readback_unverified"',
            '"noncanonical_snapshot_bytes"',
            'canonical.encode_checked_projection(value)',
            "luci.jsonc",
            "shape.validate(value)",
        ):
            with self.subTest(expected=expected):
                self.assertIn(expected,source)
        executable="\n".join(
            line for line in source.splitlines()
            if line.strip() and not line.lstrip().startswith("--")
        )
        for banned in (
            "os.execute(", "io.popen(", "socket.",
            "luci.http", "uci:commit","fwenv_set",
            "/dev/mtd", "cron(", "setInterval(",
            "/usr/bin/pon", "/usr/sbin/ethtool",
        ):
            with self.subTest(banned=banned):
                self.assertNotIn(banned,executable)


class VendorMipsSnapshotProcessTests(unittest.TestCase):
    def setUp(self):
        self.snapshot_dir=None
        self.lock_dir=None
        if not os.getenv("AOTT_VENDOR_ROOTFS"):
            self.skipTest("Vendor rootfs not provided")
        if os.geteuid()!=0:
            self.skipTest("Private root-owned test dirs require root")
        if not shutil.which("qemu-mips-static"):
            self.skipTest("QEMU MIPS unavailable")
        if not (VENDOR/"usr/bin/lua").is_file() or not (
            VENDOR/"usr/lib/lua/nixio.so").is_file() or not (
            VENDOR/"usr/lib/lua/luci/jsonc.so").is_file():
            self.skipTest("Extracted vendor Lua, nixio or jsonc missing")
        self.snapshot_dir=Path("/var/tmp/aott-h026-ipc-test-"+secrets.token_hex(8))
        self.lock_dir=Path("/var/tmp/aott-h022-lock-test-"+secrets.token_hex(8))
        self.snapshot_dir.mkdir(mode=0o700)
        self.lock_dir.mkdir(mode=0o700)

    def tearDown(self):
        for directory in (self.snapshot_dir,self.lock_dir):
            if directory is not None and directory.exists():
                directory.chmod(0o700)
                shutil.rmtree(directory)

    def command(self,action):
        return [
            "qemu-mips-static","-L",str(VENDOR),
            str(VENDOR/"usr/bin/lua"),
            str(IPC),str(VENDOR),str(HISTORY),str(OVERLAY),
            str(self.lock_dir),str(self.snapshot_dir),action,
        ]

    def invoke(self,action):
        out=subprocess.run(self.command(action),cwd=ROOT,
                           capture_output=True,text=True,timeout=15)
        self.assertEqual(out.returncode,0,out.stderr)
        return out.stdout

    def test_vendor_mips_projection_shape_validation(self):
        cmd=["qemu-mips-static","-L",str(VENDOR),
             str(VENDOR/"usr/bin/lua"),str(SHAPE),str(HISTORY)]
        p=subprocess.run(cmd,cwd=ROOT,capture_output=True,text=True,
                         timeout=12)
        self.assertEqual(p.returncode,0,p.stderr)
        self.assertIn("AOTT_H026_PROJECTION_SHAPE_PASS checks=57",
                      p.stdout)

    def test_cross_process_publish_and_read_is_bounded_and_private(self):
        self.assertIn("AOTT_H026_INVALID_READ_DENIED",
                      self.invoke("read_invalid"))
        self.assertIn("AOTT_H026_IPC_PUBLISH_PASS",
                      self.invoke("publish"))
        self.assertIn("AOTT_H026_CROSS_PROCESS_READ_PASS",
                      self.invoke("read"))
        file=self.snapshot_dir/SNAPSHOT
        self.assertTrue(file.is_file())
        self.assertEqual(file.stat().st_mode & 0o777,0o600)
        self.assertEqual(file.stat().st_uid,0)
        self.assertEqual(file.stat().st_nlink,1)
        self.assertLess(file.stat().st_size,65537)
        self.assertFalse((self.snapshot_dir/STAGED).exists())
        body=file.read_text()
        data=json.loads(body)
        self.assertTrue(data["source_only_not_live"])
        self.assertTrue(data["actual_isp_uptime_unverified"])
        self.assertFalse(any(x in body for x in (
            "11111111-2222","RxGoodBytes","TxGoodBytes","gpon_sn","loid"
        )))

    def test_atomic_replacement_switches_inode_without_partial_read(self):
        self.invoke("publish")
        first=(self.snapshot_dir/SNAPSHOT).read_bytes()
        inode=(self.snapshot_dir/SNAPSHOT).stat().st_ino
        self.invoke("republish")
        second=(self.snapshot_dir/SNAPSHOT).read_bytes()
        updated=(self.snapshot_dir/SNAPSHOT).stat().st_ino
        self.assertNotEqual(first,second)
        self.assertNotEqual(inode,updated)
        self.assertEqual(len(json.loads(first)["samples"]),3)
        self.assertEqual(len(json.loads(second)["samples"]),4)
        self.assertFalse((self.snapshot_dir/STAGED).exists())
        self.assertIn("AOTT_H026_CROSS_PROCESS_READ_PASS",
                      self.invoke("read"))

    def test_multiple_readers_across_republish_validate_their_own_response(self):
        self.invoke("publish")
        with ThreadPoolExecutor(max_workers=5) as pool:
            reads=[pool.submit(self.invoke,"read_concurrent") for _ in range(6)]
            self.invoke("republish")
            outputs=[f.result(timeout=15) for f in reads]
        for output in outputs:
            self.assertRegex(output,
                r"AOTT_H026_CONCURRENT_READ_(VALID samples=[34]|REFUSED code="
                r"snapshot_(inode_changed|readback_unverified))")
        # A quiescent reader must still succeed; refusing everything cannot pass.
        self.assertIn("AOTT_H026_CROSS_PROCESS_READ_PASS",self.invoke("read"))

    def test_malformed_json_is_not_relayed_to_http(self):
        self.invoke("publish")
        path=self.snapshot_dir/SNAPSHOT
        for bytestring in (
            b'{"serial":"SENSITIVE_DO_NOT_EXPORT"}',
            b'{"schema":1,"actual_isp_uptime_unverified":false}',
            b'{"samples":',
            b'[{"status":"true"}]',
        ):
            with self.subTest(payload=bytestring[:36]):
                path.write_bytes(bytestring)
                path.chmod(0o600)
                self.assertIn("AOTT_H026_INVALID_READ_DENIED",
                              self.invoke("read_invalid"))
        self.invoke("publish")
        self.assertIn("AOTT_H026_CROSS_PROCESS_READ_PASS",
                      self.invoke("read"))

    def test_vendor_jsonc_trailing_and_duplicate_keys_rejected(self):
        self.invoke("publish")
        path=self.snapshot_dir/SNAPSHOT
        genuine=path.read_bytes()
        variants=(
            genuine+b"HIDDEN_TRAILING_PRIVATE_DATA",
            genuine+b'{"private":"OTHER_TOP_LEVEL_OBJECT"}',
            genuine.replace(b'"schema":1',
                            b'"schema":1,"schema":1',1),
            genuine.replace(b'"kind":"aott_source_only_history"',
                            b'"kind":"SENSITIVE_PRECEDING_VALUE",'
                            b'"kind":"aott_source_only_history"',1),
        )
        for content in variants:
            with self.subTest(prefix=content[-35:]):
                self.assertNotEqual(content,genuine)
                path.write_bytes(content)
                path.chmod(0o600)
                self.assertIn("AOTT_H026_INVALID_READ_DENIED",
                              self.invoke("read_invalid"))
        path.write_bytes(genuine)
        path.chmod(0o600)
        self.invoke("read")

    def test_oversized_snapshot_rejected_before_json_processing(self):
        target=self.snapshot_dir/SNAPSHOT
        target.write_bytes(b"{" + b"x"*65600 + b"}")
        target.chmod(0o600)
        self.assertIn("AOTT_H026_INVALID_READ_DENIED",
                      self.invoke("read_invalid"))
        self.assertIn("AOTT_H026_PUBLICATION_DENIED",
                      self.invoke("publish_denied"))

    def test_snapshot_symlink_and_hardlink_are_never_followed(self):
        sentinel=self.snapshot_dir/"inert-sentinel"
        sentinel.write_text("DO_NOT_ACCESS")
        sentinel.chmod(0o600)
        target=self.snapshot_dir/SNAPSHOT
        target.symlink_to(sentinel)
        self.invoke("read_invalid")
        self.invoke("publish_denied")
        self.assertEqual(sentinel.read_text(),"DO_NOT_ACCESS")
        target.unlink()
        os.link(sentinel,target)
        self.invoke("read_invalid")
        self.invoke("publish_denied")
        self.assertEqual(sentinel.stat().st_nlink,2)
        self.assertEqual(sentinel.read_text(),"DO_NOT_ACCESS")

    def test_wrong_target_permissions_and_directory_mode_fail(self):
        target=self.snapshot_dir/SNAPSHOT
        target.write_text("{}")
        target.chmod(0o644)
        self.invoke("read_invalid")
        self.invoke("publish_denied")
        target.unlink()
        self.snapshot_dir.chmod(0o777)
        try:
            self.invoke("read_invalid")
            self.invoke("publish_denied")
        finally:
            self.snapshot_dir.chmod(0o700)
        self.assertFalse(target.exists())

    def test_regular_stale_stage_requires_lock_owner_to_discard(self):
        stage=self.snapshot_dir/STAGED
        stage.write_text("interrupted write")
        stage.chmod(0o600)
        self.assertIn("AOTT_H026_IPC_PUBLISH_PASS",
                      self.invoke("publish_blocked"))
        self.assertFalse(stage.exists())
        self.invoke("read")

    def test_symlink_stage_cannot_be_deleted_by_collector(self):
        sentinel=self.snapshot_dir/"sensitive-sentinel"
        sentinel.write_text("UNCHANGED")
        stage=self.snapshot_dir/STAGED
        stage.symlink_to(sentinel)
        self.assertIn("AOTT_H026_UNSAFE_STAGE_FAIL_CLOSED",
                      self.invoke("stale_stage"))
        self.assertTrue(stage.is_symlink())
        self.assertEqual(sentinel.read_text(),"UNCHANGED")
        self.assertFalse((self.snapshot_dir/SNAPSHOT).exists())


if __name__=="__main__":
    unittest.main()
