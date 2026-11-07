"""Actual vendor-MIPS integration of staging, two-file activation and recovery.
All active/source/candidate files belong to disposable synthetic fixtures.
"""
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path
import secrets
import select
import shutil
import subprocess
import time
import unittest

import test_c014_native_uci_candidate as reference

ROOT=Path(__file__).resolve().parents[1]
MODULE=ROOT/"prototypes/configuration/8311/vlan_transaction.lua"
FIXTURE=ROOT/"tests/c014_transaction_fixture.lua"
VENDOR=reference.VENDOR


class TransactionSourceTests(unittest.TestCase):
    def test_lua51_syntax(self):
        if not shutil.which("luac5.1"):self.skipTest("Host Lua compiler missing")
        for path in (MODULE,FIXTURE):
            r=subprocess.run(["luac5.1","-p",str(path)],capture_output=True,text=True,timeout=8)
            self.assertEqual(r.returncode,0,r.stderr)

    def test_production_paths_modes_and_unknown_roots_refused(self):
        if not shutil.which("lua5.1"):self.skipTest("Host Lua interpreter missing")
        code='''package.path=arg[1].."/prototypes/configuration/?.lua;"..package.path
local tx=require "8311.vlan_transaction"
for _,path in ipairs({"/etc/config","/ptconf","/var/tmp","/var/tmp/aott-c014-txn-test-a",
 "/var/tmp/aott-c014-txn-test-0123456789abcdef/child"}) do
 local a,e=tx.preview(path,"offline_synthetic")
 assert(a==nil and e=="transaction_directory_not_authorized")
 a,e=tx.recover(path,"offline_synthetic")
 assert(a==nil and e=="transaction_directory_not_authorized")
end
local a,e=tx.preview("/var/tmp/aott-c014-txn-test-0123456789abcdef","production")
assert(a==nil and e=="transaction_directory_not_authorized")
print("TRANSACTION_SCOPE_REFUSAL_PASS")
'''
        r=subprocess.run(["lua5.1","-",str(ROOT)],input=code,capture_output=True,text=True,timeout=8)
        self.assertEqual(r.returncode,0,r.stderr)
        self.assertIn("TRANSACTION_SCOPE_REFUSAL_PASS",r.stdout)

    def test_integration_not_separate_fake_save_or_live_overlay(self):
        text=MODULE.read_text()
        for token in ('require "8311.vlan_transition"','require "8311.vlan_stage_guard"',
                      'guard.stage(handle,plan,adapter,mode)','fd:lock("tlock")',
                      'j.phase="rolling_back"','j.phase="confirmed"','j.phase="rolled_back"'):
            self.assertIn(token,text)
        for forbidden in ('fwenv_set','mtd write','ifup ', 'network reload', 'uhttpd restart'):
            self.assertNotIn(forbidden,text)
        self.assertNotIn('vlan_transaction.lua',(ROOT/"MANIFEST.json").read_text())
        self.assertFalse((ROOT/"overlay/usr/lib/lua/8311/vlan_transaction.lua").exists())


