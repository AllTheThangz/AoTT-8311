"""Independent native recovery-worker admission and loss-of-worker coverage.
No production path or configuration is used; all active files are synthetic.
"""
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import select
import shutil
import signal
import subprocess
import unittest

import test_c014_apply_recovery as transaction

ROOT=Path(__file__).resolve().parents[1]
MODULE=ROOT/"prototypes/configuration/8311/recovery_admission.lua"


class AdmissionSourceTests(unittest.TestCase):
    def test_lua51_syntax_and_not_installed(self):
        result=subprocess.run(["luac5.1","-p",str(MODULE)],capture_output=True,text=True,timeout=8)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertNotIn("recovery_admission.lua",(ROOT/"MANIFEST.json").read_text())
        self.assertFalse((ROOT/"overlay/usr/lib/lua/8311/recovery_admission.lua").exists())

    def test_production_modes_paths_and_forged_proofs_refused(self):
        source='''package.path=arg[1].."/prototypes/configuration/?.lua;"..package.path
local m=require "8311.recovery_admission"
for _,path in ipairs({"/etc/config","/run/aott","/var/tmp/aott-c014-txn-test-a"}) do
 local h,e=m.present(path,"offline_synthetic")
 assert(h==nil and e=="recovery_directory_not_authorized")
end
local path="/var/tmp/aott-c014-txn-test-0123456789abcdef"
local h,e=m.acquire(path,120,"production")
assert(h==nil and e=="recovery_directory_not_authorized")
h,e=m.verify(path,{},"offline_synthetic");assert(h==nil and e=="invalid_recovery_proof")
h,e=m.close({});assert(h==nil and e=="invalid_recovery_owner")
print("RECOVERY_SCOPE_GATES_PASS")
'''
        result=subprocess.run(["lua5.1","-",str(ROOT)],input=source,capture_output=True,text=True,timeout=8)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertIn("RECOVERY_SCOPE_GATES_PASS",result.stdout)

    def test_no_network_or_service_start_and_mandatory_core_admission(self):
        source=MODULE.read_text()
        for banned in ("os.execute", "io.popen", "socket", "procd", "fwenv_set", "kill("):
            self.assertNotIn(banned,source)
        core=(ROOT/"prototypes/configuration/8311/vlan_transaction.lua").read_text()
        self.assertIn('local recovery=admission.present(root,mode)',core)
        self.assertIn('admission.arm(root,recovery,j,mode)',core)
        self.assertIn('admission.verify(root,recovery,mode)',core)
        self.assertIn('/task/\'..pid..\'/stat',source)
        self.assertIn("a.challenge~=p.challenge",source)


