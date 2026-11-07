"""Protected retention, native boot reconciliation, and reference-only boot audit.
No live ONU, system service, real config package or firmware bank is accessed.
"""
import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest import mock

import test_c014_apply_recovery as transaction
import test_c014_native_lua_transition as lua_reference

ROOT=Path(__file__).resolve().parents[1]
STORAGE=ROOT/'prototypes/configuration/8311/recovery_storage.lua'
BOOT=ROOT/'prototypes/configuration/8311/boot_recovery_gate.lua'
SPEC=importlib.util.spec_from_file_location('audit_prx126_boot_storage',ROOT/'tools/audit_prx126_boot_storage.py')
audit=importlib.util.module_from_spec(SPEC);SPEC.loader.exec_module(audit)


class StorageContractTests(unittest.TestCase):
    def run_lua(self,body):
        if not shutil.which('lua5.1'):self.skipTest('Host Lua missing')
        prelude='package.path=arg[1].."/prototypes/configuration/?.lua;"..package.path\nlocal m=require "8311.recovery_storage"\n'
        result=subprocess.run(['lua5.1','-',str(ROOT)],input=prelude+body+'\nprint("STORAGE_CONTRACT_PASS")\n',
            capture_output=True,text=True,timeout=8)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertIn('STORAGE_CONTRACT_PASS',result.stdout)

    def test_lua51_syntax_and_no_runtime_install(self):
        for path in (STORAGE,BOOT):
            result=subprocess.run(['luac5.1','-p',str(path)],capture_output=True,text=True,timeout=8)
            self.assertEqual(result.returncode,0,result.stderr)
        manifest=(ROOT/'MANIFEST.json').read_text()
        self.assertIn(STORAGE.name,manifest)
        self.assertTrue((ROOT/'overlay/usr/lib/lua/8311'/STORAGE.name).is_file())
        self.assertNotIn(BOOT.name,manifest)
        self.assertFalse((ROOT/'overlay/usr/lib/lua/8311'/BOOT.name).exists())

    def test_capacity_exact_threshold_and_inode_accounting(self):
        self.run_lua('''local s={frsize=4096,bavail=256,flag=0,files=1000,favail=24}
local r,e=m.reserve(s);assert(r,e);assert(r.reserve_bytes==1048576 and r.inode_accounting_available)
s.bavail=255;r,e=m.reserve(s);assert(r==nil and e=="recovery_capacity_insufficient")
s.bavail=256;s.favail=23;r,e=m.reserve(s);assert(r==nil and e=="recovery_inode_capacity_insufficient")
s.files=0;s.favail=0;r,e=m.reserve(s);assert(r and not r.inode_accounting_available)
''')

    def test_readonly_unknown_fractional_and_overflow_capacity_rejected(self):
        self.run_lua('''local cases={
 {frsize=4096,bavail=10000,flag=1,files=1000,favail=100},
 {frsize=0,bavail=10000,flag=0,files=1000,favail=100},
 {frsize=4096,bavail=-1,flag=0,files=1000,favail=100},
 {frsize=4096,bavail=1.5,flag=0,files=1000,favail=100},
 {frsize=4096,bavail=9007199254740991,flag=0,files=1000,favail=100},
 {frsize=4096,bavail=10000,flag=0},
 {frsize=4096,bavail=10000,flag=0,files=1000,favail=-1}}
for _,s in ipairs(cases) do local r,e=m.reserve(s);assert(r==nil and type(e)=="string")end
local r,e=m.reserve(nil);assert(r==nil and e=="recovery_capacity_unavailable")
''')

    def test_manifest_roundtrip_tamper_workspace_binding_and_no_raw_data(self):
        self.run_lua('''local id=string.rep("a",16)
local entries={}
for _,name in ipairs({"previous_network","previous_firewall","candidate_network","candidate_firewall"}) do
 entries[name]={bytes=100,sha256=string.rep("b",64)}
end
local encoded,e=m.encode(id,entries);assert(encoded,e)
local r,e=m.verify(id,encoded,entries);assert(r,e);assert(r.files==4 and not r.contains_configuration_values)
r,e=m.verify(string.rep("c",16),encoded,entries);assert(r==nil and e=="retention_manifest_wrong_workspace")
entries.candidate_network.bytes=101
r,e=m.verify(id,encoded,entries);assert(r==nil and e=="retention_manifest_content_mismatch")
entries.candidate_network.bytes=100
r,e=m.verify(id,encoded.."extra\\n",entries);assert(r==nil)
r,e=m.verify(id,encoded:gsub(" 100 "," 0100 "),entries);assert(r==nil)
r,e=m.verify(id,encoded:gsub("candidate_firewall","candidate_network"),entries);assert(r==nil)
''')

    def test_manifest_refuses_extra_missing_oversized_and_metatable_entries(self):
        self.run_lua('''local names={"previous_network","previous_firewall","candidate_network","candidate_firewall"}
for scenario=1,6 do
 local e={};for _,name in ipairs(names) do e[name]={bytes=1,sha256=string.rep("b",64)}end
 if scenario==1 then e.extra={bytes=1,sha256=string.rep("b",64)}
 elseif scenario==2 then e.previous_network=nil
 elseif scenario==3 then e.previous_network.bytes=65537
 elseif scenario==4 then e.previous_network.bytes=0
 elseif scenario==5 then e.previous_network.raw="PRIVATE"
 else setmetatable(e.previous_network,{}) end
 local r,why=m.encode(string.rep("a",16),e);assert(r==nil and not why:find("PRIVATE",1,true))
end
''')

    def test_proposed_persistent_store_screen_never_authorizes_activation(self):
        self.run_lua('''local f={mountpoint="/ptconf",store_path="/ptconf/8311/aott-recovery/v1",
 ancestors_verified=true,store_uid=0,store_gid=0,store_mode=700,mount_read_only=false,
 same_filesystem=true,physical_mount_verified=true,fs_type="ubifs",reference_only=true,
 capacity={frsize=4096,bavail=256,flag=0,files=0,favail=0}}
local r,e=m.screen_persistent_evidence(f);assert(r,e);assert(not r.production_activation_allowed)
f.reference_only=false;f.live_observation=true;r,e=m.screen_persistent_evidence(f)
assert(r and not r.production_activation_allowed and r.needs_power_loss_and_bank_qualification)
for _,kind in ipairs({"tmpfs","overlay","ext4","unknown"})do
 f.fs_type=kind;r,e=m.screen_persistent_evidence(f);assert(r==nil)end
f.fs_type="ubifs";f.ancestors_verified=false;r,e=m.screen_persistent_evidence(f);assert(r==nil)
f.ancestors_verified=true;f.reference_only="yes";r,e=m.screen_persistent_evidence(f);assert(r==nil)
''')

    def test_boot_scope_forged_handles_and_order_refused_without_native_reads(self):
        self.run_lua('''local b=require "8311.boot_recovery_gate"
for _,root in ipairs({"/etc/config","/ptconf","/var/tmp/aott-c014-txn-test-a"})do
 local r,e=b.reconcile(root,"offline_synthetic");assert(r==nil and e=="boot_recovery_scope_refused")end
local r,e=b.reconcile("/var/tmp/aott-c014-txn-test-0123456789abcdef","production")
assert(r==nil and e=="boot_recovery_scope_refused")
r,e=b.after({},"before_network","offline_synthetic");assert(r==nil and e=="invalid_boot_recovery_handle")
''')


