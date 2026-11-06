"""Real flock compatibility across native apply, confirmation and recovery.
Only disposable file-backed environment fixtures, never the live ONU.
"""
import json
import os
from pathlib import Path
import select
import subprocess
import time
import unittest
import test_c014_guarded_native_environment as native
import test_c014_apply_recovery as transaction
import test_c014_native_lua_transition as portable
ROOT=Path(__file__).resolve().parents[1]
MODULE=ROOT/'prototypes/configuration/8311/environment_lease.lua'

class LeaseScopeTests(unittest.TestCase):
    def lua(self,body):
        source='package.path=arg[1].."/prototypes/configuration/?.lua;"..package.path\n'+body+'\nprint("LEASE_SCOPE_PASS")\n'
        r=subprocess.run(['lua5.1','-',str(ROOT)],input=source,capture_output=True,text=True,timeout=8)
        self.assertEqual(r.returncode,0,r.stderr);self.assertIn('LEASE_SCOPE_PASS',r.stdout)

    def test_syntax_and_no_production_path_or_installation(self):
        r=subprocess.run(['luac5.1','-p',str(MODULE)],capture_output=True,text=True,timeout=8)
        self.assertEqual(r.returncode,0,r.stderr)
        self.assertNotIn(MODULE.name,(ROOT/'MANIFEST.json').read_text())
        self.assertFalse((ROOT/'overlay/usr/lib/lua/8311'/MODULE.name).exists())
        for banned in ('os.execute','io.popen','/dev/mtd','/tmp/8311-environment.lock'):
            self.assertNotIn(banned,MODULE.read_text())

    def test_scope_and_forged_handles_rejected_before_io(self):
        self.lua('local l=require "8311.environment_lease"; for _,p in ipairs({"/tmp/8311-environment.lock","/ptconf","/etc/config","/var/tmp/aott-c014-txn-test-x"})do local h,e=l.acquire(p,"offline_synthetic");assert(h==nil and e=="environment_lease_scope_refused")end; local p="/var/tmp/aott-c014-txn-test-0123456789abcdef";local h,e=l.acquire(p,"production");assert(h==nil and e=="environment_lease_scope_refused");h,e=l.verify({});assert(h==nil and e=="invalid_environment_lease");h,e=l.close({});assert(h==nil and e=="invalid_environment_lease");h,e=l.require_owned(p,"offline_synthetic");assert(h==nil and e=="environment_lease_required")')

    def test_native_mutation_api_cannot_be_called_without_lease(self):
        records={k:{'state':'value','value':v}for k,v in native.source_values().items()}
        body='local before='+portable.lua(records)+';local g=require "8311.native_environment_guard";local p="/var/tmp/aott-c014-txn-test-0123456789abcdef";assert(g.bind_fixture(p,{root=p,disposable_fixture=true,validate=function()return true end,read=function()error("READ_MUST_NOT_RUN")end,set_vlan=function()error("WRITE_MUST_NOT_RUN")end},"offline_synthetic"));local a={};for k,v in pairs(before)do a[k]={state=v.state,value=v.value}end;a.lct_vlan.value="123";local h,e=g.change(p,before,a,"apply",function()return true end,"offline_synthetic");assert(h==nil and e=="environment_lease_required")'
        self.lua(body)