class NativeTransactionTests(unittest.TestCase):
    def setUp(self):
        if (not os.environ.get("AOTT_VENDOR_ROOTFS") or os.geteuid()!=0 or
            not shutil.which("qemu-mips-static") or not (VENDOR/"sbin/uci").is_file()):
            self.skipTest("Private vendor MIPS runtime and root-owned fixture required")
        self.directories=[];self.children=[];self.admission_workers={}
        self.setup_case()

    def setup_case(self):
        self.suffix=secrets.token_hex(8)
        self.root=Path("/var/tmp/aott-c014-txn-test-"+self.suffix)
        self.stage=Path("/var/tmp/aott-c014-stage-test-"+secrets.token_hex(8))
        for p in (self.root,self.stage):p.mkdir(mode=0o700);self.directories.append(p)
        for p in (self.root/"active",self.root/"source",self.stage/"candidate",self.stage/"delta",self.stage/"cold"):
            p.mkdir(mode=0o700)
        self.original={"network":reference.NETWORK.encode(),"firewall":reference.FIREWALL.encode()}
        self.packages={p:"aott_c014_"+self.suffix+"_"+p for p in self.original}
        for pkg,raw in self.original.items():
            for directory in (self.root/"active",self.root/"source",self.stage/"candidate"):
                p=directory/self.packages[pkg];p.write_bytes(raw);p.chmod(0o600)

    def tearDown(self):
        try:
            for child in self.children:
                if child.poll() is None:child.kill()
                child.communicate(timeout=10)
            for directory in self.directories:
                if not directory.name.startswith("aott-c014-txn-test-"):continue
                for pkg,raw in self.original.items():
                    suffix=directory.name.split("aott-c014-txn-test-",1)[1]
                    p=directory/"source"/("aott_c014_"+suffix+"_"+pkg)
                    self.assertEqual(p.read_bytes(),raw)
        finally:
            for directory in self.directories:
                if directory.is_symlink():directory.unlink()
                elif directory.exists():directory.chmod(0o700);shutil.rmtree(directory)

    def ensure_recovery_worker(self,root):
        root=Path(root)
        # Rejected malformed-directory tests must not be "fixed" by fixture setup.
        if (root.stat().st_mode&0o777)!=0o700 or ((root/"active").stat().st_mode&0o777)!=0o700:
            return
        worker=self.admission_workers.get(str(root))
        if worker is not None:
            return  # Do not silently replace a dead worker during a transaction.
        command=["qemu-mips-static","-L",str(VENDOR),str(VENDOR/"usr/bin/lua"),str(FIXTURE),
            str(VENDOR),str(ROOT),str(root),str(self.stage),"admission_watch","120","none","none","none"]
        worker=subprocess.Popen(command,cwd=ROOT,stdin=subprocess.PIPE,stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,text=True)
        self.children.append(worker)
        self.assertTrue(select.select([worker.stdout],[],[],10)[0],"Recovery worker did not announce readiness")
        self.assertEqual(worker.stdout.readline().strip(),"AOTT_RECOVERY_ADMISSION_READY")
        self.admission_workers[str(root)]=worker

    def command(self,action="begin",ttl=30,point="none",fault="none",token="none",root=None):
        if action=="begin":self.ensure_recovery_worker(root or self.root)
        return ["qemu-mips-static","-L",str(VENDOR),str(VENDOR/"usr/bin/lua"),str(FIXTURE),
            str(VENDOR),str(ROOT),str(root or self.root),str(self.stage),action,str(ttl),point,fault,token]

    def invoke(self,action="begin",exit_code=0,**kw):
        if action=="recover":
            # These cases fault-inject the explicit manual-recovery caller.
            # Stop the separate worker first so it cannot finish that recovery
            # before the requested crash point. Automatic-worker paths are
            # exercised separately with the real worker left running.
            worker=self.admission_workers.get(str(kw.get("root") or self.root))
            if worker is not None and worker.poll() is None:
                worker.kill();worker.wait(timeout=10)
        r=subprocess.run(self.command(action,**kw),cwd=ROOT,capture_output=True,text=True,timeout=45)
        self.assertEqual(r.returncode,exit_code,r.stderr)
        self.assertNotIn("SYNTHETIC_PRIVATE_HEALTH",r.stdout+r.stderr)
        self.assertNotIn("SYNTHETIC_PRIVATE_ACTIVATION",r.stdout+r.stderr)
        if exit_code:return r
        return json.loads(r.stdout.strip().splitlines()[-1])

    def active(self):return {p:(self.root/"active"/self.packages[p]).read_bytes() for p in self.original}
    def phase(self):return (self.root/"transaction.state").read_text().splitlines()[1]
    def token(self):return (self.root/"transaction.state").read_text().splitlines()[2]
    def pending(self,**kw):
        r=self.invoke(**kw)
        self.assertEqual(r["status"],"SOURCE_TXN_PENDING_CONFIRMATION")
        self.assertEqual(r["phase"],"pending")
        return r["transaction_id"]
    def restored(self,r):
        self.assertEqual(r["status"],"SOURCE_TXN_ROLLED_BACK")
        self.assertEqual(self.active(),self.original)
        self.assertEqual(self.phase(),"rolled_back")
    def pause(self,action,point):
        child=subprocess.Popen(self.command(action,point=point,fault="pause"),cwd=ROOT,
            stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
        self.children.append(child)
        self.assertTrue(select.select([child.stdout],[],[],20)[0],"Transaction failed to reach barrier")
        self.assertEqual(child.stdout.readline().strip(),"AOTT_TRANSACTION_BARRIER:"+point)
        return child
    def finish(self,child):
        out,err=child.communicate("continue\n",timeout=45)
        self.assertEqual(child.returncode,0,err)
        return json.loads(out.strip().splitlines()[-1])

    def test_integrated_stage_and_apply_await_explicit_confirmation(self):
        token=self.pending()
        self.assertNotEqual(self.active(),self.original)
        self.assertEqual((self.stage/"stage.state").read_text().splitlines()[1],"validated")
        for pkg,raw in self.active().items():
            self.assertEqual(raw,(self.root/("candidate."+pkg)).read_bytes())
            self.assertEqual(self.original[pkg],(self.root/("previous."+pkg)).read_bytes())
        result=self.invoke("expire")
        self.assertEqual(result["status"],"SOURCE_TXN_PENDING_CONFIRMATION")
        self.assertEqual(result["transaction_id"],token)
        self.assertFalse(result["contains_configuration_values"])
        self.assertTrue(result["no_real_network_apply"])

    def test_confirmation_retains_candidate_after_recovery_process(self):
        token=self.pending();after=self.active()
        r=self.invoke("confirm",token=token)
        self.assertEqual(r["status"],"SOURCE_TXN_CONFIRMED")
        self.assertEqual(self.phase(),"confirmed")
        self.assertEqual(self.invoke("recover")["status"],"SOURCE_TXN_CONFIRMED")
        self.assertEqual(self.active(),after)

    def test_unconfirmed_explicit_recovery_restores_both_original_packages(self):
        self.pending()
        self.restored(self.invoke("recover"))
        self.restored(self.invoke("recover"))
        self.assertEqual(self.invoke()["status"],"REJECTED")

    def test_independent_watch_process_rolls_back_when_confirmation_is_absent(self):
        child=subprocess.Popen(self.command("watch"),cwd=ROOT,stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
        self.children.append(child)
        self.assertTrue(select.select([child.stdout],[],[],10)[0])
        self.assertEqual(child.stdout.readline().strip(),"AOTT_TRANSACTION_WATCH_READY")
        # A short real deadline can expire while apply is still running.
        # Both early caller rollback and later worker rollback are correct;
        # a separate barrier test requires worker-only recovery after pending.
        applied=self.invoke(ttl=2)
        self.assertIn(applied["status"],("SOURCE_TXN_PENDING_CONFIRMATION","SOURCE_TXN_ROLLED_BACK"))
        if applied["status"]=="SOURCE_TXN_ROLLED_BACK":self.restored(applied)
        out,err=child.communicate(timeout=15)
        self.assertEqual(child.returncode,0,err)
        self.restored(json.loads(out.strip().splitlines()[-1]))

    def test_confirmation_after_deadline_rolls_back_instead(self):
        transaction_id=self.pending()
        self.restored(self.invoke("confirm",token=transaction_id,fault="clock_after_deadline"))

    def test_confirmation_exactly_at_deadline_rolls_back(self):
        transaction_id=self.pending()
        self.restored(self.invoke("confirm",token=transaction_id,fault="clock_at_deadline"))

    def test_confirmation_one_tick_before_deadline_can_commit(self):
        transaction_id=self.pending();after=self.active()
        result=self.invoke("confirm",token=transaction_id,fault="clock_before_deadline")
        self.assertEqual(result["status"],"SOURCE_TXN_CONFIRMED")
        self.assertEqual(self.phase(),"confirmed")
        self.assertEqual(self.active(),after)

    def test_deadline_during_apply_returns_verified_rollback_not_pending(self):
        child=subprocess.Popen(self.command("begin",ttl=1,point="activate_firewall",fault="pause"),
            cwd=ROOT,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
        self.children.append(child)
        self.assertTrue(select.select([child.stdout],[],[],20)[0])
        self.assertEqual(child.stdout.readline().strip(),"AOTT_TRANSACTION_BARRIER:activate_firewall")
        self.assertEqual(self.phase(),"pending")
        self.assertNotEqual(self.active(),self.original)
        deadline=int((self.root/"transaction.state").read_text().splitlines()[5])
        until=time.monotonic()+5
        while int(float(Path('/proc/uptime').read_text().split()[0]))<deadline and time.monotonic()<until:
            time.sleep(0.05)
        self.assertGreaterEqual(int(float(Path('/proc/uptime').read_text().split()[0])),deadline)
        self.restored(self.finish(child))
        self.restored(self.invoke("recover"))

    def test_independent_worker_recovers_only_after_caller_returned_pending(self):
        child=subprocess.Popen(self.command("watch",fault="watch_after_pending"),cwd=ROOT,
            stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
        self.children.append(child)
        self.assertTrue(select.select([child.stdout],[],[],10)[0])
        self.assertEqual(child.stdout.readline().strip(),"AOTT_TRANSACTION_WATCH_READY")
        transaction_id=self.pending()
        self.assertEqual(self.phase(),"pending")
        self.assertNotEqual(self.active(),self.original)
        result=self.finish(child)
        self.assertEqual(result["transaction_id"],transaction_id)
        self.restored(result)

    def test_watch_does_not_undo_explicitly_confirmed_transaction(self):
        token=self.pending(ttl=10);self.invoke("confirm",token=token);after=self.active()
        r=self.invoke("watch")
        self.assertEqual(r["status"],"SOURCE_TXN_CONFIRMED")
        self.assertEqual(after,self.active())

    def test_boot_change_or_backward_monotonic_clock_trigger_recovery(self):
        for fault in ("changed_boot","backward_clock"):
            with self.subTest(fault=fault):
                self.setup_case();self.pending()
                self.restored(self.invoke("expire",fault=fault))

    def test_failed_activation_or_readback_rolls_back_immediately(self):
        for fault in ("activation_failed","activation_exception","bad_active_readback"):
            with self.subTest(fault=fault):
                self.setup_case()
                r=self.invoke(fault=fault);self.restored(r)
                self.assertFalse(r["apply_accepted"])

    def test_failed_confirmation_health_or_probe_exception_rolls_back(self):
        for fault in ("management_failed","forwarding_failed","recovery_failed","health_exception"):
            with self.subTest(fault=fault):
                self.setup_case();token=self.pending()
                r=self.invoke("confirm",fault=fault,token=token)
                self.restored(r);self.assertFalse(r["confirmation_accepted"])

    def test_wrong_confirmation_token_never_confirms_or_mutates(self):
        self.pending();before=self.active()
        r=self.invoke("confirm",token="0"*32)
        self.assertEqual(r["error"],"transaction_confirmation_id_mismatch")
        self.assertEqual(self.phase(),"pending");self.assertEqual(self.active(),before)
        self.restored(self.invoke("recover"))

    def test_confirmation_requires_explicit_operator_consent(self):
        token=self.pending();after=self.active()
        r=self.invoke("confirm",token=token,fault="no_consent")
        self.assertEqual(r["error"],"confirmation_adapter_not_qualified")
        self.assertEqual(self.active(),after)
        self.restored(self.invoke("recover"))

    def test_stale_preview_invalid_vlan_wrong_adapter_or_no_consent_never_applies(self):
        for fault in ("stale_preview","invalid_vlan","wrong_adapter","no_consent"):
            with self.subTest(fault=fault):
                self.setup_case();r=self.invoke(fault=fault)
                self.assertEqual(r["status"],"REJECTED")
                self.assertEqual(self.active(),self.original)
                self.assertFalse((self.root/"transaction.state").exists())

    def test_crash_after_pending_and_each_package_replacement_is_recoverable(self):
        for point in ("journal_pending","activate_network","activate_firewall"):
            with self.subTest(point=point):
                self.setup_case();self.invoke(point=point,fault="crash",exit_code=87)
                self.assertEqual(self.phase(),"pending")
                self.restored(self.invoke("recover"))

    def test_partial_scratch_after_activation_crash_is_never_used_as_source(self):
        self.invoke(point="activate_firewall",fault="partial_scratch_crash",exit_code=87)
        self.assertNotEqual(self.active()["network"],self.original["network"])
        self.restored(self.invoke("recover"))
        self.assertNotIn(b"partial_synthetic",b"".join(self.active().values()))

    def test_crashes_before_pending_never_change_active_configuration(self):
        for point in ("previous_network","previous_firewall","candidate_network","candidate_firewall"):
            with self.subTest(point=point):
                self.setup_case();self.invoke(point=point,fault="crash",exit_code=87)
                self.assertEqual(self.active(),self.original)
                self.assertFalse((self.root/"transaction.state").exists())
                self.assertEqual(self.invoke("recover")["error"],"transaction_not_armed")
                self.assertEqual(self.invoke()["status"],"REJECTED")

    def test_recovery_is_repeatable_after_crash_at_each_rollback_step(self):
        for point in ("journal_rolling_back","restore_network","restore_firewall","journal_rolled_back"):
            with self.subTest(point=point):
                self.setup_case();self.pending()
                self.invoke("recover",point=point,fault="crash",exit_code=87)
                self.restored(self.invoke("recover"))

    def test_partial_scratch_during_rollback_is_safely_replaced_on_retry(self):
        self.pending()
        self.invoke("recover",point="restore_network",fault="partial_scratch_crash",exit_code=87)
        self.assertEqual(self.phase(),"rolling_back")
        self.restored(self.invoke("recover"))
        self.assertFalse((self.root/"active"/(self.packages["network"]+".new")).exists())

    def test_crash_after_confirmation_marker_preserves_candidate(self):
        token=self.pending();after=self.active()
        self.invoke("confirm",token=token,point="journal_confirmed",fault="crash",exit_code=87)
        self.assertEqual(self.phase(),"confirmed")
        self.assertEqual(self.invoke("recover")["status"],"SOURCE_TXN_CONFIRMED")
        self.assertEqual(self.active(),after)

    def test_crash_before_confirmation_marker_rolls_back_on_recovery(self):
        token=self.pending()
        self.invoke("confirm",token=token,point="journal_confirmed",fault="partial_scratch_crash",exit_code=87)
        self.assertEqual(self.phase(),"pending")
        self.restored(self.invoke("recover"))

    def test_active_replace_failure_automatically_restores_both_packages(self):
        for point in ("activate_network","activate_firewall"):
            with self.subTest(point=point):
                self.setup_case();r=self.invoke(point=point,fault="replace_fail")
                self.restored(r)

    def test_rollback_replace_failure_retains_recovery_state_for_next_process(self):
        self.pending()
        r=self.invoke("recover",point="restore_firewall",fault="replace_fail")
        self.assertEqual(r["error"],"transaction_replace_failed")
        self.assertEqual(self.phase(),"rolling_back")
        self.restored(self.invoke("recover"))

    def test_bad_backup_or_candidate_hash_refuses_without_overwriting_active(self):
        for path,code in (("previous.network","transaction_backup_mismatch"),
                          ("candidate.firewall","transaction_candidate_mismatch")):
            with self.subTest(file=path):
                self.setup_case();self.pending();after=self.active()
                (self.root/path).write_bytes(b"SYNTHETIC_PRIVATE_CORRUPTION")
                r=self.invoke("recover")
                self.assertEqual(r["error"],code)
                self.assertEqual(self.active(),after);self.assertEqual(self.phase(),"pending")

    def test_unknown_active_changes_are_not_blindly_overwritten(self):
        self.pending()
        path=self.root/"active"/self.packages["firewall"]
        path.write_bytes(b"SYNTHETIC_PRIVATE_FOREIGN_CHANGE")
        before=self.active()
        r=self.invoke("recover")
        self.assertEqual(r["error"],"transaction_unknown_active_content")
        self.assertEqual(self.active(),before);self.assertEqual(self.phase(),"pending")

    def test_corrupt_journal_refuses_without_writes_or_disclosure(self):
        self.pending();after=self.active()
        (self.root/"transaction.state").write_bytes(b"SYNTHETIC_PRIVATE_JOURNAL")
        r=self.invoke("recover")
        self.assertEqual(r["error"],"transaction_journal_invalid")
        self.assertEqual(self.active(),after)
        self.assertNotIn("SYNTHETIC_PRIVATE",json.dumps(r))

    def test_locked_apply_blocks_independent_confirm_and_recover_processes(self):
        child=self.pause("begin","activate_network");before=self.active()
        with ThreadPoolExecutor(max_workers=4) as pool:
            results=list(pool.map(lambda _:self.invoke("recover"),range(8)))
        for r in results:self.assertEqual(r["error"],"transaction_busy")
        self.assertEqual(self.active(),before)
        child.kill();child.communicate(timeout=10)
        self.restored(self.invoke("recover"))

    def test_recursive_call_does_not_release_outer_transaction_lock(self):
        token=self.pending(fault="nested_call")
        self.assertEqual(len(token),32)
        self.restored(self.invoke("recover"))

    def test_confirmed_or_restored_files_changed_later_are_not_repaired_silently(self):
        for confirmed in (True,False):
            with self.subTest(confirmed=confirmed):
                self.setup_case();token=self.pending()
                if confirmed:self.invoke("confirm",token=token)
                else:self.invoke("recover")
                replacement=(self.root/("previous.network" if confirmed else "candidate.network")).read_bytes()
                (self.root/"active"/self.packages["network"]).write_bytes(replacement)
                before=self.active();r=self.invoke("recover")
                self.assertEqual(r["error"],"confirmed_state_changed" if confirmed else "rolled_back_state_changed")
                self.assertEqual(before,self.active())

    def test_symlink_hardlink_or_wrong_mode_backups_are_rejected(self):
        for kind in ("symlink","hardlink","mode"):
            with self.subTest(kind=kind):
                self.setup_case();self.pending();after=self.active()
                path=self.root/"previous.network"
                if kind=="mode":path.chmod(0o644)
                else:
                    path.unlink();source=self.root/"source"/self.packages["network"]
                    if kind=="symlink":path.symlink_to(source)
                    else:os.link(source,path)
                r=self.invoke("recover")
                self.assertEqual(r["error"],"unsafe_transaction_file")
                self.assertEqual(after,self.active())

    def test_symlink_scratch_is_not_followed_or_deleted(self):
        self.pending()
        scratch=self.root/"active"/(self.packages["network"]+".new")
        sentinel=self.root/"sentinel";sentinel.write_bytes(b"DO_NOT_TOUCH")
        scratch.symlink_to(sentinel)
        before=self.active();r=self.invoke("recover")
        self.assertEqual(r["error"],"unsafe_transaction_scratch")
        self.assertTrue(scratch.is_symlink());self.assertEqual(sentinel.read_bytes(),b"DO_NOT_TOUCH")
        self.assertEqual(before,self.active())

    def test_invalid_lock_or_directory_modes_prevent_operations(self):
        for kind in ("lock_mode","lock_symlink","root_mode","active_mode"):
            with self.subTest(kind=kind):
                self.setup_case()
                lock=self.root/"transaction.lock"
                if kind=="lock_mode":lock.write_bytes(b"");lock.chmod(0o644)
                elif kind=="lock_symlink":lock.symlink_to(self.root/"source"/self.packages["network"])
                elif kind=="root_mode":self.root.chmod(0o755)
                else:(self.root/"active").chmod(0o755)
                r=self.invoke()
                self.assertEqual(r["status"],"REJECTED")
                self.assertEqual(self.active(),self.original)
                self.assertFalse((self.root/"transaction.state").exists())

    def test_pending_journal_sync_failure_never_activates_any_package(self):
        r=self.invoke(point="journal_pending_sync",fault="sync_fail")
        self.assertEqual(r["error"],"transaction_write_sync_failed")
        self.assertEqual(self.active(),self.original)
        self.assertFalse((self.root/"transaction.state").exists())
        self.assertTrue((self.root/"transaction.state.new").exists())
        self.assertEqual(self.invoke("recover")["error"],"transaction_not_armed")

    def test_confirmation_journal_sync_failure_retains_unconfirmed_recovery(self):
        token=self.pending()
        r=self.invoke("confirm",token=token,point="journal_confirmed_sync",fault="sync_fail")
        self.assertEqual(r["error"],"transaction_write_sync_failed")
        self.assertEqual(self.phase(),"pending")
        self.restored(self.invoke("recover"))

    def test_activation_directory_sync_failure_restores_previous_files(self):
        self.restored(self.invoke(point="active_directory_sync",fault="sync_fail"))

    def test_deadline_is_rechecked_after_health_probe_before_confirmation(self):
        token=self.pending()
        self.restored(self.invoke("confirm",token=token,fault="deadline_during_probe"))

    def test_missing_second_backup_does_not_partially_restore_first_package(self):
        self.pending();before=self.active()
        (self.root/"previous.firewall").unlink()
        r=self.invoke("recover")
        self.assertEqual(r["error"],"unsafe_transaction_file")
        self.assertEqual(before,self.active());self.assertEqual(self.phase(),"pending")

    def test_confirmation_timeout_bounds_are_explicitly_validated(self):
        for ttl in (0,-1,301):
            with self.subTest(ttl=ttl):
                r=self.invoke(ttl=ttl)
                self.assertEqual(r["error"],"transaction_request_invalid")
                self.assertEqual(self.active(),self.original)
                self.assertFalse((self.root/"transaction.state").exists())

    def test_receipts_never_include_package_contents_addresses_or_backup_hashes(self):
        token=self.pending();r=self.invoke("confirm",token=token)
        text=json.dumps(r)
        for value in (reference.IP,reference.MAC,"resolver.example.invalid",
                      hashlib.sha256(self.original["network"]).hexdigest(),"aott_c014_"+self.suffix):
            self.assertNotIn(value,text)


if __name__=="__main__":unittest.main()