class ExtractedBootAuditTests(unittest.TestCase):
    def test_reference_audit_does_not_read_configuration_contents(self):
        with tempfile.TemporaryDirectory(prefix='aott-boot-audit-') as path:
            vendor=Path(path)
            (vendor/'etc/init.d').mkdir(parents=True)
            (vendor/'etc/config').mkdir()
            (vendor/'etc/config/secret').write_text('PRIVATE_SENTINEL_NEVER_READ')
            (vendor/'etc/init.d/boot').write_text('START=10\nboot() { uci_apply_defaults; }\n')
            (vendor/'etc/init.d/network').write_text('START=20\n')
            (vendor/'var').symlink_to('tmp')
            real=Path.read_bytes
            def guarded(p):
                self.assertNotIn('/etc/config/',str(p))
                return real(p)
            with mock.patch.object(Path,'read_bytes',guarded):
                result=audit.audit(ROOT,vendor)
            self.assertFalse(result['live_device_examined'])
            self.assertFalse(result['config_values_read'])
            self.assertFalse(result['production_activation_allowed'])
            self.assertNotIn('PRIVATE_SENTINEL_NEVER_READ',json.dumps(result))
            self.assertIn('DEFAULTS_MUTATE_BEFORE_CURRENT_CONFIG_SNAPSHOT',[b['code'] for b in result['blockers']])
            self.assertIn('VAR_TMP_NOT_DURABLE_BY_REFERENCE_LAYOUT',[b['code'] for b in result['blockers']])

    def test_missing_reference_files_are_reported_not_invented(self):
        with tempfile.TemporaryDirectory(prefix='aott-boot-audit-') as path:
            result=audit.audit(ROOT,Path(path))
            self.assertFalse(result['source_files']['boot']['available'])
            self.assertFalse(result['reference_facts']['var_is_tmp_symlink'])
            self.assertFalse(result['production_activation_allowed'])

    def test_symlink_source_is_not_read_and_init_is_not_executed(self):
        with tempfile.TemporaryDirectory(prefix='aott-boot-audit-') as path:
            vendor=Path(path);(vendor/'etc/init.d').mkdir(parents=True)
            marker=vendor/'marker'
            (vendor/'etc/init.d/boot').write_text('START=10\ntouch '+str(marker)+'\n')
            (vendor/'secret').write_text('PRIVATE')
            (vendor/'etc/init.d/network').symlink_to(vendor/'secret')
            result=audit.audit(ROOT,vendor)
            self.assertFalse(marker.exists())
            self.assertTrue(result['source_files']['network']['refused_type_or_size'])
            self.assertNotIn('PRIVATE',json.dumps(result))

    @unittest.skipUnless(os.environ.get('AOTT_VENDOR_ROOTFS'),'Private extracted reference required')
    def test_actual_extracted_reference_exposes_reboot_and_precedence_blockers(self):
        result=audit.audit(ROOT,transaction.VENDOR)
        self.assertEqual(result['basis'],'EXTRACTED_REFERENCE_AND_SOURCE_ONLY')
        self.assertEqual(result['startup_priorities']['boot'],10)
        self.assertEqual(result['startup_priorities']['capture'],17)
        self.assertEqual(result['startup_priorities']['sysinit'],18)
        self.assertEqual(result['startup_priorities']['network'],20)
        self.assertEqual(result['startup_priorities']['netinit'],26)
        self.assertTrue(result['reference_facts']['persistence_flag_controls_rootfs_data'])
        self.assertEqual(len(result['blockers']),6)
        self.assertTrue(result['reference_facts']['backend_management_setters_are_noops'])
        self.assertNotIn('LATER_ENV_CONSUMER_CAN_OVERWRITE_RESTORED_UCI',[b['code'] for b in result['blockers']])
        self.assertFalse(result['bank_selector_read'])


