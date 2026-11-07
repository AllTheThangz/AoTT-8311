"""Startup-source agreement, actual cached shell getters and native boot gate.
Only private synthetic evidence/configuration files; no live environment read.
"""
import copy
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import tempfile
import unittest

import test_c014_apply_recovery as transaction
import test_c014_native_lua_transition as portable
import test_c014_management_vlan_path as characterization
import test_c014_storage_boot as storage

ROOT=Path(__file__).resolve().parents[1]
VENDOR=transaction.VENDOR
MODEL=ROOT/'prototypes/configuration/8311/management_sources.lua'
SOURCE=ROOT/'overlay/lib/8311.sh'
DNS='.'.join(('192','0','2','20'))
OTHER='.'.join(('198','51','100','10'))


def evidence():
    network=transaction.reference.state()['network']
    network['lct']['options']['dns']=[DNS]
    values={'ipaddr':transaction.reference.IP,'netmask':transaction.reference.MASK,
            'gateway':transaction.reference.IP,'dns_server':DNS,
            'lct_mac':transaction.reference.MAC,'lct_vlan':'0'}
    return {'environment':{k:{'state':'value','value':v} for k,v in values.items()},
            'cache':{k:{'state':'absent'} for k in values if k!='lct_vlan'},
            'factory_mac':{'state':'absent'},'network':network}


