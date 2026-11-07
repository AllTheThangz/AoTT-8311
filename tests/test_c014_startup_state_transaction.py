"""File-backed startup settings/cache transaction, using actual vendor Lua/UCI.
The records model only six management settings; no real firmware env or cache.
"""
import copy
import hashlib
import json
import os
from pathlib import Path
import select
import shutil
import subprocess
import time
import unittest

import test_c014_apply_recovery as tx
import test_c014_native_lua_transition as lua_helper
import test_c014_storage_boot as storage
import test_c014_source_precedence as precedence

ROOT=Path(__file__).resolve().parents[1]
MODULE=ROOT/'prototypes/configuration/8311/startup_state.lua'
ENV_KEYS=('ipaddr','netmask','gateway','dns_server','lct_mac','lct_vlan','factory_mac')
CACHE_KEYS=('ipaddr','netmask','gateway','dns_server','lct_mac')


def encode(kind,records):
    keys=ENV_KEYS if kind=='ENV' else CACHE_KEYS
    rows=['AOTT-MGMT-'+kind+'-1']
    for key in keys:
        item=records[key]
        rows.append(key+' '+item['state']+(' '+item['value'].encode().hex() if item['state']=='value' else ''))
    return ('\n'.join(rows)+'\n').encode()


def decode(raw):
    rows=raw.decode().splitlines();records={}
    for row in rows[1:]:
        parts=row.split(' ',2)
        records[parts[0]]={'state':parts[1]}
        if parts[1]=='value':records[parts[0]]['value']=bytes.fromhex(parts[2]).decode()
    return records