class NativeCooperativeLeaseTests(unittest.TestCase):
    def setUp(self):
        self.native=native.JournaledNativeWriteTests();self.native.setUp()
        self.case=self.native.case;self.base=self.native.base;self.root=self.native.root
        self.path=self.root/'native-env/8311-environment.lock'
    def tearDown(self):self.native.tearDown()
    def probe(self):
        r=subprocess.run(['/usr/bin/flock','-n',str(self.path),'/bin/true'],capture_output=True,text=True,timeout=4)
        self.assertEqual(r.stdout+r.stderr,'');return r.returncode
    def paused(self,action,expected,**kw):
        p=subprocess.Popen(self.case.command(action,**kw),cwd=ROOT,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
        self.case.children.append(p)
        self.assertTrue(select.select([p.stdout],[],[],15)[0],'No native barrier')
        self.assertEqual(p.stdout.readline().strip(),expected);return p
    def finish(self,p):
        out,err=p.communicate('continue\n',timeout=20)
        self.assertEqual(p.returncode,0,err);return json.loads(out.strip().splitlines()[-1])
    def shell_holder(self):
        text=(transaction.VENDOR/'lib/8311-env-lock.sh').read_text()
        self.assertEqual(text.count('/tmp/8311-environment.lock'),1)
        text=text.replace('/tmp/8311-environment.lock',str(self.path))
        text+='\nlock_environment || exit $?\necho AOTT_LEGACY_ENV_LOCK_READY\nread action\n[ "$action" = release ] || exit 9\nunlock_environment\n'
        script=self.root/'legacy-lock-helper.sh';script.write_text(text);script.chmod(0o600)
        p=subprocess.Popen(['qemu-mips-static','-L',str(transaction.VENDOR),str(transaction.VENDOR/'bin/busybox'),'sh',str(script)],cwd=ROOT,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
        self.case.children.append(p)
        self.assertTrue(select.select([p.stdout],[],[],10)[0]);self.assertEqual(p.stdout.readline().strip(),'AOTT_LEGACY_ENV_LOCK_READY');return p
    def release_shell(self,p):
        out,err=p.communicate('release\n',timeout=10);self.assertEqual((p.returncode,out,err),(0,'',''))

    def test_lease_blocks_real_flock_and_keeps_stable_inode_after_release(self):
        p=self.paused('lease_hold','AOTT_ENVIRONMENT_LEASE_READY');inode=self.path.stat().st_ino
        self.assertEqual(self.probe(),1)
        self.assertEqual(self.finish(p)['status'],'SOURCE_ENVIRONMENT_LEASE_RELEASED')
        self.assertEqual(self.probe(),0);self.assertEqual(self.path.stat().st_ino,inode)

    def test_native_transaction_refuses_while_actual_legacy_wrapper_owns_lock(self):
        holder=self.shell_holder();before=self.native.read_all();r=self.case.invoke()
        self.assertEqual(r['error'],'environment_lease_busy');self.assertEqual(r['native_stage_operations'],0)
        self.assertEqual(self.native.calls(),[]);self.assertFalse((self.root/'previous.network').exists())
        self.assertFalse((self.root/'transaction.state').exists());self.assertEqual(self.native.read_all(),before)
        self.release_shell(holder);self.native.begin();self.native.restore(self.case.invoke('recover'))

    def test_legacy_wrapper_waits_for_native_owner_then_acquires_same_inode(self):
        owner=self.paused('lease_hold','AOTT_ENVIRONMENT_LEASE_READY')
        helper=(transaction.VENDOR/'lib/8311-env-lock.sh').read_text().replace('/tmp/8311-environment.lock',str(self.path))
        script=self.root/'waiting-wrapper.sh';script.write_text(helper+'\nlock_environment || exit $?\necho ACQUIRED_AFTER_RELEASE\nunlock_environment\n');script.chmod(0o600)
        waiter=subprocess.Popen(['qemu-mips-static','-L',str(transaction.VENDOR),str(transaction.VENDOR/'bin/busybox'),'sh',str(script)],cwd=ROOT,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
        self.case.children.append(waiter)
        self.assertFalse(select.select([waiter.stdout],[],[],.25)[0])
        self.assertIsNone(waiter.poll());self.assertEqual(self.probe(),1);self.finish(owner)
        out,err=waiter.communicate(timeout=5);self.assertEqual((waiter.returncode,out.strip(),err),(0,'ACQUIRED_AFTER_RELEASE',''))

    def test_nested_and_forked_close_cannot_release_parent_lease(self):
        for fault in ('nested_lease','fork_lease_close'):
            with self.subTest(fault=fault):
                owner=self.paused('lease_hold','AOTT_ENVIRONMENT_LEASE_READY',fault=fault)
                self.assertEqual(self.probe(),1)
                self.assertEqual(self.finish(owner)['status'],'SOURCE_ENVIRONMENT_LEASE_RELEASED');self.assertEqual(self.probe(),0)

    def test_killed_holder_releases_kernel_lock_without_removing_file(self):
        owner=self.paused('lease_hold','AOTT_ENVIRONMENT_LEASE_READY');inode=self.path.stat().st_ino
        self.assertEqual(self.probe(),1);owner.kill();owner.communicate(timeout=5)
        deadline=time.monotonic()+5
        while self.probe()==1 and time.monotonic()<deadline:time.sleep(.05)
        self.assertEqual(self.probe(),0);self.assertEqual(self.path.stat().st_ino,inode)
        self.assertEqual(self.case.invoke('preview')['status'],'SOURCE_TXN_PREVIEW')

    def test_two_native_writes_and_configuration_replacements_share_one_lease(self):
        caller=self.paused('begin','AOTT_NATIVE_ENV_BARRIER:apply_one',fault='native_pause_after_first')
        self.assertEqual(self.native.calls(),['apply:1']);self.assertEqual(self.probe(),1)
        result=self.finish(caller);self.assertEqual(result['status'],'SOURCE_TXN_PENDING_CONFIRMATION')
        self.assertEqual(self.native.calls(),['apply:1','apply:2']);self.assertEqual(self.probe(),0)
        self.native.restore(self.case.invoke('recover'))

    def test_lease_remains_held_through_final_uci_replacement(self):
        caller=self.paused('begin','AOTT_TRANSACTION_BARRIER:activate_firewall',point='activate_firewall',fault='pause')
        self.assertEqual(self.native.calls(),['apply:1','apply:2']);self.assertEqual(self.probe(),1)
        self.assertEqual(self.finish(caller)['status'],'SOURCE_TXN_PENDING_CONFIRMATION')
        self.assertEqual(self.probe(),0);self.native.restore(self.case.invoke('recover'))

    def test_rollback_keeps_lease_until_native_and_file_state_restored(self):
        self.native.begin();self.base.stop()
        caller=self.paused('recover','AOTT_NATIVE_ENV_BARRIER:restore_one',fault='native_pause_during_restore')
        self.assertEqual(self.case.phase(),'rolling_back');self.assertEqual(self.probe(),1)
        self.native.restore(self.finish(caller));self.assertEqual(self.probe(),0)

    def test_confirmation_keeps_lease_through_terminal_journal_write(self):
        ident=self.native.begin()
        caller=self.paused('confirm','AOTT_TRANSACTION_BARRIER:journal_confirmed',point='journal_confirmed',fault='pause',token=ident)
        self.assertEqual(self.probe(),1)
        self.assertEqual(self.finish(caller)['status'],'SOURCE_TXN_CONFIRMED');self.assertEqual(self.probe(),0)

    def test_busy_manual_recovery_preserves_every_artifact_then_resumes(self):
        self.native.begin();self.base.stop();native_before=self.native.read_all();files_before=self.base.active()
        journal=(self.root/'transaction.state').read_bytes();holder=self.shell_holder();r=self.case.invoke('recover')
        self.assertEqual(r['error'],'environment_lease_busy')
        self.assertEqual(self.native.read_all(),native_before);self.assertEqual(self.base.active(),files_before)
        self.assertEqual((self.root/'transaction.state').read_bytes(),journal)
        self.release_shell(holder);self.native.restore(self.case.invoke('recover'))

    def test_supervisor_waits_for_busy_environment_without_worker_restart(self):
        self.case.ensure_recovery_worker=lambda root:None
        supervisor=subprocess.Popen(self.case.command('supervisor',ttl=45),cwd=ROOT,stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
        self.case.children.append(supervisor);deadline=time.monotonic()+10
        while not (self.root/'recovery.ready').exists()and time.monotonic()<deadline:
            self.assertIsNone(supervisor.poll());time.sleep(.05)
        self.assertTrue((self.root/'recovery.ready').exists())
        self.native.begin(ttl=4);epoch=(self.root/'recovery.ready').read_text().splitlines()[1]
        holder=self.shell_holder();time.sleep(4.5)
        self.assertIsNone(supervisor.poll());self.assertEqual(self.case.phase(),'pending')
        self.assertEqual((self.root/'recovery.ready').read_text().splitlines()[1],epoch)
        self.release_shell(holder);out,err=supervisor.communicate(timeout=15)
        self.assertEqual(supervisor.returncode,0,err);result=json.loads(out.strip().splitlines()[-1])
        self.assertEqual(result['status'],'SOURCE_SUPERVISOR_COMPLETE');self.assertEqual(result['recovery'],'rolled_back')
        self.assertEqual(self.base.active(),self.base.original);self.assertEqual(self.native.read_all(),self.native.original_values)

    def test_unsafe_lock_inodes_never_authorize_a_native_write(self):
        sentinel=self.root/'untouched-lock-sentinel';sentinel.write_bytes(b'');sentinel.chmod(0o600)
        for kind in ('symlink','hardlink','fifo','mode','nonempty'):
            with self.subTest(kind=kind):
                if kind=='symlink':self.path.symlink_to(sentinel)
                elif kind=='hardlink':os.link(sentinel,self.path)
                elif kind=='fifo':os.mkfifo(self.path,0o600)
                else:self.path.write_bytes(b'x'if kind=='nonempty'else b'');self.path.chmod(0o644 if kind=='mode'else 0o600)
                result=self.case.invoke('preview');self.assertEqual(result['error'],'environment_lease_unsafe_file')
                self.assertEqual(self.native.calls(),[]);self.assertEqual(sentinel.read_bytes(),b'');self.path.unlink()

    def test_replaced_lock_inode_stops_transaction_without_blind_rollback(self):
        caller=self.paused('begin','AOTT_TRANSACTION_BARRIER:activate_network',point='activate_network',fault='pause')
        old=self.root/'native-env/original-cooperative.lock';self.path.rename(old)
        self.path.write_bytes(b'');self.path.chmod(0o600)
        state=self.base.active();result=self.finish(caller)
        self.assertEqual(result['error'],'environment_lease_inode_changed');self.assertEqual(self.base.active(),state)
        self.path.unlink();old.rename(self.path);self.native.restore(self.case.invoke('recover'))

    def test_error_and_crash_release_lease_for_separate_recovery_process(self):
        self.case.invoke(fault='native_crash_after_first',exit_code=87)
        self.assertEqual(self.probe(),0);self.native.restore(self.case.invoke('recover'));self.assertEqual(self.probe(),0)

    def test_human_confirmation_interval_is_not_claimed_as_continuously_locked(self):
        ident=self.native.begin();self.assertEqual(self.probe(),0)
        alien=self.native.read_all();alien['8311_gateway']='198.51.100.10';self.native.images(alien)
        result=self.case.invoke('confirm',token=ident)
        self.assertEqual(result['error'],'native_environment_external_change')
        self.assertEqual(self.native.read_all(),alien);self.assertEqual(self.native.calls(),['apply:1','apply:2'])

if __name__=='__main__':unittest.main()