class SourceAgreementTests(unittest.TestCase):
    def run_lua(self,script):
        if not shutil.which('lua5.1'):self.skipTest('Host Lua 5.1 required')
        prelude='package.path=arg[1].."/prototypes/configuration/?.lua;"..package.path\nlocal m=require "8311.management_sources"\n'
        result=subprocess.run(['lua5.1','-',str(ROOT)],input=prelude+script+'\nprint("SOURCE_AGREEMENT_PASS")\n',
            capture_output=True,text=True,timeout=8)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertIn('SOURCE_AGREEMENT_PASS',result.stdout)

    def test_syntax_no_io_and_not_installed(self):
        result=subprocess.run(['luac5.1','-p',str(MODEL)],capture_output=True,text=True,timeout=8)
        self.assertEqual(result.returncode,0,result.stderr)
        source=MODEL.read_text()
        for item in ('io.open','os.execute','io.popen','fwenv_get','fwenv_set','nixio','socket'):
            self.assertNotIn(item,source)
        self.assertNotIn(MODEL.name,(ROOT/'MANIFEST.json').read_text())
        self.assertFalse((ROOT/'overlay/usr/lib/lua/8311'/MODEL.name).exists())

    def test_valid_source_profile_returns_redacted_non_production_receipt(self):
        self.run_lua('local e='+portable.lua(evidence())+'''
local h,why=m.review(e);assert(h,why)
assert(m.verify(h,e))
local r=assert(m.report(h));assert(r.fields_checked==6 and r.boot_cache_entries==0)
assert(not r.production_activation_allowed and not r.future_reboot_proven and not r.live_effect_proven)
assert(not r.contains_configuration_values)
for k,v in pairs(r)do assert(type(v)~="table");assert(k~="saved" and k~="network")end
''')

    def test_current_boot_cache_cannot_hide_conflicting_saved_source(self):
        variants=[]
        for key,value in (('ipaddr',OTHER),('netmask','.'.join(('255','255','0','0'))),('gateway',OTHER),('dns_server',OTHER),
                          ('lct_mac',':'.join(('02','00','00','00','00','99')))):
            e=evidence();e['cache'][key]={'state':'value','value':value};variants.append((e,key))
        self.run_lua('\n'.join('do local h,w=m.review('+portable.lua(e)+');assert(h==nil and w=="startup_cache_conflicts_'+k+'")end' for e,k in variants))

    def test_saved_environment_must_match_uci_including_vlan(self):
        tests=[]
        for key,value in (('ipaddr',OTHER),('gateway',''),('dns_server',''),('lct_vlan','123')):
            e=evidence();e['environment'][key]={'state':'value','value':value};tests.append((e,key))
        self.run_lua('\n'.join('do local h,w=m.review('+portable.lua(e)+');assert(h==nil and w=="startup_override_conflicts_'+k+'")end' for e,k in tests))

    def test_supported_unset_defaults_need_independent_factory_mac(self):
        e=evidence()
        e['environment']={k:{'state':'unset'} for k in e['environment']}
        e['factory_mac']={'state':'value','value':transaction.reference.MAC}
        opts=e['network']['lct']['options'];opts['ipaddr']='.'.join(('192','168','11','1'));opts.pop('gateway');opts.pop('dns')
        self.run_lua('local e='+portable.lua(e)+'''
assert(m.review(e))
e.factory_mac={state="absent"};local h,w=m.review(e);assert(h==nil and w=="management_factory_mac_unavailable")
''')

    def test_invalid_saved_values_are_not_silently_treated_as_unset(self):
        tests=[]
        for key,value in (('ipaddr','bad'),('netmask','.'.join(('255','0','255','0'))),('gateway','bad'),('dns_server','resolver.example.invalid'),
                          ('lct_mac','bad'),('lct_vlan','4095'),('lct_vlan','00123'),('lct_vlan','bad')):
            e=evidence();e['environment'][key]={'state':'value','value':value};tests.append((e,key))
        self.run_lua('\n'.join('do local h,w=m.review('+portable.lua(e)+');assert(h==nil and w=="management_value_unqualified_'+k+'")end' for e,k in tests))

    def test_empty_optional_cache_is_evidence_not_a_missing_read(self):
        e=evidence()
        for name in ('gateway','dns_server'):
            e['environment'][name]={'state':'unset'};e['cache'][name]={'state':'value','value':''}
        e['network']['lct']['options'].pop('gateway');e['network']['lct']['options'].pop('dns')
        self.run_lua('local e='+portable.lua(e)+'''
assert(m.review(e));e.cache.gateway={state="unreadable"}
local h,w=m.review(e);assert(h==nil and w=="management_evidence_unavailable")
''')

    def test_caches_may_fill_with_reviewed_values_but_must_not_disappear(self):
        self.run_lua('local e='+portable.lua(evidence())+'''
local h=assert(m.review(e))
for key,item in pairs(e.environment)do
 if key~="lct_vlan"then e.cache[key]={state="value",value=item.value}end
end
assert(m.verify(h,e));assert(m.report(h).boot_cache_entries==5)
e.cache.ipaddr={state="absent"}
local ok,w=m.verify(h,e);assert(ok==nil and w=="management_sources_changed")
''')

    def test_same_effective_value_does_not_hide_saved_source_revision_change(self):
        e=evidence();e['environment']['gateway']={'state':'unset'};e['network']['lct']['options'].pop('gateway')
        self.run_lua('local e='+portable.lua(e)+'''
local h=assert(m.review(e));e.environment.gateway={state="value",value=""}
local ok,w=m.verify(h,e);assert(ok==nil and w=="management_sources_changed")
''')

    def test_mac_case_and_single_dns_list_are_semantically_equivalent(self):
        e=evidence();e['environment']['lct_mac']['value']=e['environment']['lct_mac']['value'].upper()
        self.run_lua('local e='+portable.lua(e)+'''
local h=assert(m.review(e));e.network.lct.options.dns=e.network.lct.options.dns[1]
assert(m.verify(h,e))
e.network.lct.options.dns={"192.0.2.20","192.0.2.1"}
local ok,w=m.verify(h,e);assert(ok==nil and w=="management_dns_unqualified")
''')

    def test_tagged_profile_requires_one_unambiguous_interface(self):
        e=evidence();e['network']=transaction.reference.plan({'network':e['network'],'firewall':transaction.reference.state()['firewall']},123)['after']['network']
        e['environment']['lct_vlan']={'state':'value','value':'123'}
        self.run_lua('local e='+portable.lua(e)+'''
assert(m.review(e));e.network.lct.options.ipaddr=e.network.mgmt.options.ipaddr
local h,w=m.review(e);assert(h==nil and w=="management_uci_topology_ambiguous")
''')

    def test_unknown_environment_fields_and_malformed_records_are_rejected(self):
        self.run_lua('local base='+portable.lua(evidence())+'''
base.environment.serial={state="value",value="PRIVATE"}
local h,w=m.review(base);assert(h==nil and w=="management_environment_scope_invalid")
base.environment.serial=nil;base.cache.ipaddr={state="value",value="PRIVATE",extra=true}
h,w=m.review(base);assert(h==nil and w=="management_evidence_record_invalid")
base.cache.ipaddr={state="absent"};setmetatable(base.environment.ipaddr,{})
h,w=m.review(base);assert(h==nil and w=="management_evidence_record_invalid")
''')

    def test_private_proof_and_callback_data_cannot_override_expected_profile(self):
        self.run_lua('local e='+portable.lua(evidence())+'''
local h=assert(m.review(e));h.saved={ipaddr="PRIVATE"}
local receipt=assert(m.report(h));receipt.production_activation_allowed=true
assert(m.report(h).production_activation_allowed==false);assert(m.verify(h,e))
local ok,w=m.verify({},e);assert(ok==nil and w=="invalid_management_source_proof")
e.environment.ipaddr.value="PRIVATE"
ok,w=m.verify(h,e);assert(ok==nil and not w:find("PRIVATE",1,true))
''')