class StartupRecordTests(unittest.TestCase):
    def run_lua(self,body):
        if not shutil.which('lua5.1'):self.skipTest('Host Lua missing')
        script='package.path=arg[1].."/prototypes/configuration/?.lua;"..package.path\nlocal s=require "8311.startup_state"\n'+body+'\nprint("STARTUP_RECORD_PASS")\n'
        r=subprocess.run(['lua5.1','-',str(ROOT)],input=script,capture_output=True,text=True,timeout=8)
        self.assertEqual(r.returncode,0,r.stderr)
        self.assertIn('STARTUP_RECORD_PASS',r.stdout)

    def test_syntax_no_live_operations_or_overlay_install(self):
        r=subprocess.run(['luac5.1','-p',str(MODULE)],capture_output=True,text=True,timeout=8)
        self.assertEqual(r.returncode,0,r.stderr)
        for name in ('io.open','io.popen','os.execute','fwenv_set','/tmp/8311','/dev/mtd','nixio'):
            self.assertNotIn(name,MODULE.read_text())
        self.assertNotIn(MODULE.name,(ROOT/'MANIFEST.json').read_text())
        self.assertFalse((ROOT/'overlay/usr/lib/lua/8311'/MODULE.name).exists())

    def test_canonical_records_preserve_absence_empty_and_value(self):
        e=precedence.evidence();env=e['environment'];env['factory_mac']=e['factory_mac']
        env['gateway']={'state':'unset'};env['dns_server']={'state':'value','value':''}
        cache=e['cache'];cache['dns_server']={'state':'value','value':''}
        eraw,craw=encode('ENV',env),encode('CACHE',cache)
        self.run_lua('local e='+lua_helper.lua(env)+'\nlocal c='+lua_helper.lua(cache)+'''
local er=assert(s.encode_environment(e));local cr=assert(s.encode_cache(c))
assert(er=='''+lua_helper.lua(eraw.decode())+''' and cr=='''+lua_helper.lua(craw.decode())+''')
local d=assert(s.evidence(er,cr,{}))
assert(d.environment.gateway.state=="unset")
assert(d.environment.dns_server.state=="value" and d.environment.dns_server.value=="")
assert(d.cache.ipaddr.state=="absent" and d.cache.dns_server.value=="")
''')

    def test_unrelated_boot_environment_keys_are_refused(self):
        e=precedence.evidence()['environment'];e['factory_mac']={'state':'absent'}
        self.run_lua('local e='+lua_helper.lua(e)+'''
e.gpon_sn={state="value",value="PRIVATE_SENTINEL"}
local raw,why=s.encode_environment(e);assert(raw==nil and why=="startup_state_scope_invalid")
e.gpon_sn=nil;e.ipaddr.extra=true
raw,why=s.encode_environment(e);assert(raw==nil and why=="startup_state_record_invalid")
''')

    def test_malformed_duplicate_noncanonical_and_oversized_records_fail_closed(self):
        e=precedence.evidence();environment=e['environment'];environment['factory_mac']=e['factory_mac']
        eraw=encode('ENV',environment).decode();craw=encode('CACHE',e['cache']).decode()
        variants=[eraw+'extra\n',eraw.replace('gateway value','ipaddr value',1),eraw[:-1],
                  eraw.replace('value ','value zz',1),eraw.replace('AOTT-MGMT-ENV-1','AOTT-MGMT-ENV-2'), 'x'*4097]
        script='local cache='+lua_helper.lua(craw)+'\n'
        for raw in variants:script+='do local d,w=s.evidence('+lua_helper.lua(raw)+',cache,{});assert(d==nil and type(w)=="string")end\n'
        self.run_lua(script)

    def test_source_plan_preserves_unrelated_settings_and_invalidates_only_managed_cache(self):
        before=precedence.evidence()
        before['cache']={key:copy.deepcopy(before['environment'][key]) for key in CACHE_KEYS}
        env=copy.deepcopy(before['environment']);env['factory_mac']=before['factory_mac']
        after=tx.reference.plan({'network':before['network'],'firewall':tx.reference.state()['firewall']},123)['after']['network']
        self.run_lua('local env='+lua_helper.lua(encode('ENV',env).decode())+'\nlocal cache='+lua_helper.lua(encode('CACHE',before['cache']).decode())+'\nlocal a='+lua_helper.lua(before['network'])+'\nlocal b='+lua_helper.lua(after)+'''
local p,w=s.plan(env,cache,a,b,"offline_synthetic");assert(p,w)
assert(p.changed_sources==1 and p.invalidated_caches==5)
local d=assert(s.evidence(p.environment,p.cache,b))
assert(d.environment.lct_vlan.value=="123")
for key,v in pairs(d.cache)do assert(v.state=="absent")end
assert(s.verify(p.environment,p.cache,b))
local q,e=s.plan(env,cache,a,a,"offline_synthetic");assert(q,e)
assert(q.environment==env and q.cache==cache and q.changed_sources==0)
q,e=s.plan(env,cache,a,b,"production");assert(q==nil and e=="startup_state_mode_refused")
''')

    def test_versioned_retention_cannot_omit_source_records(self):
        self.run_lua('''local store=require "8311.recovery_storage"
local files={}
for _,prefix in ipairs({"previous_","candidate_"})do
 for _,id in ipairs({"network","firewall","environment","cache"})do
  files[prefix..id]={sha256=string.rep("b",64),bytes=40}
 end
end
local raw=assert(store.encode(string.rep("a",16),files,"uci_and_startup_sources"))
assert(raw:find("AOTT-RETAINED-CONFIG-2",1,true)==1)
local verified=assert(store.verify(string.rep("a",16),raw,files,"uci_and_startup_sources"))
assert(verified.files==8)
assert(store.verify(string.rep("a",16),raw,files,"uci_only")==nil)
files.previous_cache=nil
assert(store.verify(string.rep("a",16),raw,files,"uci_and_startup_sources")==nil)
''')


