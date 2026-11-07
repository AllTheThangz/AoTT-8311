"""Read-only native-utility qualification and wrapper compatibility evidence.
A passing harness test is NOT a passing native backend qualification. That
separate report retains crashes/fallbacks and never authorizes a device write.
"""
import hashlib
import importlib.util
import inspect
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import tempfile
import unittest
from unittest import mock

ROOT=Path(__file__).resolve().parents[1]
VENDOR=Path(os.environ.get('AOTT_VENDOR_ROOTFS','/missing-private-rootfs'))
SPEC=importlib.util.spec_from_file_location('qualify_vendor_env_reader',ROOT/'tools/qualify_vendor_env_reader.py')
probe=importlib.util.module_from_spec(SPEC);SPEC.loader.exec_module(probe)


class ReadQualificationPolicyTests(unittest.TestCase):
    def test_generated_single_and_redundant_crc_images_are_bounded(self):
        for redundant in (False,True):
            for flag in (0,1):
                raw=probe.image(redundant,flag)
                self.assertTrue(probe.verify_image(raw,redundant))
                self.assertEqual(len(raw),16384)
                altered=raw[:8]+bytes([raw[8]^1])+raw[9:]
                self.assertFalse(probe.verify_image(altered,redundant))
                self.assertFalse(probe.verify_image(raw[:-1],redundant))

    def test_empty_and_unset_reader_output_are_not_interchangeable(self):
        expect={'one':'','two':'value'}
        self.assertEqual(probe.classify(0,'one=\ntwo=value\n','',expect),'SYNTHETIC_READER_PASS')
        self.assertEqual(probe.classify(0,'two=value\n','',expect),'NATIVE_READER_CONTENT_MISMATCH')
        self.assertEqual(probe.classify(0,'one=\ntwo=value','',expect),'NATIVE_READER_CONTENT_MISMATCH')

    def test_zero_exit_with_crc_fallback_warning_is_refused(self):
        state=probe.classify(0,'one=x\n','Warning: Bad CRC, using default environment',{'one':'x'})
        self.assertEqual(state,'NATIVE_READER_DIAGNOSTIC_OUTPUT')

    def test_nonzero_signal_duplicate_and_unknown_output_fail_closed(self):
        self.assertEqual(probe.classify(-11,'','',{}),'NATIVE_READER_SIGNAL_11')
        self.assertEqual(probe.classify(-7,'','',{}),'NATIVE_READER_SIGNAL_7')
        self.assertEqual(probe.classify(1,'key=value\n','',{'key':'value'}),'NATIVE_READER_FAILED')
        self.assertEqual(probe.classify(0,'key=x\nkey=x\n','',{'key':'x'}),'NATIVE_READER_INVALID_OUTPUT')
        self.assertEqual(probe.classify(0,'PRIVATE_FAILURE\n','',{}),'NATIVE_READER_INVALID_OUTPUT')
        self.assertEqual(probe.classify(0,'unknown=x\n','',{}),'NATIVE_READER_CONTENT_MISMATCH')

    def test_private_regular_file_guard_rejects_symlink_hardlink_and_mode(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);p=root/'image';p.write_bytes(b'fixture');p.chmod(0o600)
            probe.regular_private(p,7)
            link=root/'link';link.symlink_to(p)
            with self.assertRaises(ValueError):probe.regular_private(link,7)
            link.unlink();os.link(p,link)
            with self.assertRaises(ValueError):probe.regular_private(p,7)
            link.unlink();p.chmod(0o644)
            with self.assertRaises(ValueError):probe.regular_private(p,7)

    def test_qualification_never_escalates_from_read_failure_to_write(self):
        with tempfile.TemporaryDirectory() as directory:
            vendor=Path(directory);binary=vendor/'usr/sbin/fw_printenv'
            binary.parent.mkdir(parents=True);binary.write_bytes(b'\x7fELFprivate-fake-fixture')
            calls=[]
            def controlled(v,q,w,args,trace=False):
                calls.append((args,trace))
                return {'exit_code':-11,'stdout':'','stderr':'synthetic crash',
                        'stdout_sha256':probe.sha(b''),'stderr_sha256':probe.sha(b'synthetic crash'),'timed_out':False}
            with mock.patch.object(probe.shutil,'which',return_value='/usr/bin/qemu-mips-static'),mock.patch.object(probe,'native',side_effect=controlled):
                report=probe.qualify(vendor)
            self.assertEqual(report['status'],'BLOCKED_NATIVE_ENVIRONMENT_READER')
            self.assertEqual(report['native_setter_invocations'],0)
            self.assertFalse(report['production_activation_allowed'])
            self.assertFalse(report['physical_device_tested'])
            self.assertEqual(len(report['cases']),4)
            for args,traced in calls:
                self.assertNotIn('fw_setenv',' '.join(args))
                self.assertNotIn('/dev/',' '.join(args))
                if args not in (['--help'],['--version']):
                    self.assertEqual(args[0],'-c');self.assertEqual(args[2],'-l');self.assertEqual(args[3],'locks')
            self.assertEqual(binary.read_bytes(),b'\x7fELFprivate-fake-fixture')

    def test_unsafe_long_lock_path_is_refused_before_native_execution(self):
        with tempfile.TemporaryDirectory(prefix='aott-lock-argument-') as directory:
            work=Path(directory);(work/'locks').mkdir(mode=0o700)
            with mock.patch.object(probe.subprocess,'run') as command:
                with self.assertRaises(ValueError):
                    probe.native(work,'qemu-mips-static',work,
                        ['-c',str(work/'fw_env.config'),'-l',str(work/'locks')])
                command.assert_not_called()

    @unittest.skipUnless(os.environ.get('AOTT_VENDOR_ROOTFS'),'Private vendor image required')
    def test_actual_native_reader_passes_with_safe_private_relative_lock(self):
        report=probe.qualify(VENDOR)
        self.assertEqual(report['status'],'SYNTHETIC_READ_PROBE_PASSED')
        self.assertTrue(report['reader_qualified_for_synthetic_backend'])
        self.assertEqual(report['lock_argument'],'locks')
        self.assertEqual(len(report['cases']),4)
        for case in report['cases']:
            self.assertEqual(case['status'],'SYNTHETIC_READER_PASS')
            self.assertTrue(case['input_images_unchanged'])
        self.assertEqual(report['native_setter_invocations'],0)
        self.assertFalse(report['physical_device_tested'])
        self.assertFalse(report['production_activation_allowed'])

    def test_no_physical_device_or_write_mode_is_exposed_by_cli(self):
        source=(ROOT/'tools/qualify_vendor_env_reader.py').read_text()
        # Hashing a wrapper is not invoking it. The only execution helper
        # remains hard-coded to the reader, never the setter or a CLI command.
        execution=inspect.getsource(probe.native)
        self.assertNotIn('fw_setenv',execution)
        self.assertNotIn('fwenv_set',execution)
        self.assertIn('usr/sbin/fw_printenv',execution)
        self.assertIn('resource.RLIMIT_CORE,(0,0)',source)
        self.assertNotIn('shell=True',source)