class NativeGetterCharacterization(unittest.TestCase):
    def setUp(self):
        if not os.environ.get('AOTT_VENDOR_ROOTFS') or not shutil.which('qemu-mips-static'):
            self.skipTest('Private vendor shell required')
        self.temp=tempfile.TemporaryDirectory(prefix='aott-c014-precedence-',dir='/var/tmp')
        self.path=Path(self.temp.name);self.path.chmod(0o700)
        (self.path/'env').mkdir(mode=0o700)
        (self.path/'cache').mkdir(mode=0o700)
        self.native_calls=[]
        self.initial={k:v['value'] for k,v in evidence()['environment'].items()}
        for k,v in self.initial.items():self.set_env(k,v)
        self.set_env('factory_mac',transaction.reference.MAC)

    def tearDown(self):self.temp.cleanup()

    def set_env(self,key,value):
        path=self.path/'env'/key;path.write_text(value);path.chmod(0o600)

    def function(self,name,source=SOURCE):
        match=re.search(r'(?ms)^'+re.escape(name)+r'\(\) \{\n.*?^\}',source.read_text())
        self.assertIsNotNone(match,name)
        text=match.group()
        for cache in ('ipaddr','netmask','gateway','dns','lct-mac'):
            text=text.replace('/tmp/8311-'+cache,str(self.path/'cache'/cache))
        self.assertNotIn('/tmp/8311-',text)
        return text

    def run_shell(self,body,functions):
        q=shlex.quote
        prelude='bb() { /usr/bin/qemu-mips-static -L '+q(str(VENDOR))+' '+q(str(VENDOR/'bin/busybox'))+' "$@"; }\n'
        prelude+='grep() { bb grep "$@"; }; cat() { bb cat "$@"; }; tr() { bb tr "$@"; }\n'
        prelude+='fwenv_get_8311() { case "$1" in ipaddr|netmask|gateway|dns_server|lct_mac|lct_vlan) ;; *) return 9;; esac; '
        prelude+='if [ -f '+q(str(self.path/'env'))+'/"$1" ]; then cat '+q(str(self.path/'env'))+'/"$1"; else printf "%s" "$2"; fi; }\n'
        prelude+='pon_mac_get() { cat '+q(str(self.path/'env/factory_mac'))+'; }\n'
        code=prelude+'\n'.join(functions)+'\n'+body
        r=subprocess.run(['qemu-mips-static','-L',str(VENDOR),str(VENDOR/'bin/busybox'),'sh'],input=code,capture_output=True,text=True,timeout=10)
        self.assertEqual(r.returncode,0,r.stderr)
        return r.stdout

    def getter(self,name):
        return self.run_shell('get_8311_'+name+'\n',[self.function('ipv4'),self.function('strtoupper'),self.function('get_8311_'+name)]).strip()

    def test_existing_ipv4_cache_masks_later_saved_override(self):
        self.assertEqual(self.getter('ipaddr'),self.initial['ipaddr'])
        self.set_env('ipaddr',OTHER)
        self.assertEqual(self.getter('ipaddr'),self.initial['ipaddr'])
        (self.path/'cache/ipaddr').unlink()
        self.assertEqual(self.getter('ipaddr'),OTHER)

    def test_gateway_cache_retains_value_after_saved_clear(self):
        self.assertEqual(self.getter('gateway'),self.initial['gateway'])
        self.set_env('gateway','')
        self.assertEqual(self.getter('gateway'),self.initial['gateway'])
        (self.path/'cache/gateway').unlink()
        self.assertEqual(self.getter('gateway'),'')

    def test_empty_dns_cache_masks_new_saved_dns(self):
        self.set_env('dns_server','')
        self.assertEqual(self.getter('dns_server'),'')
        self.set_env('dns_server',DNS)
        self.assertEqual(self.getter('dns_server'),'')
        (self.path/'cache/dns').unlink()
        self.assertEqual(self.getter('dns_server'),DNS)

    def test_vlan_getter_is_uncached_unlike_ip(self):
        self.assertEqual(self.getter('lct_vlan'),'0')
        self.set_env('lct_vlan','123')
        self.assertEqual(self.getter('lct_vlan'),'123')
        self.assertFalse(any((self.path/'cache').iterdir()))

    def test_factory_mac_is_cached_until_cache_removed(self):
        self.set_env('lct_mac','')
        self.assertEqual(self.getter('lct_mac'),self.initial['lct_mac'].upper())
        new=':'.join(('02','ab','cd','01','02','03'));self.set_env('lct_mac',new)
        self.assertEqual(self.getter('lct_mac'),self.initial['lct_mac'].upper())
        (self.path/'cache/lct-mac').unlink()
        self.assertEqual(self.getter('lct_mac'),new.upper())

    def test_netinit_management_calls_do_not_write_uci_in_current_backend(self):
        names=['ipv4','strtoupper']+['get_8311_'+x for x in ('ipaddr','netmask','gateway','dns_server','lct_mac','lct_vlan')]
        names+=['set_8311_'+x for x in ('ipaddr','netmask','gateway','dns_server','lct_mac','lct_vlan','iphost_mac')]
        functions=[self.function(x) for x in names]
        backend=ROOT/'overlay/lib/8311_backend.sh'
        functions += [self.function('_set_8311_'+x,backend) for x in ('ipaddr','netmask','gateway','lct_mac','iphost_mac')]
        functions.append(self.function('boot',ROOT/'overlay/etc/init.d/_8311-netinit.sh'))
        body='''to_console() { cat >/dev/null; }
get_8311_ethtool() { printf ''; }
get_8311_iphost_mac() { pon_mac_get host; }
uci() { printf 'UNEXPECTED_UCI\\n'; return 99; }
ifup() { printf 'IFUP:%s\\n' "$1"; }
boot
'''
        self.set_env('lct_vlan','123')
        self.assertEqual(self.run_shell(body,functions).splitlines(),['IFUP:lct','IFUP:mgmt'])