class NativeRecoveryAdmissionTests(unittest.TestCase):
    def setUp(self):
        self.case=transaction.NativeTransactionTests()
        self.case.setUp()
        # These tests control whether an independent worker actually exists.
        # The core itself has no bypass for a missing worker.
        self.case.ensure_recovery_worker=lambda root:None
        self.root=self.case.root
        self.workers=[]

    def tearDown(self):
        self.case.tearDown()

    def start(self,fault="none",budget=120,action="admission_watch"):
        command=self.case.command(action,ttl=budget,fault=fault)
        worker=subprocess.Popen(command,cwd=ROOT,stdin=subprocess.PIPE,stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,text=True)
        self.case.children.append(worker);self.workers.append(worker)
        self.assertTrue(select.select([worker.stdout],[],[],10)[0],"No worker readiness message")
        self.assertEqual(worker.stdout.readline().strip(),"AOTT_RECOVERY_ADMISSION_READY")
        return worker

    def stop(self,worker):
        if worker.poll() is None:worker.kill()
        worker.wait(timeout=10)

    def read_record(self,name):return (self.root/name).read_text().splitlines()
    def write_record(self,name,fields):
        path=self.root/name
        path.write_text("\n".join(fields)+"\n");path.chmod(0o600)
    def invoke(self,action="begin",**kw):return self.case.invoke(action,**kw)
    def missing(self):
        before=self.case.active();result=self.invoke()
        self.assertEqual(result["error"],"independent_recovery_worker_unavailable")
        self.assertEqual(result["native_stage_operations"],0)
        self.assertEqual(before,self.case.active())
        self.assertFalse((self.root/"transaction.state").exists())
        self.assertFalse((self.root/"previous.network").exists())
        return result
    def recover(self):self.case.restored(self.invoke("recover"))

    def test_no_worker_blocks_before_staging_and_backups(self):
        self.missing()
        self.assertFalse((self.root/"recovery.lock").exists())

    def test_dead_worker_stale_ready_file_does_not_authorize_apply(self):
        worker=self.start();ready=(self.root/"recovery.ready").read_bytes()
        self.stop(worker)
        self.missing()
        self.assertEqual((self.root/"recovery.ready").read_bytes(),ready)

    def test_live_worker_acknowledges_specific_transaction_before_apply(self):
        self.start();id=self.case.pending()
        req=self.read_record("recovery.request");ack=self.read_record("recovery.ack")
        self.assertEqual(req[1],ack[1]);self.assertEqual(req[2],id);self.assertEqual(ack[2],id)
        self.assertEqual(req[3],ack[3]);self.assertEqual(req[5],ack[5])
        self.assertEqual(len(req[5]),32)
        self.assertNotEqual(self.case.active(),self.case.original)
        self.recover()

    def test_successful_confirmation_requires_fresh_challenge(self):
        self.start();id=self.case.pending();old=self.read_record("recovery.ack")
        result=self.invoke("confirm",token=id)
        self.assertEqual(result["status"],"SOURCE_TXN_CONFIRMED")
        new=self.read_record("recovery.ack")
        self.assertEqual(old[1],new[1]);self.assertEqual(old[2],new[2])
        self.assertNotEqual(old[5],new[5])

    def test_nonresponsive_worker_never_allows_any_active_replacement(self):
        self.start(fault="freeze_before_ack")
        result=self.invoke()
        self.case.restored(result)
        self.assertFalse(result["apply_accepted"])
        self.assertFalse((self.root/"recovery.ack").exists())

    def test_previous_apply_ack_does_not_count_for_confirmation(self):
        worker=self.start(fault="freeze_after_first_ack")
        id=self.case.pending()
        self.assertTrue(select.select([worker.stdout],[],[],5)[0])
        self.assertEqual(worker.stdout.readline().strip(),"AOTT_RECOVERY_ACK_FROZEN")
        old=self.read_record("recovery.ack")
        result=self.invoke("confirm",token=id)
        self.case.restored(result);self.assertFalse(result["confirmation_accepted"])
        self.assertEqual(self.read_record("recovery.ack"),old)
        self.assertNotEqual(self.read_record("recovery.request")[5],old[5])

    def test_worker_budget_must_cover_transaction_deadline(self):
        self.start(budget=5)
        result=self.invoke(ttl=30)
        self.case.restored(result);self.assertFalse(result["apply_accepted"])
        self.assertFalse((self.root/"recovery.ack").exists())

    def test_worker_dead_before_first_activation_causes_rollback_without_apply(self):
        worker=self.start()
        caller=self.case.pause("begin","journal_pending")
        self.stop(worker)
        result=self.case.finish(caller)
        self.case.restored(result)
        self.assertFalse(result["apply_accepted"])

    def test_worker_death_between_package_writes_restores_original_pair(self):
        worker=self.start();caller=self.case.pause("begin","activate_network")
        self.assertNotEqual(self.case.active()["network"],self.case.original["network"])
        self.assertEqual(self.case.active()["firewall"],self.case.original["firewall"])
        self.stop(worker)
        result=self.case.finish(caller);self.case.restored(result)
        self.assertFalse(result["apply_accepted"])

    def test_worker_death_after_both_replacements_does_not_return_pending(self):
        worker=self.start();caller=self.case.pause("begin","activate_firewall")
        self.stop(worker)
        result=self.case.finish(caller);self.case.restored(result)
        self.assertFalse(result["apply_accepted"])

    def test_worker_loss_before_confirmation_rolls_back(self):
        worker=self.start();id=self.case.pending();self.stop(worker)
        result=self.invoke("confirm",token=id)
        self.case.restored(result);self.assertFalse(result["confirmation_accepted"])

    def test_replacement_worker_cannot_inherit_inflight_apply_proof(self):
        old=self.start();caller=self.case.pause("begin","journal_pending")
        old_epoch=self.read_record("recovery.ready")[1]
        self.stop(old);self.start()
        self.assertNotEqual(self.read_record("recovery.ready")[1],old_epoch)
        self.case.restored(self.case.finish(caller))
        self.assertFalse((self.root/"recovery.ack").exists())

    def test_replacement_worker_can_freshly_acknowledge_pending_confirmation(self):
        old=self.start();id=self.case.pending();old_epoch=self.read_record("recovery.ready")[1]
        self.stop(old);self.start()
        result=self.invoke("confirm",token=id)
        self.assertEqual(result["status"],"SOURCE_TXN_CONFIRMED")
        self.assertNotEqual(self.read_record("recovery.ack")[1],old_epoch)

    def test_worker_and_caller_crash_are_recovered_by_separate_restarted_worker(self):
        worker=self.start()
        caller=subprocess.Popen(self.case.command("begin",ttl=2,point="activate_network",fault="pause"),
            cwd=ROOT,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
        self.case.children.append(caller)
        self.assertTrue(select.select([caller.stdout],[],[],20)[0])
        self.assertEqual(caller.stdout.readline().strip(),"AOTT_TRANSACTION_BARRIER:activate_network")
        self.stop(worker);caller.kill();caller.communicate(timeout=10)
        successor=self.start()
        out,err=successor.communicate(timeout=15)
        self.assertEqual(successor.returncode,0,err)
        self.case.restored(json.loads(out.strip().splitlines()[-1]))

    def test_same_process_cannot_claim_independent_recovery_or_release_its_lock(self):
        holder=self.start(action="admission_self_hold")
        with ThreadPoolExecutor(max_workers=4) as pool:
            results=list(pool.map(lambda _:self.invoke("admission_watch"),range(8)))
        for result in results:self.assertEqual(result["error"],"recovery_worker_already_running")
        self.assertEqual(self.invoke("admission_probe")["status"],"SOURCE_INDEPENDENT_WORKER_OBSERVED")
        out,err=holder.communicate("continue\n",timeout=5)
        self.assertEqual(holder.returncode,0,err)
        self.assertTrue((self.root/"recovery.lock").exists())
        self.missing()

    def test_stopped_process_is_not_live_worker_evidence(self):
        worker=self.start();os.kill(worker.pid,signal.SIGSTOP)
        try:self.missing()
        finally:os.kill(worker.pid,signal.SIGCONT)

    def test_heartbeat_clock_and_process_incarnation_are_checked(self):
        self.start(fault="freeze_before_ack")
        original=self.read_record("recovery.ready")
        cases=("stale","future","different_boot","different_start","different_pid")
        for case in cases:
            with self.subTest(case=case):
                values=original[:]
                if case=="stale":values[5]=str(int(values[5])-5);values[7]=str(int(values[7])-5)
                elif case=="future":values[5]=str(int(values[5])+60)
                elif case=="different_boot":values[4]="00000000-0000-0000-0000-000000000000"
                elif case=="different_start":values[3]=str(int(values[3])+1)
                else:values[2]="2147483647"
                self.write_record("recovery.ready",values);self.missing()
        self.write_record("recovery.ready",original)

    def test_readiness_malformed_extra_lines_or_unsafe_permissions_rejected(self):
        self.start(fault="freeze_before_ack")
        path=self.root/"recovery.ready";original=path.read_bytes()
        for kind in ("garbage","extra","mode"):
            with self.subTest(kind=kind):
                path.write_bytes(original);path.chmod(0o600)
                if kind=="garbage":path.write_bytes(b"SYNTHETIC_PRIVATE_DO_NOT_ECHO")
                elif kind=="extra":path.write_bytes(original+b"extra\n")
                else:path.chmod(0o644)
                result=self.missing();self.assertNotIn("SYNTHETIC_PRIVATE",json.dumps(result))
        path.write_bytes(original);path.chmod(0o600)

    def test_readiness_symlink_and_hardlink_are_not_followed(self):
        self.start(fault="freeze_before_ack")
        path=self.root/"recovery.ready";data=path.read_bytes()
        sentinel=self.root/"sentinel";sentinel.write_bytes(data);sentinel.chmod(0o600)
        for kind in ("symlink","hardlink"):
            path.unlink()
            if kind=="symlink":path.symlink_to(sentinel)
            else:os.link(sentinel,path)
            self.missing();self.assertEqual(sentinel.read_bytes(),data)
        path.unlink();path.write_bytes(data);path.chmod(0o600)

    def test_replaced_lock_inode_cannot_admit_using_old_ready_file(self):
        self.start(fault="freeze_before_ack")
        path=self.root/"recovery.lock";path.rename(self.root/"old_recovery.lock")
        path.write_bytes(b"");path.chmod(0o600)
        self.missing()
        self.assertTrue((self.root/"old_recovery.lock").exists())

    def test_ack_changed_during_apply_prevents_further_changes(self):
        worker=self.start();caller=self.case.pause("begin","activate_network")
        ack=self.read_record("recovery.ack");ack[5]="0"*32
        self.write_record("recovery.ack",ack)
        self.case.restored(self.case.finish(caller))

    def test_bad_request_never_produces_ack_or_live_success(self):
        self.start(fault="freeze_before_ack")
        (self.root/"recovery.ack").write_bytes(b"SYNTHETIC_PRIVATE_BAD_ACK")
        (self.root/"recovery.ack").chmod(0o600)
        result=self.invoke()
        self.case.restored(result)
        self.assertFalse(result["apply_accepted"])
        self.assertNotIn("SYNTHETIC_PRIVATE",json.dumps(result))

    def test_metadata_contains_no_configuration_values(self):
        self.start();self.case.pending()
        for name in ("recovery.ready","recovery.request","recovery.ack"):
            raw=(self.root/name).read_text()
            self.assertLess(len(raw),1024)
            self.assertEqual((self.root/name).stat().st_mode&0o777,0o600)
            for value in (transaction.reference.IP,transaction.reference.MAC,"resolver.example.invalid"):
                self.assertNotIn(value,raw)
        self.recover()


if __name__=="__main__":unittest.main()