class OperatorBaselineTests(unittest.TestCase):
    def test_shell_syntax_and_wrong_architecture_refusal(self):
        script=ROOT/'tools/collect_onu_env_baseline.sh'
        result=subprocess.run(['/bin/sh','-n',str(script)],capture_output=True,text=True,timeout=5)
        self.assertEqual(result.returncode,0,result.stderr)
        arch=subprocess.check_output(['uname','-m'],text=True).strip()
        if arch.startswith('mips'):self.skipTest('Wrong-host refusal test requires non-MIPS host')
        result=subprocess.run(['/bin/sh',str(script)],capture_output=True,text=True,timeout=5)
        self.assertEqual(result.returncode,2)
        self.assertIn('run on the MIPS ONU itself, not Hermes',result.stdout)
        self.assertNotIn('native_reader_exit=',result.stdout)

    def test_only_one_scoped_read_and_no_raw_output_or_device_write(self):
        text=(ROOT/'tools/collect_onu_env_baseline.sh').read_text()
        self.assertEqual(text.count('/usr/sbin/fw_printenv -n -- 8311_lct_vlan'),1)
        executable='\n'.join(line for line in text.splitlines() if not line.lstrip().startswith('#'))
        for operation in ('fwenv_set --','fw_setenv --','mtd write','ubiupdatevol','ifup ','service ','reboot','rm '):
            self.assertNotIn(operation,executable)
        self.assertNotIn('printf "%s" "$observed"',text)
        self.assertIn('native_reader_output=empty_or_diagnostic_not_exported',text)
        self.assertIn('/usr/bin/timeout -k 1 5',text)