class NativeStartupTransactionTests(unittest.TestCase):
    def setUp(self):
        self.case=tx.NativeTransactionTests();self.case.setUp()
        storage.prepare_boot_sources(self.case)
        self.root=self.case.root
        values=json.loads((self.root/'source-evidence.json').read_text())
        self.environment=copy.deepcopy(values['environment']);self.environment['factory_mac']=values['factory_mac']
        self.caches={k:copy.deepcopy(values['environment'][k]) for k in CACHE_KEYS}
        self.original={**self.case.original,'environment':encode('ENV',self.environment),'cache':encode('CACHE',self.caches)}
        self.names={p:'aott_c014_'+self.case.suffix+'_'+p for p in self.original}
        for p in ('environment','cache'):
            for directory in (self.root/'active',self.root/'source'):
                path=directory/self.names[p];path.write_bytes(self.original[p]);path.chmod(0o600)

    def tearDown(self):
        try:
            for p in ('environment','cache'):
                self.assertEqual((self.root/'source'/self.names[p]).read_bytes(),self.original[p])
        finally:self.case.tearDown()

    def active(self):return {p:(self.root/'active'/name).read_bytes() for p,name in self.names.items()}
    def invoke(self,action='begin',**kw):return self.case.invoke(action,**kw)
    def pending(self,**kw):
        r=self.invoke(**kw)
        self.assertEqual(r['status'],'SOURCE_TXN_PENDING_CONFIRMATION')
        self.assertTrue(r['startup_sources_included']);self.assertEqual(r['active_artifacts'],4)
        return r['transaction_id']
    def stop(self):
        for p in self.case.admission_workers.values():
            if p.poll() is None:p.kill();p.wait(timeout=10)
    def restored(self,result):
        self.assertEqual(result['status'],'SOURCE_TXN_ROLLED_BACK')
        self.assertEqual(self.active(),self.original)
        self.assertEqual(self.case.phase(),'rolled_back')
    def boot(self):self.stop();return self.invoke('boot_gate')

    def test_success_updates_vlan_source_and_invalidates_cache_before_confirm(self):
        token=self.pending();values=self.active()
        self.assertEqual(decode(values['environment'])['lct_vlan'],{'state':'value','value':'123'})
        for key in ENV_KEYS:
            if key!='lct_vlan':self.assertEqual(decode(values['environment'])[key],self.environment[key])
        self.assertTrue(all(v['state']=='absent' for v in decode(values['cache']).values()))
        self.assertEqual((self.root/'transaction.state').read_text().splitlines()[0],'AOTT-C014-TXN-2')
        self.assertEqual(len((self.root/'transaction.state').read_text().splitlines()),14)
        self.assertEqual(len((self.root/'retained.state').read_text().splitlines()),10)
        r=self.invoke('confirm',token=token);self.assertEqual(r['status'],'SOURCE_TXN_CONFIRMED')
        self.assertEqual(self.active(),values)

    def test_confirmed_bundle_passes_boot_source_agreement_without_manual_evidence_edit(self):
        token=self.pending();self.invoke('confirm',token=token);after=self.active()
        # The legacy JSON evidence deliberately remains untagged. The native
        # boot fixture must now read the actual transaction-managed records.
        self.assertEqual(json.loads((self.root/'source-evidence.json').read_text())['environment']['lct_vlan']['value'],'0')
        result=self.boot()
        self.assertEqual(result['status'],'SOURCE_BOOT_RECONCILIATION_CHECKED')
        self.assertTrue(result['source_precedence_verified']);self.assertEqual(self.active(),after)

    def test_rollback_restores_exact_saved_representations_and_cache_bytes(self):
        self.pending();self.restored(self.invoke('recover'));self.restored(self.invoke('recover'))
        self.assertEqual(self.boot()['status'],'SOURCE_BOOT_RECONCILIATION_CHECKED')

    def test_boot_reconciles_pending_sources_and_uci_as_one_transaction(self):
        self.pending();result=self.boot()
        self.assertEqual(result['status'],'SOURCE_BOOT_RECONCILIATION_CHECKED')
        self.assertEqual(result['phase'],'rolled_back');self.assertEqual(self.active(),self.original)

    def test_expired_confirmation_rolls_back_all_four_artifacts(self):
        token=self.pending();self.restored(self.invoke('confirm',token=token,fault='clock_at_deadline'))

    def test_failed_health_observation_restores_source_records_too(self):
        token=self.pending();self.restored(self.invoke('confirm',token=token,fault='management_failed'))

    def test_no_op_preserves_exact_environment_and_existing_cache(self):
        token=self.pending(fault='vlan_unchanged')
        self.assertEqual(self.active()['environment'],self.original['environment'])
        self.assertEqual(self.active()['cache'],self.original['cache'])
        self.assertEqual(self.invoke('confirm',token=token)['status'],'SOURCE_TXN_CONFIRMED')

    def test_explicit_source_scope_required_before_staging(self):
        for fault in ('omit_source_scope','wrong_source_scope'):
            with self.subTest(fault=fault):
                result=self.invoke(fault=fault)
                self.assertEqual(result['error'],'transaction_scope_not_confirmed')
                self.assertEqual(result['native_stage_operations'],0)
                self.assertEqual(self.active(),self.original)
                self.assertFalse((self.root/'previous.network').exists())

    def test_preview_binds_both_extra_records_and_refuses_stale_evidence(self):
        p=self.invoke('preview');self.assertEqual(p['scope'],'uci_and_startup_sources');self.assertEqual(len(p['review_revision']),256)
        data=copy.deepcopy(self.caches);data['ipaddr']={'state':'value','value':'198.51.100.10'}
        (self.root/'active'/self.names['cache']).write_bytes(encode('CACHE',data))
        r=self.invoke('preview');self.assertEqual(r['error'],'transaction_startup_source_disagreement')
        self.assertFalse((self.root/'transaction.state').exists())

    def test_missing_one_source_file_cannot_fall_back_to_uci_only(self):
        (self.root/'active'/self.names['cache']).unlink()
        r=self.invoke('preview');self.assertEqual(r['error'],'transaction_startup_scope_incomplete')
        self.assertFalse((self.root/'transaction.state').exists())

    def test_source_bundle_downgrade_after_apply_is_refused(self):
        self.pending();self.stop();before={p:raw for p,raw in self.active().items() if p in ('network','firewall')}
        for p in ('environment','cache'):(self.root/'active'/self.names[p]).unlink()
        r=self.invoke('recover');self.assertEqual(r['error'],'transaction_startup_scope_changed')
        for p,raw in before.items():self.assertEqual((self.root/'active'/self.names[p]).read_bytes(),raw)

    def test_environment_crash_before_network_activation_restores_all(self):
        self.invoke(point='activate_environment',fault='crash',exit_code=87)
        self.assertEqual(self.active()['network'],self.original['network'])
        self.assertNotEqual(self.active()['environment'],self.original['environment'])
        self.restored(self.invoke('recover'))

    def test_cache_crash_before_network_activation_restores_all(self):
        self.invoke(point='activate_cache',fault='crash',exit_code=87)
        self.assertEqual(self.active()['network'],self.original['network'])
        self.assertNotEqual(self.active()['cache'],self.original['cache'])
        self.restored(self.invoke('recover'))

    def test_network_crash_restores_uci_saved_source_and_cache(self):
        self.invoke(point='activate_network',fault='crash',exit_code=87)
        self.restored(self.invoke('recover'))

    def test_partial_source_write_is_replaced_from_verified_backup(self):
        self.invoke(point='activate_cache',fault='partial_scratch_crash',exit_code=87)
        self.restored(self.invoke('recover'))
        self.assertNotIn(b'partial_synthetic',b''.join(self.active().values()))

    def test_environment_replace_failure_never_leaves_new_uci(self):
        self.restored(self.invoke(point='activate_environment',fault='replace_fail'))

    def test_cache_replace_failure_restores_previous_environment(self):
        self.restored(self.invoke(point='activate_cache',fault='replace_fail'))

    def test_rollback_crash_after_source_restore_resumes_without_caller_adapter(self):
        self.pending();self.invoke('recover',point='restore_environment',fault='crash',exit_code=87)
        self.assertEqual(self.case.phase(),'rolling_back')
        self.restored(self.invoke('recover'))

    def test_corrupt_source_backup_prevents_even_first_uci_restore(self):
        self.pending();self.stop();after=self.active()
        (self.root/'previous.cache').write_bytes(b'PRIVATE_BAD_BACKUP')
        r=self.invoke('recover');self.assertEqual(r['error'],'transaction_backup_mismatch');self.assertEqual(self.active(),after)

    def test_unknown_current_cache_change_is_not_blindly_overwritten(self):
        self.pending();self.stop()
        (self.root/'active'/self.names['cache']).write_bytes(b'PRIVATE_OTHER_WRITER')
        after=self.active();r=self.invoke('recover')
        self.assertEqual(r['error'],'transaction_unknown_active_content');self.assertEqual(self.active(),after)

    def test_prejournal_crash_quarantines_source_backup_without_active_change(self):
        self.invoke(point='previous_environment',fault='crash',exit_code=87)
        self.assertEqual(self.active(),self.original)
        self.assertFalse((self.root/'transaction.state').exists())
        self.assertEqual(self.boot()['error'],'boot_recovery_incomplete_preparation')

    def test_independent_supervisor_restores_startup_records_after_caller_crash(self):
        self.case.ensure_recovery_worker=lambda root:None
        supervisor=subprocess.Popen(self.case.command('supervisor',ttl=45),cwd=ROOT,
            stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
        self.case.children.append(supervisor)
        deadline=time.monotonic()+10
        while not (self.root/'recovery.ready').exists() and time.monotonic()<deadline:
            self.assertIsNone(supervisor.poll());time.sleep(0.05)
        self.assertTrue((self.root/'recovery.ready').is_file())
        self.invoke(ttl=4,point='activate_environment',fault='crash',exit_code=87)
        out,err=supervisor.communicate(timeout=15)
        self.assertEqual(supervisor.returncode,0,err)
        result=json.loads(out.strip().splitlines()[-1])
        self.assertEqual(result['status'],'SOURCE_SUPERVISOR_COMPLETE')
        self.assertEqual(result['recovery'],'rolled_back')
        self.assertEqual(self.active(),self.original)

    def test_source_inode_safety_checks_prevent_preview_reads(self):
        path=self.root/'active'/self.names['environment']
        original=path.read_bytes();sentinel=self.root/'private-source-sentinel'
        sentinel.write_bytes(original);sentinel.chmod(0o600)
        for kind in ('symlink','hardlink','mode'):
            with self.subTest(kind=kind):
                path.unlink()
                if kind=='symlink':path.symlink_to(sentinel)
                elif kind=='hardlink':os.link(sentinel,path)
                else:path.write_bytes(original);path.chmod(0o644)
                result=self.invoke('preview')
                self.assertEqual(result['error'],'unsafe_transaction_file')
                self.assertEqual(sentinel.read_bytes(),original)
                self.assertFalse((self.root/'transaction.state').exists())
        path.unlink();path.write_bytes(original);path.chmod(0o600)

    def test_unset_override_and_absent_cache_are_restored_without_normalization(self):
        self.environment['lct_vlan']={'state':'unset'}
        self.caches['ipaddr']={'state':'absent'}
        self.original['environment']=encode('ENV',self.environment)
        self.original['cache']=encode('CACHE',self.caches)
        for part in ('environment','cache'):
            for directory in ('active','source'):
                path=self.root/directory/self.names[part];path.write_bytes(self.original[part]);path.chmod(0o600)
        self.pending();self.restored(self.invoke('recover'))
        self.assertEqual(decode(self.active()['environment'])['lct_vlan'],{'state':'unset'})
        self.assertEqual(decode(self.active()['cache'])['ipaddr'],{'state':'absent'})

    def test_inverse_transition_updates_saved_vlan_to_untagged_in_new_workspace(self):
        token=self.pending();self.invoke('confirm',token=token);tagged=self.active();self.stop()
        other=tx.NativeTransactionTests();other.setUp()
        try:
            other.original={p:tagged[p] for p in ('network','firewall')}
            for part,raw in other.original.items():
                for directory in (other.root/'source',other.root/'active',other.stage/'candidate'):
                    path=directory/other.packages[part];path.write_bytes(raw);path.chmod(0o600)
            for part in ('environment','cache'):
                path=other.root/'active'/('aott_c014_'+other.suffix+'_'+part)
                path.write_bytes(tagged[part]);path.chmod(0o600)
            result=other.invoke(fault='vlan_unchanged')
            self.assertEqual(result['status'],'SOURCE_TXN_PENDING_CONFIRMATION')
            self.assertEqual(other.invoke('confirm',token=result['transaction_id'])['status'],'SOURCE_TXN_CONFIRMED')
            env=other.root/'active'/('aott_c014_'+other.suffix+'_environment')
            self.assertEqual(decode(env.read_bytes())['lct_vlan']['value'],'0')
            for worker in other.admission_workers.values():
                if worker.poll() is None:worker.kill();worker.wait(timeout=10)
            self.assertEqual(other.invoke('boot_gate')['status'],'SOURCE_BOOT_RECONCILIATION_CHECKED')
        finally:other.tearDown()

    def test_receipts_omit_record_values_and_hashes(self):
        token=self.pending();r=self.invoke('confirm',token=token);raw=json.dumps(r)
        for v in (tx.reference.IP,tx.reference.MAC,hashlib.sha256(self.original['environment']).hexdigest(),'factory_mac'):
            self.assertNotIn(v,raw)
        self.assertFalse(r['contains_configuration_values'])


if __name__=='__main__':unittest.main()
