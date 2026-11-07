"""Journaled native setter + UCI recovery on generated redundant image files.
No physical devices, live cache files, bank variables or production transports.
"""
import copy
import json
import os
from pathlib import Path
import resource
import select
import subprocess
import time
import unittest

import test_c014_native_lua_transition as portable
import test_c014_native_management_reader as reader_fixture
import test_c014_startup_state_transaction as source_fixture
import test_c014_apply_recovery as transaction

ROOT=Path(__file__).resolve().parents[1]
GUARD=ROOT/'prototypes/configuration/8311/native_environment_guard.lua'


class NativeWriteScopeTests(unittest.TestCase):
    def lua(self,body):
        code='package.path=arg[1].."/prototypes/configuration/?.lua;"..package.path\nlocal m=require "8311.native_environment_guard"\n'
        result=subprocess.run(['lua5.1','-',str(ROOT)],input=code+body+'\nprint("NATIVE_WRITE_SCOPE_PASS")\n',capture_output=True,text=True,timeout=8)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertIn('NATIVE_WRITE_SCOPE_PASS',result.stdout)

    def test_syntax_and_no_installed_or_unrestricted_writer(self):
        result=subprocess.run(['luac5.1','-p',str(GUARD)],capture_output=True,text=True,timeout=8)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertFalse((ROOT/'overlay/usr/lib/lua/8311'/GUARD.name).exists())
        self.assertNotIn(GUARD.name,(ROOT/'MANIFEST.json').read_text())
        for text in ('fw_setenv','fwenv_set','/dev/mtd','os.execute','io.popen'):
            self.assertNotIn(text,GUARD.read_text())

    def test_production_modes_paths_and_forged_backends_refused(self):
        self.lua('''for _,root in ipairs({"/etc/config","/ptconf","/var/tmp/aott-c014-txn-test-x"})do
local r,e=m.bind_fixture(root,{},"offline_synthetic");assert(r==nil and e=="native_environment_mode_refused")end
local root="/var/tmp/aott-c014-txn-test-0123456789abcdef"
local r,e=m.bind_fixture(root,{},"production");assert(r==nil and e=="native_environment_mode_refused")
r,e=m.bind_fixture(root,{},"offline_synthetic");assert(r==nil and e=="native_environment_transport_refused")
''')

    def test_only_vlan_changes_supported_and_empty_restoration_refused(self):
        before={key:{'state':'value','value':value}for key,value in source_values().items()}
        self.lua('local before='+portable.lua(before)+'''
local after={};for k,v in pairs(before)do after[k]={state=v.state,value=v.value}end
after.lct_vlan={state="value",value="123"}
assert(m.plan(before,after,"offline_synthetic"))
before.lct_vlan={state="value",value=""}
local r,e=m.plan(before,after,"offline_synthetic");assert(r==nil and e=="native_environment_empty_restore_unsupported")
before.lct_vlan={state="unset"};assert(m.plan(before,after,"offline_synthetic"))
after.gateway={state="unset"}
r,e=m.plan(before,after,"offline_synthetic");assert(r==nil and e=="native_environment_write_scope_refused")
''')

    def test_unchanged_empty_value_is_preserved_without_setter_use(self):
        before={key:{'state':'value','value':value}for key,value in source_values().items()}
        before['gateway']['value']='';before['lct_vlan']['value']=''
        self.lua('local before='+portable.lua(before)+'''
local r=assert(m.plan(before,before,"offline_synthetic"));assert(not r.changed and r.field_count==0)
assert(not r.production_write_allowed)
''')

    def test_noncanonical_vlan_injection_and_extra_keys_refused(self):
        before={key:{'state':'value','value':value}for key,value in source_values().items()}
        self.lua('local before='+portable.lua(before)+'''
for _,v in ipairs({"01","4095","-1","123;touch /tmp/x","1\\n2"})do
local after={};for k,item in pairs(before)do after[k]={state=item.state,value=item.value}end
after.lct_vlan={state="value",value=v}
local r,e=m.plan(before,after,"offline_synthetic");assert(r==nil)
end
before.boot_part={state="value",value="1"};assert(m.plan(before,before,"offline_synthetic")==nil)
''')


def source_values():
    return {'ipaddr':'192.0.2.10','netmask':'255.255.255.0','gateway':'192.0.2.10',
            'dns_server':'192.0.2.20','lct_mac':transaction.reference.MAC,'lct_vlan':'0'}


