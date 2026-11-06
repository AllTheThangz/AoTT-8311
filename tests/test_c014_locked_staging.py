"""Native Lua staging lock and persistent single-use state, disposable only.
Real vendor-MIPS processes call real UCI against synthetic private packages.
"""
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import secrets
import select
import shutil
import stat
import subprocess
import unittest

import test_c014_native_uci_candidate as reference

ROOT=Path(__file__).resolve().parents[1]
GUARD=ROOT/"prototypes/configuration/8311/vlan_stage_guard.lua"
FIXTURE=ROOT/"tests/c014_locked_staging_fixture.lua"
VENDOR=reference.VENDOR
PENDING=b"AOTT-C014-SOURCE-STAGING-1\npending\n"
VALIDATED=b"AOTT-C014-SOURCE-STAGING-1\nvalidated\n"


class StagingGuardSourceTests(unittest.TestCase):
    def test_lua51_syntax(self):
        if not shutil.which("luac5.1"):
            self.skipTest("Lua compiler missing")
        for path in (GUARD,FIXTURE):
            result=subprocess.run(["luac5.1","-p",str(path)],capture_output=True,text=True,timeout=8)
            self.assertEqual(result.returncode,0,result.stderr)

    def test_no_live_path_activation_or_destructive_cleanup(self):
        source=GUARD.read_text()
        self.assertIn('mode~="offline_synthetic"',source)
        self.assertIn('fd:lock("tlock")',source)
        self.assertIn('if HELD[directory]',source)
        self.assertLess(source.index('if HELD[directory]'),source.index('fd=n.open'))
        for text in ("fs.unlink", "fs.rmdir", "os.execute", "io.popen", "/etc/config",
                     "/run/aott", "fwenv_set", "ifup", "network reload"):
            self.assertNotIn(text,source)
        self.assertNotIn('vlan_stage_guard.lua',(ROOT/"MANIFEST.json").read_text())
        self.assertFalse((ROOT/"overlay/usr/lib/lua/8311/vlan_stage_guard.lua").exists())

    def test_unrelated_paths_modes_and_forged_handles_refused_without_native_io(self):
        if not shutil.which("lua5.1"):
            self.skipTest("Host Lua missing")
        script='''package.path=arg[1].."/prototypes/configuration/?.lua;"..package.path
local m=require "8311.vlan_stage_guard"
for _,path in ipairs({"/etc","/tmp","/run/aott-staging","/var/tmp/aott-c014-stage-test-a",
 "/var/tmp/aott-c014-stage-test-0123456789abcdef/child"}) do
 local a,e=m.acquire(path,"offline_synthetic")
 assert(a==nil and e=="disallowed_staging_workspace")
end
local a,e=m.acquire("/var/tmp/aott-c014-stage-test-0123456789abcdef","production")
assert(a==nil and e=="disallowed_staging_workspace")
a,e=m.status({});assert(a==nil and e=="invalid_staging_handle")
a,e=m.close({});assert(a==nil and e=="invalid_staging_handle")
a,e=m.stage({}, {}, {}, "production");assert(a==nil and e=="staging_mode_not_authorized")
print("SOURCE_PATH_AND_MODE_REFUSAL_PASS")
'''
        result=subprocess.run(["lua5.1","-",str(ROOT)],input=script,capture_output=True,text=True,timeout=8)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertIn("SOURCE_PATH_AND_MODE_REFUSAL_PASS",result.stdout)