class DefaultsWriterCharacterization(unittest.TestCase):
    def setUp(self):self.case=characterization.ManagementVlanCharacterization();self.case.setUp()
    def tearDown(self):self.case.tearDown()

    def test_empty_dns_default_does_not_clear_existing_uci_dns(self):
        state=json.loads(self.case.state_path.read_text());state['network.lct.dns']=DNS
        self.case.state_path.write_text(json.dumps(state))
        result,state=self.case.run_source(0)
        self.assertEqual(result.returncode,0);self.assertEqual(state['network.lct.dns'],DNS)

    def test_defaults_are_actual_management_address_writer(self):
        state=json.loads(self.case.state_path.read_text());state['network.lct.ipaddr']=OTHER
        self.case.state_path.write_text(json.dumps(state))
        result,state=self.case.run_source(0)
        self.assertEqual(result.returncode,0);self.assertEqual(state['network.lct.ipaddr'],transaction.reference.IP)

    def test_backend_audit_does_not_classify_arbitrary_functions_as_noop(self):
        self.assertTrue(storage.audit.backend_noop('f() {\n # delegated\n return 0\n}\n','f'))
        self.assertFalse(storage.audit.backend_noop('f() {\n uci set value\n return 0\n}\n','f'))
        self.assertFalse(storage.audit.backend_noop('','f'))