def prepare_boot_sources(case):
    """Synthetic saved source, independent of later active/candidate writes.

    The shell getter accepts IPv4 DNS, unlike the generic transaction fixture
    which deliberately uses a hostname to test representation preservation.
    Use a valid DNS address here rather than claiming that hostname survives
    this board's boot-source filter.
    """
    case.original["network"]=case.original["network"].replace(b"resolver.example.invalid",b"192.0.2.20")
    for package,raw in case.original.items():
        for directory in (case.root/"source",case.root/"active",case.stage/"candidate"):
            path=directory/case.packages[package];path.write_bytes(raw);path.chmod(0o600)
    values={"ipaddr":transaction.reference.IP,"netmask":transaction.reference.MASK,
            "gateway":transaction.reference.IP,"dns_server":"192.0.2.20",
            "lct_mac":transaction.reference.MAC,"lct_vlan":"0"}
    evidence={"environment":{k:{"state":"value","value":v} for k,v in values.items()},
              "cache":{k:{"state":"absent"} for k in values if k!="lct_vlan"},
              "factory_mac":{"state":"absent"}}
    path=case.root/"source-evidence.json"
    path.write_text(json.dumps(evidence,sort_keys=True));path.chmod(0o600)
    return evidence


class NativeRetentionAndBootTests(unittest.TestCase):
    def setUp(self):
        self.case=transaction.NativeTransactionTests();self.case.setUp()
        self.root=self.case.root
        prepare_boot_sources(self.case)

    def tearDown(self):self.case.tearDown()

    def stop_workers(self):
        for worker in self.case.admission_workers.values():
            if worker.poll() is None:worker.kill();worker.wait(timeout=10)

    def begin(self):return self.case.pending()
    def invoke(self,action='begin',**kw):return self.case.invoke(action,**kw)
    def boot(self,**kw):self.stop_workers();return self.invoke('boot_gate',**kw)

    def test_capacity_shortage_readonly_and_unknown_capacity_prevent_staging(self):
        for fault in ('capacity_low','inodes_low','capacity_missing','readonly_storage'):
            with self.subTest(fault=fault):
                result=self.invoke(fault=fault)
                self.assertEqual(result['error'],'transaction_recovery_storage_not_ready')
                self.assertEqual(result['native_stage_operations'],0)
                self.assertEqual(self.case.active(),self.case.original)
                self.assertFalse((self.root/'previous.network').exists())
                self.assertFalse((self.root/'transaction.state').exists())

    def test_retained_manifest_binds_all_four_files_and_is_private(self):
        self.begin()
        path=self.root/'retained.state';raw=path.read_text();rows=raw.splitlines()
        self.assertEqual(rows[:2],['AOTT-RETAINED-CONFIG-1',self.case.suffix])
        for row in rows[2:]:
            name,size,sha=row.split()
            filename=name.replace('_','.',1)
            content=(self.root/filename).read_bytes()
            self.assertEqual(int(size),len(content));self.assertEqual(sha,hashlib.sha256(content).hexdigest())
        self.assertEqual(path.stat().st_mode&0o777,0o600)
        for value in (transaction.reference.IP,transaction.reference.MAC,'resolver.example.invalid'):
            self.assertNotIn(value,raw)
        self.case.restored(self.invoke('recover'))

    def test_retention_seal_sync_failure_or_replace_failure_never_activates(self):
        for fault,point in (('sync_fail','retention_seal_sync'),('replace_fail','retention_seal')):
            with self.subTest(fault=fault):
                self.case.setup_case();self.root=self.case.root;prepare_boot_sources(self.case)
                result=self.invoke(fault=fault,point=point)
                self.assertEqual(result['status'],'REJECTED')
                self.assertEqual(self.case.active(),self.case.original)
                self.assertFalse((self.root/'transaction.state').exists())
                self.assertFalse((self.root/'retained.state').exists())

    def test_crash_after_sealing_before_journal_never_changes_active_files(self):
        self.invoke(point='retention_seal',fault='crash',exit_code=87)
        self.assertEqual(self.case.active(),self.case.original)
        self.assertTrue((self.root/'retained.state').exists())
        self.assertFalse((self.root/'transaction.state').exists())
        self.assertEqual(self.boot()['error'],'boot_recovery_incomplete_preparation')

    def test_corrupt_or_cross_workspace_manifest_prevents_recovery_overwrite(self):
        self.begin();self.stop_workers();before=self.case.active()
        path=self.root/'retained.state';original=path.read_text()
        for raw in ('PRIVATE_BAD_MANIFEST',original.replace(self.case.suffix,'0'*16,1),original+'extra\n'):
            with self.subTest(length=len(raw)):
                path.write_text(raw)
                result=self.invoke('recover')
                self.assertEqual(result['error'],'transaction_retention_not_verified')
                self.assertEqual(self.case.active(),before)
                self.assertEqual(self.case.phase(),'pending')
        path.write_text(original);self.case.restored(self.invoke('recover'))

    def test_unsafe_or_missing_retained_manifest_is_not_reconstructed(self):
        self.begin();self.stop_workers();before=self.case.active()
        path=self.root/'retained.state';raw=path.read_bytes()
        path.chmod(0o644)
        self.assertEqual(self.invoke('recover')['error'],'unsafe_transaction_file')
        self.assertEqual(self.case.active(),before)
        path.unlink()
        self.assertEqual(self.invoke('recover')['error'],'unsafe_transaction_file')
        self.assertFalse(path.exists());self.assertEqual(self.case.active(),before)
        path.write_bytes(raw);path.chmod(0o600);self.case.restored(self.invoke('recover'))

    def test_boot_reconciliation_restores_pending_before_consumer_checks(self):
        self.begin();self.assertNotEqual(self.case.active(),self.case.original)
        result=self.boot()
        self.assertEqual(result['status'],'SOURCE_BOOT_RECONCILIATION_CHECKED')
        self.assertEqual(result['phase'],'rolled_back')
        self.assertEqual(self.case.active(),self.case.original)
        self.assertFalse(result['production_activation_allowed'])
        self.assertFalse(result['live_startup_hooks_installed'])

    def test_boot_reconciliation_preserves_explicit_confirmation(self):
        token=self.begin();self.invoke('confirm',token=token);after=self.case.active()
        # Separate synthetic evidence models a matching persistent source.
        # Actual transaction persistence does not write that environment.
        path=self.root/'source-evidence.json';evidence=json.loads(path.read_text())
        evidence['environment']['lct_vlan']={'state':'value','value':'123'}
        path.write_text(json.dumps(evidence))
        result=self.boot()
        self.assertEqual(result['status'],'SOURCE_BOOT_RECONCILIATION_CHECKED')
        self.assertEqual(result['phase'],'confirmed')
        self.assertEqual(after,self.case.active())

    def test_boot_gate_detects_later_native_uci_regeneration(self):
        self.begin()
        result=self.boot(fault='consumer_write')
        self.assertEqual(result['error'],'boot_recovery_content_changed')
        self.assertEqual(self.case.phase(),'rolled_back')
        self.assertNotEqual(self.case.active(),self.case.original)
        # A later native writer is not silently overwritten. Startup must stop
        # and report the precedence problem instead of claiming recovered state.
        self.assertEqual(self.invoke('recover')['error'],'transaction_unknown_active_content')

    def test_boot_gate_refuses_out_of_order_consumers_and_reused_handle(self):
        self.begin()
        result=self.boot(fault='wrong_order')
        self.assertEqual(result['error'],'boot_recovery_order_invalid')
        self.assertEqual(self.case.active(),self.case.original)
        result=self.boot(fault='repeat_final')
        self.assertEqual(result['error'],'boot_recovery_order_invalid')

    def test_boot_identity_change_invalidates_gate(self):
        self.begin()
        result=self.boot(fault='boot_changed')
        self.assertEqual(result['error'],'boot_identity_changed')
        self.assertEqual(self.case.active(),self.case.original)

    def test_boot_gate_no_transaction_and_no_orphan_is_readonly(self):
        before=self.case.active();result=self.boot()
        self.assertEqual(result['status'],'SOURCE_BOOT_RECONCILIATION_CHECKED')
        self.assertEqual(result['phase'],'unarmed');self.assertEqual(before,self.case.active())
        self.assertFalse((self.root/'transaction.state').exists())

    def test_boot_gate_blocks_orphan_partial_preparation(self):
        for filename in ('previous.network','candidate.firewall.new','retained.state.new'):
            with self.subTest(filename=filename):
                path=self.root/filename;path.write_bytes(b'PRIVATE_ORPHAN');path.chmod(0o600)
                result=self.boot()
                self.assertEqual(result['error'],'boot_recovery_incomplete_preparation')
                self.assertEqual(self.case.active(),self.case.original)
                self.assertEqual(path.read_bytes(),b'PRIVATE_ORPHAN');path.unlink()

    def test_boot_gate_does_not_claim_recovery_of_invalid_backups(self):
        self.begin();self.stop_workers();before=self.case.active()
        (self.root/'previous.firewall').write_bytes(b'CORRUPTED')
        result=self.boot()
        self.assertEqual(result['error'],'boot_recovery_unverified')
        self.assertEqual(before,self.case.active())
        self.assertEqual(self.case.phase(),'pending')


if __name__=='__main__':unittest.main()