class NativeLockedStagingTests(unittest.TestCase):
    def setUp(self):
        if (not os.environ.get("AOTT_VENDOR_ROOTFS") or os.geteuid()!=0 or
                not shutil.which("qemu-mips-static") or not (VENDOR/"sbin/uci").is_file()):
            self.skipTest("Extracted vendor runtime and root-owned fixture directories required")
        self.root=Path("/var/tmp/aott-c014-stage-test-"+secrets.token_hex(8))
        self.root.mkdir(mode=0o700)
        self.namespace="aott_c014_"+secrets.token_hex(8)
        self.original={"network":reference.NETWORK.encode(),"firewall":reference.FIREWALL.encode()}
        for name in ("original","candidate","delta","cold"):
            (self.root/name).mkdir(mode=0o700)
        for pkg,data in self.original.items():
            for directory in ("original","candidate"):
                path=self.root/directory/(self.namespace+"_"+pkg)
                path.write_bytes(data);path.chmod(0o600)
        self.children=[]
        self.other=[]

    def tearDown(self):
        try:
            for child in self.children:
                if child.poll() is None:child.kill()
                child.communicate(timeout=10)
            for pkg,data in self.original.items():
                self.assertEqual((self.root/"original"/(self.namespace+"_"+pkg)).read_bytes(),data)
        finally:
            self.root.chmod(0o700)
            shutil.rmtree(self.root)
            for path in self.other:
                if path.is_symlink() or path.is_file():path.unlink()
                elif path.exists():shutil.rmtree(path)

    def command(self,action,target=123,fail_at=0,path=None):
        return ["qemu-mips-static","-L",str(VENDOR),str(VENDOR/"usr/bin/lua"),
            str(FIXTURE),str(VENDOR),str(ROOT),str(path or self.root),self.namespace,
            action,str(target),str(fail_at),"forward"]

    def invoke(self,action,**kw):
        result=subprocess.run(self.command(action,**kw),cwd=ROOT,capture_output=True,text=True,timeout=45)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertNotIn("SYNTHETIC_PRIVATE_ADAPTER_ERROR",result.stdout+result.stderr)
        return json.loads(result.stdout.strip().splitlines()[-1])

    def hold(self,action,barrier):
        child=subprocess.Popen(self.command(action),cwd=ROOT,stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,bufsize=1)
        self.children.append(child)
        self.assertTrue(select.select([child.stdout],[],[],20)[0],"Staging process did not reach barrier")
        line=child.stdout.readline().strip()
        self.assertEqual(line,barrier)
        return child

    def release(self,child):
        output,error=child.communicate("continue\n",timeout=45)
        self.assertEqual(child.returncode,0,error)
        return json.loads(output.strip().splitlines()[-1])

    def blocked(self,code,**kw):
        result=self.invoke("run",**kw)
        self.assertEqual(result["status"],"REJECTED")
        self.assertEqual(result["error"],code)
        self.assertEqual(result["native_calls"],0)
        self.assertEqual(result["mutations"],0)
        return result

    def current_bytes(self):
        return {p.name:p.read_bytes() for p in (self.root/"candidate").iterdir()}

    def test_actual_uci_success_is_marked_validated_and_never_reused(self):
        initial=self.current_bytes()
        result=self.invoke("run")
        self.assertEqual(result["status"],"SOURCE_LOCKED_UCI_CANDIDATE_VALIDATED")
        self.assertGreater(result["mutations"],10)
        self.assertTrue(result["no_live_apply"])
        self.assertNotEqual(initial,self.current_bytes())
        self.assertEqual((self.root/"stage.state").read_bytes(),VALIDATED)
        self.assertEqual((self.root/"stage.state").stat().st_mode&0o777,0o600)
        self.assertFalse((self.root/"stage.state.new").exists())
        self.blocked("staging_workspace_already_used")

    def test_competing_processes_never_reach_native_uci(self):
        child=self.hold("hold","AOTT_C014_STAGE_LOCK_HELD")
        lock=self.root/"stage.lock";inode=lock.stat().st_ino
        with ThreadPoolExecutor(max_workers=6) as pool:
            results=list(pool.map(lambda _:self.invoke("run"),range(12)))
        for result in results:
            self.assertEqual(result["error"],"staging_owned_by_other_process")
            self.assertEqual(result["native_calls"],0)
            self.assertEqual(result["mutations"],0)
        self.assertEqual(lock.stat().st_ino,inode)
        self.assertEqual(self.release(child)["status"],"SOURCE_STAGING_OWNER_RELEASED")
        self.assertEqual(self.invoke("try")["status"],"SOURCE_STAGING_OWNER_RELEASED")
        self.assertEqual(lock.stat().st_ino,inode)
        self.assertFalse((self.root/"stage.state").exists())

    def test_kill_before_stage_releases_kernel_lock_without_consuming_workspace(self):
        child=self.hold("hold","AOTT_C014_STAGE_LOCK_HELD")
        child.kill();child.communicate(timeout=10)
        self.assertEqual(self.invoke("run")["status"],"SOURCE_LOCKED_UCI_CANDIDATE_VALIDATED")

    def test_crash_after_pending_before_mutation_keeps_candidate_blocked(self):
        before=self.current_bytes()
        child=self.hold("pending_pause","AOTT_C014_STAGE_PENDING")
        self.assertEqual((self.root/"stage.state").read_bytes(),PENDING)
        self.blocked("staging_owned_by_other_process")
        child.kill();child.communicate(timeout=10)
        self.blocked("staging_workspace_already_used")
        self.assertEqual(before,self.current_bytes())
        self.assertEqual((self.root/"stage.state").read_bytes(),PENDING)

    def test_crash_after_first_mutation_leaves_pending_and_never_resumes(self):
        child=self.hold("mutation_pause","AOTT_C014_STAGE_FIRST_MUTATION")
        self.assertEqual((self.root/"stage.state").read_bytes(),PENDING)
        self.assertTrue(any((self.root/"delta").iterdir()))
        child.kill();child.communicate(timeout=10)
        self.blocked("staging_workspace_already_used")
        self.assertEqual((self.root/"stage.state").read_bytes(),PENDING)

    def test_crash_after_persisted_read_does_not_mislabel_success(self):
        before=self.current_bytes()
        child=self.hold("readback_pause","AOTT_C014_STAGE_PERSISTED_READ")
        self.assertNotEqual(before,self.current_bytes())
        child.kill();child.communicate(timeout=10)
        self.assertEqual((self.root/"stage.state").read_bytes(),PENDING)
        self.blocked("staging_workspace_already_used")

    def test_crash_after_validation_still_prevents_automatic_reuse(self):
        child=self.hold("validated_pause","AOTT_C014_STAGE_VALIDATED")
        self.assertEqual((self.root/"stage.state").read_bytes(),VALIDATED)
        child.kill();child.communicate(timeout=10)
        self.blocked("staging_workspace_already_used")

    def test_write_and_commit_failures_leave_pending_marker(self):
        # Use distinct root-owned workspaces for all independent failure cases.
        for step in (1,len(reference.plan(reference.state(),123)["operations"])+1,
                     len(reference.plan(reference.state(),123)["operations"])+2):
            with self.subTest(step=step):
                alternate=Path("/var/tmp/aott-c014-stage-test-"+secrets.token_hex(8))
                shutil.copytree(self.root,alternate);alternate.chmod(0o700);self.other.append(alternate)
                result=self.invoke("run",fail_at=step,path=alternate)
                self.assertEqual(result["status"],"REJECTED")
                self.assertEqual(result["error"],"staging_candidate_rejected")
                self.assertEqual(result["mutations"],step)
                self.assertEqual((alternate/"stage.state").read_bytes(),PENDING)
                self.blocked("staging_workspace_already_used",path=alternate)

    def test_nested_stage_close_and_acquire_do_not_release_the_owner(self):
        result=self.invoke("nested")
        self.assertEqual(result["status"],"SOURCE_LOCKED_UCI_CANDIDATE_VALIDATED")
        self.blocked("staging_workspace_already_used")

    def test_adapter_exception_is_redacted_and_workspace_quarantined(self):
        before=self.current_bytes()
        result=self.invoke("exception")
        self.assertEqual(result["error"],"staging_candidate_rejected")
        self.assertEqual(result["mutations"],0)
        self.assertEqual(before,self.current_bytes())
        self.assertEqual((self.root/"stage.state").read_bytes(),PENDING)
        self.blocked("staging_workspace_already_used")

    def test_adapter_for_wrong_workspace_refused_without_pending_marker(self):
        result=self.invoke("wrong_workspace")
        self.assertEqual(result["error"],"private_workspace_adapter_required")
        self.assertEqual(result["mutations"],0)
        self.assertFalse((self.root/"stage.state").exists())
        self.assertEqual(self.invoke("run")["status"],"SOURCE_LOCKED_UCI_CANDIDATE_VALIDATED")

    def test_stale_candidate_and_readback_mismatch_are_not_marked_validated(self):
        for action in ("stale","bad_readback"):
            alternate=Path("/var/tmp/aott-c014-stage-test-"+secrets.token_hex(8))
            shutil.copytree(self.root,alternate);alternate.chmod(0o700);self.other.append(alternate)
            with self.subTest(action=action):
                result=self.invoke(action,path=alternate)
                self.assertEqual(result["error"],"staging_candidate_rejected")
                self.assertEqual((alternate/"stage.state").read_bytes(),PENDING)
                self.blocked("staging_workspace_already_used",path=alternate)

    def test_lock_replacement_during_stage_refused_before_writes(self):
        before=self.current_bytes()
        child=self.hold("pending_pause","AOTT_C014_STAGE_PENDING")
        lock=self.root/"stage.lock";lock.rename(self.root/"old_stage.lock")
        lock.write_bytes(b"");lock.chmod(0o600)
        result=self.release(child)
        self.assertEqual(result["error"],"staging_lock_identity_changed")
        self.assertEqual(result["mutations"],0)
        self.assertEqual(before,self.current_bytes())
        self.assertTrue((self.root/"old_stage.lock").exists())
        self.blocked("staging_workspace_already_used")

    def test_directory_permission_change_during_stage_blocks_commands(self):
        child=self.hold("pending_pause","AOTT_C014_STAGE_PENDING")
        self.root.chmod(0o755)
        try:
            result=self.release(child)
            self.assertEqual(result["error"],"staging_directory_changed")
            self.assertEqual(result["mutations"],0)
        finally:self.root.chmod(0o700)
        self.blocked("staging_workspace_already_used")

    def test_marker_tamper_during_stage_blocks_commands(self):
        child=self.hold("pending_pause","AOTT_C014_STAGE_PENDING")
        (self.root/"stage.state").write_bytes(VALIDATED)
        result=self.release(child)
        self.assertEqual(result["error"],"staging_marker_changed")
        self.assertEqual(result["mutations"],0)
        self.blocked("staging_workspace_already_used")

    def test_directory_modes_and_symlink_are_refused_before_native_reads(self):
        self.root.chmod(0o755)
        try:self.blocked("unsafe_staging_directory")
        finally:self.root.chmod(0o700)
        alias=Path("/var/tmp/aott-c014-stage-test-"+secrets.token_hex(8))
        alias.symlink_to(self.root);self.other.append(alias)
        self.blocked("unsafe_staging_directory",path=alias)
        self.assertFalse((self.root/"stage.lock").exists())

    def test_unsafe_lock_inodes_permissions_links_and_types_refused(self):
        lock=self.root/"stage.lock"
        sentinel=self.root/"sentinel";sentinel.write_text("UNTOUCHED");sentinel.chmod(0o600)
        for kind in ("symlink","hardlink","fifo","wrong_mode","nonempty"):
            with self.subTest(kind=kind):
                if kind=="symlink":lock.symlink_to(sentinel)
                elif kind=="hardlink":os.link(sentinel,lock)
                elif kind=="fifo":os.mkfifo(lock,0o600)
                else:
                    lock.write_bytes(b"data" if kind=="nonempty" else b"")
                    lock.chmod(0o644 if kind=="wrong_mode" else 0o600)
                self.blocked("unsafe_staging_lock")
                self.assertEqual(sentinel.read_text(),"UNTOUCHED")
                lock.unlink()

    def test_previous_markers_or_partial_marker_never_overwritten(self):
        for name in ("stage.state","stage.state.new"):
            with self.subTest(name=name):
                path=self.root/name;path.write_bytes(b"SYNTHETIC_PRIVATE_MARKER");path.chmod(0o600)
                self.blocked("staging_workspace_already_used")
                self.assertEqual(path.read_bytes(),b"SYNTHETIC_PRIVATE_MARKER")
                path.unlink()

    def test_noop_still_single_use_but_no_uci_mutations(self):
        before=self.current_bytes()
        result=self.invoke("run",target=0)
        self.assertEqual(result["status"],"SOURCE_LOCKED_UCI_CANDIDATE_VALIDATED")
        self.assertEqual(result["mutations"],0)
        self.assertEqual(before,self.current_bytes())
        self.assertEqual((self.root/"stage.state").read_bytes(),VALIDATED)

    def test_pending_marker_sync_failure_prevents_candidate_writes(self):
        before=self.current_bytes()
        result=self.invoke("pending_sync_failure")
        self.assertEqual(result["error"],"staging_marker_sync_failed")
        self.assertEqual(result["mutations"],0)
        self.assertEqual(before,self.current_bytes())
        self.assertFalse((self.root/"stage.state").exists())
        self.assertTrue((self.root/"stage.state.new").exists())
        self.blocked("staging_workspace_already_used")

    def test_final_marker_sync_failure_does_not_certify_completed_candidate(self):
        before=self.current_bytes()
        result=self.invoke("final_sync_failure")
        self.assertEqual(result["error"],"staging_marker_sync_failed")
        self.assertGreater(result["mutations"],10)
        self.assertNotEqual(before,self.current_bytes())
        self.assertEqual((self.root/"stage.state").read_bytes(),PENDING)
        self.assertTrue((self.root/"stage.state.new").exists())
        self.blocked("staging_workspace_already_used")

    def test_marker_replace_failure_keeps_partial_state_without_candidate_writes(self):
        result=self.invoke("marker_rename_failure")
        self.assertEqual(result["error"],"staging_marker_replace_failed")
        self.assertEqual(result["mutations"],0)
        self.assertTrue((self.root/"stage.state.new").is_file())
        self.assertFalse((self.root/"stage.state").exists())
        self.blocked("staging_workspace_already_used")

    def test_prior_symlink_state_is_never_followed_or_removed(self):
        sentinel=self.root/"sentinel";sentinel.write_bytes(b"DO_NOT_READ_OR_MODIFY")
        for name in ("stage.state","stage.state.new"):
            path=self.root/name
            with self.subTest(name=name):
                path.symlink_to(sentinel)
                self.blocked("staging_workspace_already_used")
                self.assertTrue(path.is_symlink())
                self.assertEqual(sentinel.read_bytes(),b"DO_NOT_READ_OR_MODIFY")
                path.unlink()

    def test_wrong_lock_owner_and_group_are_refused(self):
        if os.environ.get("AOTT_IMMUTABLE_METADATA_FIXTURES") == "v1":
            # The capability-free user namespace cannot create a foreign-owner
            # inode. The trusted runtime supplies real, immutable inodes, not
            # mocked stat results. The same native guard and refusal assertions
            # run against their exact ownership before any candidate operation.
            fixtures=(("f000000000000001",65534,0),("f000000000000002",0,65534))
            for suffix,uid,gid in fixtures:
                with self.subTest(uid=uid,gid=gid):
                    directory=Path("/var/tmp/aott-c014-stage-test-"+suffix)
                    parent=directory.lstat();path=directory/"stage.lock";before=path.lstat()
                    self.assertTrue(stat.S_ISDIR(parent.st_mode))
                    self.assertEqual((parent.st_uid,parent.st_gid,stat.S_IMODE(parent.st_mode)),(0,0,0o700))
                    self.assertTrue(stat.S_ISREG(before.st_mode))
                    self.assertEqual((before.st_uid,before.st_gid,stat.S_IMODE(before.st_mode),before.st_size,before.st_nlink),
                                     (uid,gid,0o600,0,1))
                    self.assertTrue(os.statvfs(directory).f_flag & os.ST_RDONLY)
                    self.blocked("unsafe_staging_lock",path=directory)
                    after=path.lstat()
                    self.assertEqual((after.st_dev,after.st_ino,after.st_uid,after.st_gid,after.st_mode),
                                     (before.st_dev,before.st_ino,before.st_uid,before.st_gid,before.st_mode))
            return
        path=self.root/"stage.lock";path.write_bytes(b"");path.chmod(0o600)
        try:
            for uid,gid in ((65534,0),(0,65534)):
                with self.subTest(uid=uid,gid=gid):
                    os.chown(path,uid,gid)
                    self.blocked("unsafe_staging_lock")
        finally:os.chown(path,0,0)

    def test_marker_changed_after_first_write_stops_all_following_mutations(self):
        child=self.hold("mutation_pause","AOTT_C014_STAGE_FIRST_MUTATION")
        (self.root/"stage.state").write_bytes(VALIDATED)
        result=self.release(child)
        self.assertEqual(result["error"],"staging_marker_changed")
        self.assertEqual(result["mutations"],1)
        self.blocked("staging_workspace_already_used")

    def test_replaced_workspace_directory_inode_is_refused(self):
        child=self.hold("pending_pause","AOTT_C014_STAGE_PENDING")
        old=Path(str(self.root)+"-retained")
        self.root.rename(old);self.other.append(old)
        shutil.copytree(old,self.root);self.root.chmod(0o700)
        result=self.release(child)
        self.assertEqual(result["error"],"staging_directory_changed")
        self.assertEqual(result["mutations"],0)
        self.blocked("staging_workspace_already_used")

    def test_lock_permission_change_during_stage_stops_before_mutation(self):
        child=self.hold("pending_pause","AOTT_C014_STAGE_PENDING")
        path=self.root/"stage.lock";path.chmod(0o644)
        try:
            result=self.release(child)
            self.assertEqual(result["error"],"staging_lock_identity_changed")
            self.assertEqual(result["mutations"],0)
        finally:path.chmod(0o600)
        self.blocked("staging_workspace_already_used")

    def test_double_close_does_not_unlink_lock(self):
        result=self.invoke("double_close")
        self.assertEqual(result["status"],"SOURCE_DOUBLE_CLOSE_REFUSED")
        self.assertTrue((self.root/"stage.lock").is_file())
        self.assertEqual(self.invoke("try")["status"],"SOURCE_STAGING_OWNER_RELEASED")


if __name__=="__main__":
    unittest.main()
