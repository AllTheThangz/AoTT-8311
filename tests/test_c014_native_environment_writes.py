"""Actual vendor setter behavior on generated regular-file images only.
This supplies evidence for a future adapter, not a production write entry point.
No physical device, extracted default env config, or real cache is selected.
"""
import hashlib
import os
from pathlib import Path
import resource
import shutil
import stat
import subprocess
import tempfile
import unittest

from test_c014_native_management_reader import image,KEYS,VALUES,VENDOR


class NativeRegularFileMutationTests(unittest.TestCase):
    def setUp(self):
        if not os.environ.get('AOTT_VENDOR_ROOTFS') or not shutil.which('qemu-mips-static'):
            self.skipTest('Private vendor runtime required')
        self.tmp=tempfile.TemporaryDirectory(prefix='aott-native-write-fixture-',dir='/var/tmp')
        self.root=Path(self.tmp.name);self.root.chmod(0o700);(self.root/'locks').mkdir(mode=0o700)
        self.values={**VALUES,'unrelated_fixture':'PRESERVE_EXACTLY'}
        self.config=self.root/'fw_env.config'
        self.config_text='a 0x0 0x4000 0x4000 1\nb 0x0 0x4000 0x4000 1\n'
        self.config.write_text(self.config_text);self.config.chmod(0o600)
        self.setter_invocations=0;self.regenerate()

    def tearDown(self):self.tmp.cleanup()

    def regenerate(self):
        for name,flag in (('a',1),('b',0)):
            p=self.root/name;p.write_bytes(image(self.values,flag));p.chmod(0o600)

    def invoke(self,write=False,key=None,value=None,delete=False):
        # Do not expose a generic native flash utility through the fixture.
        if write and key not in {'8311_'+k for k in KEYS}:
            raise ValueError('Unqualified key; native command not invoked')
        if self.config.read_text()!=self.config_text:
            raise ValueError('Changed private fixture configuration')
        for name in ('a','b'):
            p=self.root/name
            if not p.exists():continue  # Native missing-file error is tested explicitly.
            st=p.lstat()
            if not stat.S_ISREG(st.st_mode) or st.st_nlink!=1 or st.st_uid!=os.geteuid() or st.st_size!=16384:
                raise ValueError('Non-private regular image refused')
        name='fw_setenv'if write else'fw_printenv'
        args=['qemu-mips-static','-L',str(VENDOR),'-0',name,str(VENDOR/'usr/sbin/fw_printenv'),
              '-c',str(self.config),'-l','locks']
        if write:
            args+=['--',key]
            if not delete:args.append(value)
            self.setter_invocations+=1
        def no_core():resource.setrlimit(resource.RLIMIT_CORE,(0,0))
        return subprocess.run(args,cwd=self.root,capture_output=True,text=True,timeout=8,preexec_fn=no_core)

    def read(self):
        r=self.invoke();self.assertEqual(r.returncode,0,r.stderr);self.assertEqual(r.stderr,'')
        return dict(line.split('=',1)for line in r.stdout.splitlines())

    def set_pair(self,key,value=None,delete=False):
        # Mirrors the existing wrapper's two sequential updates. A failure
        # here is not called atomic, durable, or automatically rolled back.
        for _ in range(2):
            r=self.invoke(True,key,value,delete)
            self.assertEqual(r.returncode,0,r.stderr);self.assertEqual(r.stderr,'')

    def test_actual_apply_and_restore_preserve_every_unrelated_entry(self):
        before=self.read()
        self.set_pair('8311_lct_vlan','321')
        self.assertEqual(self.read(),{**before,'8311_lct_vlan':'321'})
        self.set_pair('8311_lct_vlan',before['8311_lct_vlan'])
        self.assertEqual(self.read(),before)
        self.assertEqual(self.setter_invocations,4)

    def test_absent_override_is_restored_by_deletion_not_empty_default(self):
        del self.values['8311_lct_vlan'];self.regenerate();before=self.read()
        self.set_pair('8311_lct_vlan','123');self.assertEqual(self.read(),{**before,'8311_lct_vlan':'123'})
        self.set_pair('8311_lct_vlan',delete=True);self.assertEqual(self.read(),before)
        self.assertNotIn('8311_lct_vlan',self.read())

    def test_native_empty_argument_deletes_present_empty_key(self):
        before=self.read();self.assertIn('8311_gateway',before);self.assertEqual(before['8311_gateway'],'')
        self.set_pair('8311_gateway','')
        expected=before.copy();expected.pop('8311_gateway')
        self.assertEqual(self.read(),expected)
        # Empty value cannot be round-tripped by this setter argument.
        self.set_pair('8311_gateway','');self.assertEqual(self.read(),expected)

    def test_after_first_redundant_write_new_process_can_read_and_restore(self):
        before=self.read()
        r=self.invoke(True,'8311_lct_vlan','321');self.assertEqual(r.returncode,0,r.stderr)
        self.assertEqual(self.read(),{**before,'8311_lct_vlan':'321'})
        self.set_pair('8311_lct_vlan',before['8311_lct_vlan'])
        self.assertEqual(self.read(),before)
        # This is process separation after a completed write, not a simulated
        # power cut in NAND erase/program or proof of physical atomicity.

    def test_missing_second_image_failure_does_not_modify_first_image(self):
        before=hashlib.sha256((self.root/'a').read_bytes()).hexdigest()
        (self.root/'b').unlink()
        r=self.invoke(True,'8311_lct_vlan','321')
        self.assertNotEqual(r.returncode,0)
        self.assertEqual(hashlib.sha256((self.root/'a').read_bytes()).hexdigest(),before)
        self.assertFalse((self.root/'b').exists())

    def test_unknown_key_and_changed_config_rejected_before_execution(self):
        with self.assertRaises(ValueError):self.invoke(True,'boot_part','1')
        self.assertEqual(self.setter_invocations,0)
        self.config.write_text('INVALID_CONFIGURATION\n')
        with self.assertRaises(ValueError):self.invoke(True,'8311_lct_vlan','321')
        self.assertEqual(self.setter_invocations,0)


if __name__=='__main__':unittest.main()
