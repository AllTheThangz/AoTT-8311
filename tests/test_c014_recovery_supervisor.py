"""Real vendor-MIPS supervised worker lifecycle and transaction integration.
Tests operate solely on the existing private synthetic transaction fixtures.
"""
import json
import os
from pathlib import Path
import select
import shutil
import signal
import subprocess
import time
import unittest
from unittest import mock

import test_c014_apply_recovery as transaction

ROOT=Path(__file__).resolve().parents[1]
MODULE=ROOT/"prototypes/configuration/8311/recovery_supervisor.lua"


def identity(pid):
    try:
        raw=Path('/proc',str(pid),'task',str(pid),'stat').read_text()
        fields=raw.rsplit(') ',1)[1].split()
        return fields[0],fields[19]
    except (OSError,IndexError):return None


def wait_for_process_exit(pid,expected_start,timeout):
    """One process observation per iteration; an exiting PID can disappear."""
    deadline=time.monotonic()+timeout
    while True:
        observed=identity(pid)
        if observed is None or observed[1]!=expected_start or observed[0]=='Z':
            return True
        if time.monotonic()>=deadline:
            return False
        time.sleep(0.05)


class SupervisorSourceTests(unittest.TestCase):
    def test_process_disappearance_between_polls_does_not_subscript_none(self):
        # Reproduce the previous two-read error, then check the single-read
        # helper with the same live-then-absent process sequence.
        with mock.patch(__name__+'.identity',side_effect=[('S','100'),None]):
            with self.assertRaises(TypeError):
                _=identity(123) and identity(123)[0]!='Z'
        with mock.patch(__name__+'.identity',side_effect=[('S','100'),None]) as observed, \
             mock.patch(__name__+'.time.sleep'):
            self.assertTrue(wait_for_process_exit(123,'100',2))
            self.assertEqual(observed.call_count,2)
        with mock.patch(__name__+'.identity',return_value=('S','101')):
            self.assertTrue(wait_for_process_exit(123,'100',2))

    def test_syntax_and_no_installation(self):
        if not shutil.which('luac5.1'):self.skipTest('Lua compiler missing')
        result=subprocess.run(['luac5.1','-p',str(MODULE)],capture_output=True,text=True,timeout=8)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertNotIn('recovery_supervisor.lua',(ROOT/'MANIFEST.json').read_text())
        self.assertFalse((ROOT/'overlay/usr/lib/lua/8311/recovery_supervisor.lua').exists())

    def test_production_scope_and_invalid_budget_refused_without_io(self):
        if not shutil.which('lua5.1'):self.skipTest('Lua interpreter missing')
        code='''package.path=arg[1].."/prototypes/configuration/?.lua;"..package.path
local m=require "8311.recovery_supervisor"
for _,p in ipairs({"/etc/config","/var/tmp","/var/tmp/aott-c014-txn-test-a",
 "/var/tmp/aott-c014-txn-test-0123456789abcdef/subdirectory"}) do
 local a,e=m.run(p,30,"offline_synthetic");assert(a==nil and e=="supervisor_scope_refused")
 a,e=m.request_stop(p,"offline_synthetic");assert(a==nil and e=="supervisor_scope_refused")
end
local p="/var/tmp/aott-c014-txn-test-0123456789abcdef"
local a,e=m.run(p,30,"production");assert(a==nil and e=="supervisor_scope_refused")
for _,v in ipairs({0,4,601,3.5,"30",true}) do
 a,e=m.run(p,v,"offline_synthetic");assert(a==nil and e=="supervisor_budget_invalid")
end
print("SUPERVISOR_SCOPE_PASS")
'''
        r=subprocess.run(['lua5.1','-',str(ROOT)],input=code,capture_output=True,text=True,timeout=8)
        self.assertEqual(r.returncode,0,r.stderr)
        self.assertIn('SUPERVISOR_SCOPE_PASS',r.stdout)

    def test_existing_recovery_is_used_and_restart_budget_is_bounded(self):
        source=MODULE.read_text()
        for required in ("require '8311.recovery_admission'", "require '8311.vlan_transaction'",
                         'local MAX_LAUNCHES=4', "fd:lock('tlock')", "c.n.fork()", 'gate.matches_process',
                         'tx.recover(c.root', 'if HELD[root]', 'if c.n.getppid()~=parent_id'):
            self.assertIn(required,source)
        for forbidden in ('os.execute','io.popen','procd_set_param','fwenv_set','n.exec','c.n.exec','/etc/init.d/'):
            self.assertNotIn(forbidden,source)
        self.assertNotIn('unlink',source)


class NativeSupervisedRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.case=transaction.NativeTransactionTests();self.case.setUp()
        self.case.ensure_recovery_worker=lambda root:None
        self.root=self.case.root
        self.supervisors=[];self.known_workers={}

    def tearDown(self):
        try:
            for supervisor in self.supervisors:
                if supervisor.poll() is None:
                    try:self.case.invoke('supervisor_stop')
                    except Exception:pass
                    try:supervisor.communicate(timeout=8)
                    except subprocess.TimeoutExpired:
                        supervisor.kill();supervisor.communicate(timeout=5)
            for pid,start in self.known_workers.items():
                p=identity(pid)
                if p and p[1]==start and p[0]!='Z':
                    os.kill(pid,signal.SIGKILL)
            self.case.tearDown()
        finally:pass

    def launch(self,budget=60,fault='none',ready=True):
        p=subprocess.Popen(self.case.command('supervisor',ttl=budget,fault=fault),cwd=ROOT,
            stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
        self.supervisors.append(p);self.case.children.append(p)
        if ready:self.wait_worker(p)
        return p

    def wait_worker(self,parent,previous=None,timeout=12):
        until=time.monotonic()+timeout
        while time.monotonic()<until:
            if parent.poll() is not None:
                out,err=parent.communicate(timeout=2)
                self.fail('Supervisor exited before ready: '+out+' '+err)
            try:
                lines=(self.root/'recovery.ready').read_text().splitlines()
                pid=int(lines[2]);proc=identity(pid)
                children=Path('/proc',str(parent.pid),'task',str(parent.pid),'children').read_text().split()
                if proc and proc[0] not in ('Z','T','X','t') and proc[1]==lines[3] and str(pid) in children and lines[1]!=previous:
                    self.known_workers[pid]=proc[1]
                    return pid,lines[1]
            except (OSError,IndexError,ValueError):pass
            time.sleep(0.05)
        self.fail('Supervisor did not establish an independent ready child')

    def finish(self,p,timeout=15):
        out,err=p.communicate(timeout=timeout)
        self.assertEqual(p.returncode,0,err)
        self.assertNotIn('SYNTHETIC_PRIVATE',out+err)
        return json.loads(out.strip().splitlines()[-1])

    def state(self):
        v=(self.root/'recovery.supervisor.state').read_text().splitlines()
        self.assertEqual(v[0],'AOTT-RECOVERY-SUPERVISOR-1')
        return {'boot':v[1],'started':int(v[2]),'until':int(v[3]),'launches':int(v[4]),'last':int(v[5]),'phase':v[6]}

    def assert_absent_owner(self):
        r=self.case.invoke('admission_probe')
        self.assertEqual(r['status'],'REJECTED')
        for pid,start in self.known_workers.items():
            p=identity(pid)
            self.assertTrue(not p or p[1]!=start or p[0]=='Z','Worker still running after supervision ended')

    def stopped(self,parent):
        self.assertEqual(self.case.invoke('supervisor_stop')['status'],'SOURCE_SUPERVISOR_STOP_REQUESTED')
        r=self.finish(parent)
        self.assertEqual(r['status'],'SOURCE_SUPERVISOR_STOPPED')
        self.assert_absent_owner()
        return r

    def test_started_worker_admits_transaction_and_confirmation_finishes_supervision(self):
        p=self.launch();transaction_id=self.case.pending()
        r=self.case.invoke('confirm',token=transaction_id)
        self.assertEqual(r['status'],'SOURCE_TXN_CONFIRMED')
        result=self.finish(p)
        self.assertEqual(result['status'],'SOURCE_SUPERVISOR_COMPLETE')
        self.assertEqual(result['recovery'],'confirmed')
        self.assertEqual(result['launches'],1)
        self.assert_absent_owner()

    def test_ready_child_runs_at_lower_priority(self):
        p=self.launch();pid,_=self.wait_worker(p)
        self.assertGreaterEqual(os.getpriority(os.PRIO_PROCESS,pid),10)
        inherited=[]
        for fd in Path('/proc',str(pid),'fd').iterdir():
            try:inherited.append(os.readlink(fd))
            except OSError:pass
        self.assertNotIn(str(self.root/'recovery.supervisor.lock'),inherited)
        self.stopped(p)

    def test_worker_sigkill_is_restarted_without_manual_worker_launch(self):
        p=self.launch();pid,epoch=self.wait_worker(p)
        inode=(self.root/'recovery.supervisor.lock').stat().st_ino
        os.kill(pid,signal.SIGKILL)
        replacement,new_epoch=self.wait_worker(p,previous=epoch)
        self.assertNotEqual(replacement,pid);self.assertNotEqual(new_epoch,epoch)
        self.assertEqual(self.state()['launches'],2)
        self.assertEqual((self.root/'recovery.supervisor.lock').stat().st_ino,inode)
        self.stopped(p)

    def test_stopped_worker_is_terminated_and_replaced(self):
        p=self.launch();pid,epoch=self.wait_worker(p)
        os.kill(pid,signal.SIGSTOP)
        replacement,_=self.wait_worker(p,previous=epoch)
        self.assertNotEqual(pid,replacement)
        old=identity(pid);self.assertTrue(not old or old[0]=='Z')
        self.stopped(p)

    def test_frozen_heartbeat_worker_is_not_treated_as_healthy_forever(self):
        p=self.launch(fault='worker_hang');_,epoch=self.wait_worker(p)
        self.wait_worker(p,previous=epoch,timeout=12)
        self.assertGreaterEqual(self.state()['launches'],2)
        self.stopped(p)

    def test_restart_limit_opens_after_four_failed_launches(self):
        p=self.launch(fault='worker_crash',ready=False)
        result=self.finish(p,timeout=15)
        self.assertEqual(result['status'],'SOURCE_SUPERVISOR_RESTART_LIMIT')
        self.assertEqual(result['launches'],4);self.assertEqual(result['restarts'],3)
        self.assertEqual(self.state()['phase'],'exhausted')
        self.assertEqual(self.case.active(),self.case.original)
        self.assertFalse((self.root/'transaction.state').exists())
        retry=self.launch(ready=False);r=self.finish(retry)
        self.assertEqual(r['error'],'supervisor_session_not_resumable')
        self.assertEqual(self.state()['launches'],4)

    def test_pending_transaction_survives_worker_death_then_is_restored_by_replacement(self):
        p=self.launch();pid,epoch=self.wait_worker(p)
        self.case.pending(ttl=4)
        os.kill(pid,signal.SIGKILL)
        # The new child, not the test parent, performs deadline recovery.
        result=self.finish(p,timeout=15)
        self.assertEqual(result['status'],'SOURCE_SUPERVISOR_COMPLETE')
        self.assertEqual(result['recovery'],'rolled_back')
        self.assertEqual(self.case.active(),self.case.original)
        self.assertGreaterEqual(result['launches'],2)
        self.assert_absent_owner()

    def test_caller_and_worker_death_after_first_write_are_recovered_automatically(self):
        p=self.launch();pid,_=self.wait_worker(p)
        caller=subprocess.Popen(self.case.command('begin',ttl=5,point='activate_network',fault='pause'),
            cwd=ROOT,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
        self.case.children.append(caller)
        self.assertTrue(select.select([caller.stdout],[],[],20)[0])
        self.assertEqual(caller.stdout.readline().strip(),'AOTT_TRANSACTION_BARRIER:activate_network')
        self.assertNotEqual(self.case.active()['network'],self.case.original['network'])
        caller.kill();caller.communicate(timeout=5)
        os.kill(pid,signal.SIGKILL)
        result=self.finish(p,timeout=15)
        self.assertEqual(result['recovery'],'rolled_back')
        self.assertEqual(self.case.active(),self.case.original)

    def test_stop_request_restores_pending_transaction_before_exit(self):
        p=self.launch();self.case.pending()
        result=self.stopped(p)
        self.assertEqual(result['recovery'],'rolled_back')
        self.assertEqual(self.case.active(),self.case.original)

    def test_parent_sigkill_triggers_worker_recovery_and_exit(self):
        p=self.launch();pid,_=self.wait_worker(p);self.case.pending()
        p.kill();p.communicate(timeout=5)
        until=time.monotonic()+10
        while time.monotonic()<until:
            if self.case.phase()=='rolled_back' and self.case.active()==self.case.original:
                break
            time.sleep(0.1)
        self.assertEqual(self.case.phase(),'rolled_back')
        self.assertEqual(self.case.active(),self.case.original)
        self.assertTrue(wait_for_process_exit(pid,self.known_workers[pid],3),
                        'Original worker did not exit after verified recovery')
        self.assert_absent_owner()

    def test_parent_sigterm_also_uses_parent_loss_recovery(self):
        p=self.launch();self.case.pending()
        p.terminate();p.communicate(timeout=5)
        until=time.monotonic()+10
        while self.case.phase()!='rolled_back' and time.monotonic()<until:time.sleep(0.1)
        self.assertEqual(self.case.active(),self.case.original)

    def test_parent_and_worker_crash_resume_without_resetting_launch_budget(self):
        first=self.launch();pid,_=self.wait_worker(first)
        original=self.state()
        os.kill(pid,signal.SIGSTOP)
        first.kill();first.communicate(timeout=5);os.kill(pid,signal.SIGKILL)
        second=self.launch()
        state=self.state()
        self.assertEqual(state['started'],original['started'])
        self.assertEqual(state['until'],original['until'])
        self.assertEqual(state['launches'],2)
        self.stopped(second)

    def test_second_supervisor_refused_without_touching_first_worker(self):
        first=self.launch();pid,epoch=self.wait_worker(first)
        other=self.launch(ready=False);result=self.finish(other)
        self.assertEqual(result['error'],'supervisor_already_running')
        self.assertEqual(self.wait_worker(first),(pid,epoch))
        self.stopped(first)

    def test_unrelated_existing_recovery_owner_is_not_replaced_or_killed(self):
        command=self.case.command('admission_watch',ttl=120)
        other=subprocess.Popen(command,cwd=ROOT,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
        self.case.children.append(other)
        self.assertTrue(select.select([other.stdout],[],[],10)[0])
        self.assertEqual(other.stdout.readline().strip(),'AOTT_RECOVERY_ADMISSION_READY')
        p=self.launch(ready=False);r=self.finish(p)
        self.assertEqual(r['error'],'supervisor_foreign_worker_present')
        self.assertIsNone(other.poll())
        self.assertEqual(self.state()['launches'],0)
        self.assertEqual(self.case.invoke('admission_probe')['status'],'SOURCE_INDEPENDENT_WORKER_OBSERVED')
        other.kill();other.communicate(timeout=5)

    def test_recursive_supervision_does_not_release_outer_owner(self):
        p=self.launch(fault='nested_supervisor')
        contender=self.launch(ready=False)
        self.assertEqual(self.finish(contender)['error'],'supervisor_already_running')
        self.stopped(p)

    def test_worker_budget_ends_without_unbounded_resurrection(self):
        p=self.launch(budget=5,ready=False)
        result=self.finish(p,timeout=12)
        self.assertIn(result['status'],('SOURCE_SUPERVISOR_STOPPED','SOURCE_SUPERVISOR_RESTART_LIMIT'))
        self.assertLessEqual(result['launches'],1)
        self.assertEqual(self.case.active(),self.case.original)
        self.assert_absent_owner()

    def test_stop_before_launch_never_starts_worker(self):
        self.case.invoke('supervisor_stop')
        p=self.launch(ready=False);r=self.finish(p)
        self.assertEqual(r['status'],'SOURCE_SUPERVISOR_STOPPED')
        self.assertEqual(r['launches'],0)
        self.assertFalse((self.root/'recovery.ready').exists())

    def test_completed_session_is_not_automatically_reused(self):
        p=self.launch();transaction_id=self.case.pending()
        self.case.invoke('confirm',token=transaction_id);self.finish(p)
        before=self.case.active()
        retry=self.launch(ready=False);r=self.finish(retry)
        self.assertEqual(r['error'],'supervisor_session_not_resumable')
        self.assertEqual(before,self.case.active())

    def test_unsafe_supervisor_lock_types_are_refused(self):
        path=self.root/'recovery.supervisor.lock'
        sentinel=self.root/'sentinel';sentinel.write_bytes(b'UNCHANGED');sentinel.chmod(0o600)
        for kind in ('symlink','hardlink','fifo','mode','nonempty'):
            with self.subTest(kind=kind):
                if kind=='symlink':path.symlink_to(sentinel)
                elif kind=='hardlink':os.link(sentinel,path)
                elif kind=='fifo':os.mkfifo(path,0o600)
                else:
                    path.write_bytes(b'x' if kind=='nonempty' else b'')
                    path.chmod(0o644 if kind=='mode' else 0o600)
                p=self.launch(ready=False);r=self.finish(p)
                self.assertEqual(r['error'],'unsafe_supervisor_lock')
                self.assertEqual(sentinel.read_bytes(),b'UNCHANGED')
                self.assertFalse((self.root/'recovery.ready').exists())
                path.unlink()

    def test_partial_or_corrupt_supervisor_state_is_not_reset(self):
        for name in ('recovery.supervisor.state','recovery.supervisor.state.new'):
            with self.subTest(name=name):
                path=self.root/name;path.write_bytes(b'SYNTHETIC_PRIVATE_RECORD');path.chmod(0o600)
                p=self.launch(ready=False);r=self.finish(p)
                self.assertEqual(r['status'],'REJECTED')
                self.assertEqual(path.read_bytes(),b'SYNTHETIC_PRIVATE_RECORD')
                self.assertNotIn('SYNTHETIC_PRIVATE_RECORD',json.dumps(r))
                self.assertFalse((self.root/'recovery.ready').exists())
                path.unlink()

    def test_bad_stop_record_is_not_accepted_as_request(self):
        path=self.root/'recovery.supervisor.stop';path.write_bytes(b'SYNTHETIC_PRIVATE_BAD_STOP');path.chmod(0o600)
        p=self.launch(ready=False);result=self.finish(p)
        self.assertEqual(result['error'],'supervisor_stop_invalid')
        self.assertFalse((self.root/'recovery.ready').exists())
        self.assertEqual(path.read_bytes(),b'SYNTHETIC_PRIVATE_BAD_STOP')

    def test_terminal_marker_waits_for_original_confirm_lock_to_be_released(self):
        p=self.launch();transaction_id=self.case.pending()
        confirm=subprocess.Popen(self.case.command('confirm',token=transaction_id,
            point='journal_confirmed',fault='pause'),cwd=ROOT,stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
        self.case.children.append(confirm)
        self.assertTrue(select.select([confirm.stdout],[],[],15)[0])
        self.assertEqual(confirm.stdout.readline().strip(),'AOTT_TRANSACTION_BARRIER:journal_confirmed')
        # The worker can observe the terminal marker before confirm closes its
        # transaction lock. The supervisor must wait, not restart or report failure.
        until=time.monotonic()+3
        while time.monotonic()<until:
            self.assertIsNone(p.poll(),'Supervisor rejected a legitimate lock handoff')
            self.assertEqual(self.state()['launches'],1)
            time.sleep(0.1)
        self.assertEqual(self.case.finish(confirm)['status'],'SOURCE_TXN_CONFIRMED')
        self.assertEqual(self.finish(p)['status'],'SOURCE_SUPERVISOR_COMPLETE')

    def test_parent_suspension_triggers_child_recovery_then_parent_can_finish(self):
        p=self.launch();self.case.pending()
        os.kill(p.pid,signal.SIGSTOP)
        try:
            until=time.monotonic()+10
            while self.case.phase()!='rolled_back' and time.monotonic()<until:time.sleep(0.1)
            self.assertEqual(self.case.phase(),'rolled_back')
            self.assertEqual(self.case.active(),self.case.original)
        finally:os.kill(p.pid,signal.SIGCONT)
        self.assertEqual(self.finish(p)['status'],'SOURCE_SUPERVISOR_COMPLETE')

    def test_launch_ledger_tamper_is_refused_and_pending_files_restored(self):
        p=self.launch();self.case.pending()
        record=self.root/'recovery.supervisor.state'
        altered=record.read_text().replace('\nrunning\n','\nfailed\n')
        record.write_text(altered)
        result=self.finish(p,timeout=12)
        self.assertEqual(result['error'],'supervisor_record_changed')
        self.assertEqual(record.read_text(),altered)
        self.assertEqual(self.case.active(),self.case.original)
        self.assertEqual(self.case.phase(),'rolled_back')
        self.assert_absent_owner()

    def test_process_attestation_refuses_other_pid_or_incarnation(self):
        p=self.launch();pid,_=self.wait_worker(p);start=self.known_workers[pid]
        code='''package.path=arg[1].."/prototypes/configuration/?.lua;"..arg[2].."/usr/lib/lua/?.lua;"..arg[2].."/usr/lib/lua/?/init.lua;"..package.path
package.cpath=arg[2].."/usr/lib/lua/?.so;"..package.cpath
local m=require "8311.recovery_admission"
local proof=assert(m.present(arg[3],"offline_synthetic"))
assert(m.matches_process(arg[3],proof,tonumber(arg[4]),arg[5],"offline_synthetic"))
local value,why=m.matches_process(arg[3],proof,tonumber(arg[6]),arg[5],"offline_synthetic")
assert(value==nil and why=="recovery_process_mismatch")
value,why=m.matches_process(arg[3],proof,tonumber(arg[4]),"0","offline_synthetic")
assert(value==nil and why=="recovery_process_mismatch")
assert(m.matches_process(arg[3],proof,tonumber(arg[4]),arg[5],"offline_synthetic"))
print("CHILD_PROCESS_ATTESTATION_PASS")
'''
        command=['qemu-mips-static','-L',str(transaction.VENDOR),str(transaction.VENDOR/'usr/bin/lua'),
            '-',str(ROOT),str(transaction.VENDOR),str(self.root),str(pid),start,str(p.pid)]
        result=subprocess.run(command,input=code,capture_output=True,text=True,timeout=8)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertIn('CHILD_PROCESS_ATTESTATION_PASS',result.stdout)
        self.stopped(p)

    def test_unsafe_workspace_mode_prevents_supervision(self):
        self.root.chmod(0o755)
        try:
            p=self.launch(ready=False);result=self.finish(p)
            self.assertEqual(result['error'],'unsafe_supervisor_directory')
            self.assertFalse((self.root/'recovery.ready').exists())
        finally:self.root.chmod(0o700)

    def test_metadata_and_result_do_not_include_configuration_contents(self):
        p=self.launch();r=self.stopped(p)
        state=(self.root/'recovery.supervisor.state').read_text()
        for text in (state,json.dumps(r)):
            for value in (transaction.reference.IP,transaction.reference.MAC,'resolver.example.invalid'):
                self.assertNotIn(value,text)
        self.assertLess(len(state),512)
        for name in ('recovery.supervisor.lock','recovery.supervisor.state','recovery.supervisor.stop'):
            self.assertEqual((self.root/name).stat().st_mode&0o777,0o600)


if __name__=='__main__':unittest.main()