class NativeShellWrapperCompatibilityTests(unittest.TestCase):
    def setUp(self):
        if not os.environ.get('AOTT_VENDOR_ROOTFS') or not shutil.which('qemu-mips-static'):
            self.skipTest('Extracted vendor shell required')
        self.temp=tempfile.TemporaryDirectory(prefix='aott-env-wrapper-test-',dir='/var/tmp')
        self.root=Path(self.temp.name);self.root.chmod(0o700)
        (self.root/'bin').mkdir(mode=0o700);(self.root/'lib').mkdir(mode=0o700)
        lock=(VENDOR/'lib/8311-env-lock.sh').read_text()
        self.assertEqual(lock.count('/tmp/8311-environment.lock'),1)
        lock=lock.replace('/tmp/8311-environment.lock',str(self.root/'environment.lock'))
        (self.root/'lib/8311-env-lock.sh').write_text(lock)
        self.state=self.root/'synthetic.json';self.state.write_text('{}');self.state.chmod(0o600)
        self.log=self.root/'calls.jsonl'
        self.stub='''#!/usr/bin/python3
import json,os,sys
from pathlib import Path
root=Path(os.environ['AOTT_ENV_WRAPPER_FIXTURE'])
p=root/'synthetic.json';values=json.loads(p.read_text());args=sys.argv[1:]
name=Path(sys.argv[0]).name
with (root/'calls.jsonl').open('a') as log:log.write(json.dumps({'tool':name,'args':args})+'\\n')
if name=='fw_printenv':
 if os.environ.get('AOTT_FIXTURE_UNREADABLE')=='1':sys.exit(9)
 if args[:2]==['-n','--']:
  if args[2] not in values:sys.exit(1)
  print(values[args[2]]);sys.exit(0)
 if args:sys.exit(64)
 for key in sorted(values):print(key+'='+values[key])
else:
 if args[:1]!=['--'] or len(args) not in (2,3):sys.exit(64)
 count=sum(1 for line in (root/'calls.jsonl').read_text().splitlines() if json.loads(line)['tool']=='fw_setenv')
 if str(count)==os.environ.get('AOTT_FIXTURE_FAIL_WRITE'):sys.exit(9)
 if len(args)==2:values.pop(args[1],None)
 else:values[args[1]]=args[2]
 p.write_text(json.dumps(values,sort_keys=True))
'''
        for name in ('fw_printenv','fw_setenv'):
            p=self.root/'bin'/name;p.write_text(self.stub);p.chmod(0o700)
        self.source_hashes={name:hashlib.sha256((VENDOR/'usr/sbin'/name).read_bytes()).hexdigest()
                            for name in ('fwenv_get','fwenv_set')}

    def tearDown(self):
        for name,sha in self.source_hashes.items():self.assertEqual(hashlib.sha256((VENDOR/'usr/sbin'/name).read_bytes()).hexdigest(),sha)
        self.temp.cleanup()

    def call(self,tool,args,extra=None):
        env={'PATH':str(self.root/'bin')+':/usr/bin:/bin','LANG':'C','HOME':str(self.root),
             'MAINT_LIBDIR':str(self.root/'lib'),'AOTT_ENV_WRAPPER_FIXTURE':str(self.root)}
        env.update(extra or {})
        return subprocess.run(['qemu-mips-static','-L',str(VENDOR),str(VENDOR/'bin/busybox'),'sh',
             str(VENDOR/'usr/sbin'/tool),*args],cwd=self.root,env=env,capture_output=True,text=True,timeout=8)

    def test_getter_returns_same_default_and_status_for_missing_and_empty(self):
        self.state.write_text('{}')
        missing=self.call('fwenv_get',['--8311','lct_vlan','0'])
        self.state.write_text(json.dumps({'8311_lct_vlan':''}))
        empty=self.call('fwenv_get',['--8311','lct_vlan','0'])
        self.assertEqual((missing.returncode,missing.stdout,missing.stderr),(1,'0\n',''))
        self.assertEqual((empty.returncode,empty.stdout,empty.stderr),(1,'0\n',''))
        self.assertEqual(json.loads(self.state.read_text()),{'8311_lct_vlan':''})

    def test_nonempty_getter_remains_literal_and_read_only(self):
        self.state.write_text(json.dumps({'8311_lct_vlan':'123','unrelated':'fixture'}))
        before=self.state.read_bytes();r=self.call('fwenv_get',['--8311','lct_vlan','0'])
        self.assertEqual((r.returncode,r.stdout,r.stderr),(0,'123\n',''))
        self.assertEqual(self.state.read_bytes(),before)
        self.assertTrue(all(json.loads(line)['tool']=='fw_printenv' for line in self.log.read_text().splitlines()))

    def test_empty_setter_issues_two_deletions_not_present_empty_storage(self):
        self.state.write_text(json.dumps({'8311_lct_vlan':'123','unrelated':'fixture'}))
        r=self.call('fwenv_set',['--8311','lct_vlan',''])
        self.assertEqual((r.returncode,r.stdout,r.stderr),(0,'',''))
        writes=[json.loads(line) for line in self.log.read_text().splitlines() if json.loads(line)['tool']=='fw_setenv']
        self.assertEqual([x['args'] for x in writes],[['--','8311_lct_vlan'],['--','8311_lct_vlan']])
        self.assertEqual(json.loads(self.state.read_text()),{'unrelated':'fixture'})

    def test_second_write_failure_is_not_reported_as_rollback_or_success(self):
        self.state.write_text(json.dumps({'8311_lct_vlan':'0','unrelated':'fixture'}))
        r=self.call('fwenv_set',['--8311','lct_vlan','123'],{'AOTT_FIXTURE_FAIL_WRITE':'2'})
        self.assertEqual(r.returncode,9)
        self.assertEqual(json.loads(self.state.read_text()),{'8311_lct_vlan':'123','unrelated':'fixture'})
        # This only characterizes wrapper control flow. The stub is not a
        # physical redundant environment and cannot prove flash durability.
        self.assertEqual(sum(json.loads(line)['tool']=='fw_setenv' for line in self.log.read_text().splitlines()),2)

    def test_unreadable_backend_is_not_reported_as_a_missing_key(self):
        r=self.call('fwenv_get',['--8311','lct_vlan','0'],{'AOTT_FIXTURE_UNREADABLE':'1'})
        self.assertEqual(r.returncode,74);self.assertEqual(r.stdout,'')


if __name__=='__main__':unittest.main()