class NativeSourceGateTests(unittest.TestCase):
    def setUp(self):
        self.case=transaction.NativeTransactionTests();self.case.setUp()
        self.evidence=storage.prepare_boot_sources(self.case);self.root=self.case.root
    def tearDown(self):self.case.tearDown()
    def save(self):
        p=self.root/'source-evidence.json';p.write_text(json.dumps(self.evidence));p.chmod(0o600)
    def stop(self):
        for p in self.case.admission_workers.values():
            if p.poll() is None:p.kill();p.wait(timeout=10)
    def boot(self,**kw):self.stop();return self.case.invoke('boot_gate',**kw)

    def test_matching_sources_are_checked_through_all_boot_consumers(self):
        self.case.pending();r=self.boot()
        self.assertEqual(r['status'],'SOURCE_BOOT_RECONCILIATION_CHECKED')
        self.assertTrue(r['source_precedence_verified']);self.assertEqual(self.case.active(),self.case.original)

    def test_confirmed_uci_vlan_alone_is_not_saved_source_persistence(self):
        id=self.case.pending();self.case.invoke('confirm',token=id);before=self.case.active()
        r=self.boot()
        self.assertEqual(r['error'],'boot_startup_override_conflicts_lct_vlan')
        self.assertEqual(self.case.active(),before);self.assertEqual(self.case.phase(),'confirmed')

    def test_rollback_does_not_claim_successful_boot_when_saved_address_disagrees(self):
        self.case.pending();self.evidence['environment']['ipaddr']['value']=OTHER;self.save()
        r=self.boot()
        self.assertEqual(r['error'],'boot_startup_override_conflicts_ipaddr')
        self.assertEqual(self.case.active(),self.case.original)

    def test_stale_cache_blocks_even_when_active_uci_matches_saved_override(self):
        self.evidence['cache']['ipaddr']={'state':'value','value':OTHER};self.save()
        r=self.boot();self.assertEqual(r['error'],'boot_startup_cache_conflicts_ipaddr')
        self.assertFalse((self.root/'transaction.state').exists())

    def test_saved_clear_cannot_hide_stale_uci_dns(self):
        self.evidence['environment']['dns_server']={'state':'unset'};self.save()
        r=self.boot();self.assertEqual(r['error'],'boot_startup_override_conflicts_dns_server')

    def test_missing_source_read_and_exceptions_are_not_success_or_disclosure(self):
        (self.root/'source-evidence.json').unlink()
        r=self.boot();self.assertEqual(r['error'],'boot_management_source_read_failed')
        self.save();r=self.boot(fault='source_exception')
        self.assertEqual(r['error'],'boot_management_source_read_failed')
        self.assertNotIn('PRIVATE_SOURCE_EXCEPTION',json.dumps(r))

    def test_source_change_after_review_revokes_remaining_checkpoints(self):
        r=self.boot(fault='saved_changes_after_review')
        self.assertEqual(r['error'],'boot_startup_override_conflicts_ipaddr')

    def test_late_netinit_checkpoint_catches_cache_conflict_before_https(self):
        r=self.boot(fault='late_cache_conflict')
        self.assertEqual(r['error'],'boot_startup_cache_conflicts_ipaddr')

    def test_matching_cache_population_during_boot_is_allowed(self):
        r=self.boot(fault='populate_matching_cache')
        self.assertEqual(r['status'],'SOURCE_BOOT_RECONCILIATION_CHECKED')
        self.assertTrue(r['source_precedence_verified'])


if __name__=='__main__':unittest.main()