class JournaledNativeWriteTests(unittest.TestCase):
    def setUp(self):
        self.base=source_fixture.NativeStartupTransactionTests();self.base.setUp()
        self.case=self.base.case;self.root=self.base.root;self.envdir=self.root/'native-env'
        self.envdir.mkdir(mode=0o700);(self.envdir/'locks').mkdir(mode=0o700)
        self.values={'8311_'+key:item['value']for key,item in self.base.environment.items()
                     if key!='factory_mac'and item['state']=='value'}
        self.values['unrelated_fixture']='PRESERVE_EXACTLY'
        self.config=self.envdir/'fw_env.config'
        self.config.write_text('a 0x0 0x4000 0x4000 1\nb 0x0 0x4000 0x4000 1\n');self.config.chmod(0o600)
        marker=self.root/'native.environment';marker.write_bytes(b'AOTT-NATIVE-ENV-FIXTURE-1\n');marker.chmod(0o600)
        self.images(self.values);self.original_values=self.read_all()

    def tearDown(self):self.base.tearDown()

    def images(self,values):
        for name,flag in (('a',1),('b',0)):
            p=self.envdir/name;p.write_bytes(reader_fixture.image(values,flag));p.chmod(0o600)

    def read_all(self):
        def no_core():resource.setrlimit(resource.RLIMIT_CORE,(0,0))
        result=subprocess.run(['qemu-mips-static','-L',str(transaction.VENDOR),str(transaction.VENDOR/'usr/sbin/fw_printenv'),
                               '-c',str(self.config),'-l','locks'],cwd=self.envdir,capture_output=True,text=True,timeout=8,preexec_fn=no_core)
        self.assertEqual(result.returncode,0,result.stderr);self.assertEqual(result.stderr,'')
        return dict(row.split('=',1)for row in result.stdout.splitlines())

    def calls(self):
        path=self.envdir/'calls.log'
        return path.read_text().splitlines()if path.exists()else[]

    def begin(self,**kw):
        result=self.case.invoke(**kw)
        self.assertEqual(result['status'],'SOURCE_TXN_PENDING_CONFIRMATION',result)
        self.assertTrue(result['native_environment_coordinated'])
        self.assertEqual((self.root/'transaction.state').read_text().splitlines()[0],'AOTT-C014-TXN-3')
        return result['transaction_id']

    def restore(self,result):
        self.base.restored(result)
        self.assertEqual(self.read_all(),self.original_values)

    def test_native_apply_confirm_and_recovered_boot_agreement(self):
        ident=self.begin()
        self.assertEqual(self.read_all(),{**self.original_values,'8311_lct_vlan':'123'})
        self.assertEqual(self.calls(),['apply:1','apply:2'])
        self.assertEqual(self.case.invoke('confirm',token=ident)['status'],'SOURCE_TXN_CONFIRMED')
        self.assertEqual(self.base.boot()['status'],'SOURCE_BOOT_RECONCILIATION_CHECKED')
        self.assertEqual(self.read_all(),{**self.original_values,'8311_lct_vlan':'123'})
        self.assertEqual(self.calls(),['apply:1','apply:2'])

    def test_restore_coordinates_actual_native_value_and_all_four_records(self):
        self.begin();self.restore(self.case.invoke('recover'))
        self.assertEqual(self.calls(),['apply:1','apply:2','restore:1','restore:2'])
        self.restore(self.case.invoke('recover'))
        self.assertEqual(len(self.calls()),4)

    def test_absent_override_is_restored_as_missing_not_empty(self):
        self.base.environment['lct_vlan']={'state':'unset'}
        raw=source_fixture.encode('ENV',self.base.environment);self.base.original['environment']=raw
        for directory in ('source','active'):(self.root/directory/self.base.names['environment']).write_bytes(raw)
        self.values.pop('8311_lct_vlan');self.images(self.values);self.original_values=self.read_all()
        self.begin();self.restore(self.case.invoke('recover'))
        self.assertNotIn('8311_lct_vlan',self.read_all())

    def test_empty_touched_override_refused_before_backups_or_native_writes(self):
        self.base.environment['lct_vlan']={'state':'value','value':''}
        raw=source_fixture.encode('ENV',self.base.environment);self.base.original['environment']=raw
        for directory in ('source','active'):(self.root/directory/self.base.names['environment']).write_bytes(raw)
        self.values['8311_lct_vlan']='';self.images(self.values);self.original_values=self.read_all()
        result=self.case.invoke()
        self.assertEqual(result['error'],'native_environment_empty_restore_unsupported')
        self.assertEqual(result['native_stage_operations'],0);self.assertEqual(self.calls(),[])
        self.assertFalse((self.root/'previous.network').exists())
        self.assertFalse((self.root/'transaction.state').exists());self.assertEqual(self.read_all(),self.original_values)

    def test_noop_does_not_write_native_environment(self):
        self.begin(fault='vlan_unchanged');self.assertEqual(self.calls(),[])
        self.restore(self.case.invoke('recover'));self.assertEqual(self.calls(),[])

    def test_first_native_write_crash_recovers_in_separate_process(self):
        self.case.invoke(fault='native_crash_after_first',exit_code=87)
        self.assertEqual(self.base.active(),self.base.original)
        self.assertEqual(self.read_all(),{**self.original_values,'8311_lct_vlan':'123'})
        self.restore(self.case.invoke('recover'))
        self.assertEqual(self.calls(),['apply:1','restore:1','restore:2'])

    def test_second_native_call_failure_restores_without_accepting_partial_update(self):
        result=self.case.invoke(fault='native_second_write_fail');self.restore(result)
        self.assertFalse(result['apply_accepted'])
        self.assertEqual(self.calls(),['apply:1','apply:2','restore:1','restore:2'])

    def test_error_return_after_native_change_still_recovers(self):
        result=self.case.invoke(fault='native_error_after_write');self.restore(result)
        self.assertFalse(result['apply_accepted'])

    def test_false_success_without_write_is_detected(self):
        result=self.case.invoke(fault='native_silent_noop');self.restore(result)
        self.assertFalse(result['apply_accepted']);self.assertEqual(self.calls(),['apply:1','restore:1','restore:2'])

    def test_uci_activation_failure_restores_native_environment_too(self):
        result=self.case.invoke(fault='activation_failed');self.restore(result)
        self.assertFalse(result['apply_accepted'])

    def test_crash_during_native_restore_resumes_both_updates(self):
        self.begin();self.case.invoke('recover',fault='native_crash_during_restore',exit_code=87)
        self.assertEqual(self.case.phase(),'rolling_back')
        self.restore(self.case.invoke('recover'))
        self.assertEqual(self.calls(),['apply:1','apply:2','restore:1','restore:1','restore:2'])

    def test_external_change_refuses_restore_before_overwriting_any_artifact(self):
        self.begin();self.base.stop();active=self.base.active()
        alien=self.read_all();alien['8311_gateway']='198.51.100.10';self.images(alien)
        result=self.case.invoke('recover')
        self.assertEqual(result['error'],'native_environment_external_change')
        self.assertEqual(self.base.active(),active);self.assertEqual(self.read_all(),alien)
        self.assertEqual(self.calls(),['apply:1','apply:2'])

    def test_stale_native_source_cannot_stage_or_apply(self):
        self.values['8311_lct_vlan']='321';self.images(self.values)
        result=self.case.invoke()
        self.assertEqual(result['error'],'native_environment_external_change')
        self.assertEqual(result['native_stage_operations'],0);self.assertEqual(self.calls(),[])
        self.assertFalse((self.root/'transaction.state').exists())

    def test_missing_native_binding_or_marker_cannot_downgrade_journal(self):
        self.begin();self.base.stop();active=self.base.active();native=self.read_all()
        result=self.case.invoke('recover',fault='native_missing_binding')
        self.assertEqual(result['error'],'native_environment_backend_missing')
        (self.root/'native.environment').unlink()
        result=self.case.invoke('recover')
        self.assertEqual(result['error'],'transaction_native_scope_changed')
        self.assertEqual(self.base.active(),active);self.assertEqual(self.read_all(),native)

    def test_native_candidate_reverted_during_uci_activation_cannot_return_pending(self):
        caller=self.case.pause('begin','activate_firewall')
        self.assertEqual(self.read_all()['8311_lct_vlan'],'123')
        self.images(self.original_values)
        result=self.case.finish(caller)
        self.restore(result);self.assertFalse(result['apply_accepted'])

    def test_confirmation_requires_actual_native_candidate(self):
        ident=self.begin();self.images(self.original_values)
        result=self.case.invoke('confirm',token=ident)
        self.assertEqual(result['error'],'transaction_native_not_fully_applied')
        self.assertEqual(self.case.phase(),'pending');self.restore(self.case.invoke('recover'))

    def test_expired_confirmation_restores_native_and_file_state(self):
        ident=self.begin();self.restore(self.case.invoke('confirm',token=ident,fault='clock_at_deadline'))

    def test_worker_loss_between_native_calls_triggers_restoration(self):
        caller=subprocess.Popen(self.case.command('begin',fault='native_pause_after_first'),cwd=ROOT,
            stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
        self.case.children.append(caller)
        self.assertTrue(select.select([caller.stdout],[],[],15)[0])
        self.assertEqual(caller.stdout.readline().strip(),'AOTT_NATIVE_ENV_BARRIER:apply_one')
        self.base.stop()
        out,err=caller.communicate('continue\n',timeout=15);self.assertEqual(caller.returncode,0,err)
        result=json.loads(out.strip().splitlines()[-1]);self.restore(result)
        self.assertFalse(result['apply_accepted'])

    def test_supervisor_recovers_native_write_after_apply_process_dies(self):
        self.case.ensure_recovery_worker=lambda root:None
        supervisor=subprocess.Popen(self.case.command('supervisor',ttl=45),cwd=ROOT,stdin=subprocess.DEVNULL,
                                    stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
        self.case.children.append(supervisor);deadline=time.monotonic()+10
        while not(self.root/'recovery.ready').exists()and time.monotonic()<deadline:
            self.assertIsNone(supervisor.poll());time.sleep(.05)
        self.assertTrue((self.root/'recovery.ready').exists())
        self.case.invoke(ttl=3,fault='native_crash_after_first',exit_code=87)
        out,err=supervisor.communicate(timeout=15);self.assertEqual(supervisor.returncode,0,err)
        result=json.loads(out.strip().splitlines()[-1])
        self.assertEqual(result['status'],'SOURCE_SUPERVISOR_COMPLETE');self.assertEqual(result['recovery'],'rolled_back')
        self.assertEqual(self.base.active(),self.base.original);self.assertEqual(self.read_all(),self.original_values)


if __name__=='__main__':unittest.main()
