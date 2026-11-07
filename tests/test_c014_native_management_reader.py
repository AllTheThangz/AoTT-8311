"""Lossless scoped reads using the real vendor reader and strict parser.
Native tests use only generated private regular files and a short lock path.
"""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import resource
import shutil
import struct
import subprocess
import tempfile
import unittest
import zlib

import test_c014_native_lua_transition as portable
from test_c014_native_uci_candidate import MAC as FIXTURE_MAC

ROOT=Path(__file__).resolve().parents[1]
VENDOR=Path(os.environ.get('AOTT_VENDOR_ROOTFS','/missing-private-rootfs'))
MODULE=ROOT/'prototypes/configuration/8311/native_management_reader.lua'
KEYS=('ipaddr','netmask','gateway','dns_server','lct_mac','lct_vlan')
VALUES={'8311_ipaddr':'192.0.2.10','8311_netmask':'255.255.255.0','8311_gateway':'',
        '8311_dns_server':'192.0.2.20','8311_lct_mac':FIXTURE_MAC,'8311_lct_vlan':'123'}


def image(values,flag=1,valid=True):
    raw=b'\0'.join((k+'='+v).encode()for k,v in values.items())+b'\0\0'
    raw+=bytes(16384-5-len(raw))
    crc=zlib.crc32(raw)&0xffffffff
    return struct.pack('>I',crc if valid else crc^1)+bytes([flag])+raw


def output(values):
    lines=[]
    for key in KEYS:
        name='8311_'+key
        lines.append(name+'='+values[name] if name in values else '## Error: "'+name+'" not defined')
    return '\n'.join(lines)+'\n'


class ScopedParserTests(unittest.TestCase):
    def lua(self,body):
        if not shutil.which('lua5.1'):self.skipTest('Host Lua 5.1 missing')
        pre='package.path=arg[1].."/prototypes/configuration/?.lua;"..package.path\nlocal m=require "8311.native_management_reader"\n'
        r=subprocess.run(['lua5.1','-',str(ROOT)],input=pre+body+'\nprint("SCOPED_PARSER_PASS")\n',capture_output=True,text=True,timeout=8)
        self.assertEqual(r.returncode,0,r.stderr)
        self.assertIn('SCOPED_PARSER_PASS',r.stdout)

    def test_syntax_and_not_deployed(self):
        r=subprocess.run(['luac5.1','-p',str(MODULE)],capture_output=True,text=True,timeout=8)
        self.assertEqual(r.returncode,0,r.stderr)
        self.assertIn(MODULE.name,(ROOT/'MANIFEST.json').read_text())
        deployed=ROOT/'overlay/usr/lib/lua/8311'/MODULE.name
        self.assertTrue(deployed.is_file())
        self.assertNotIn('fw_setenv',deployed.read_text())
        self.assertIn('write_authorized=false',deployed.read_text())

    def test_empty_and_missing_have_distinct_states_without_defaulting(self):
        values=VALUES.copy();del values['8311_lct_vlan']
        self.lua('local h=assert(m.fixture_decode(1,'+portable.lua(output(values))+''',false,"offline_synthetic"))
local data=assert(m.records(h));assert(data.gateway.state=="value" and data.gateway.value=="")
assert(data.lct_vlan.state=="unset" and data.lct_vlan.value==nil)
local r=assert(m.summary(h));assert(r.present_empty==1 and r.unset==1 and r.present==5)
assert(r.wrapper_cannot_restore_present_empty and not r.write_authorized)
assert(r.states.gateway=="present_empty" and r.states.lct_vlan=="unset")
''')

    def test_all_missing_keys_require_exact_missing_diagnostics(self):
        self.lua('local h=assert(m.fixture_decode(1,'+portable.lua(output({}))+''',false,"offline_synthetic"))
local r=assert(m.summary(h));assert(r.unset==6 and r.present==0 and not r.write_authorized)
''')

    def test_named_records_may_arrive_in_any_complete_order(self):
        raw=output(VALUES);reverse='\n'.join(reversed(raw.splitlines()))+'\n'
        self.lua('local a=assert(m.fixture_decode(0,'+portable.lua(raw)+',false,"offline_synthetic"))\n'+
            'local b=assert(m.fixture_decode(0,'+portable.lua(reverse)+',false,"offline_synthetic"))\nassert(m.same(a,b))')

    def test_failures_warnings_overflow_and_exit_mismatch_are_not_success(self):
        raw=output(VALUES);cases=[(-11,raw,False),(124,raw,False),(1,raw,False),(0,raw,True),(0,raw,None),
            (0,raw+'Warning: Bad CRC, using default environment\n',False),(0,output({}),False)]
        script=''
        for code,data,over in cases:
            script+='do local h,e=m.fixture_decode('+str(code)+','+portable.lua(data)+','+portable.lua(over)+',"offline_synthetic");assert(h==nil and type(e)=="string")end\n'
        self.lua(script)

    def test_incomplete_duplicate_unknown_control_and_oversized_lines_refused(self):
        raw=output(VALUES)
        cases=[raw[:-1],raw.split('\n',1)[1],raw+raw.splitlines()[0]+'\n',raw+'baudrate=115200\n',
               raw.replace('123','PRIVATE\rDATA'),raw.replace('123','x'*129),raw+'\n',raw+'x'*4096]
        self.lua('\n'.join('do local h,e=m.fixture_decode(0,'+portable.lua(value)+',false,"offline_synthetic");assert(h==nil and not e:find("PRIVATE",1,true))end' for value in cases))

    def test_returned_records_and_summary_cannot_mutate_snapshot(self):
        raw=output(VALUES)
        self.lua('local a=assert(m.fixture_decode(0,'+portable.lua(raw)+''',false,"offline_synthetic"))
local records=assert(m.records(a));records.ipaddr.value="PRIVATE"
local r=assert(m.summary(a));r.write_authorized=true;r.states.ipaddr="unset"
assert(m.records(a).ipaddr.value~="PRIVATE" and not m.summary(a).write_authorized)
assert(m.summary(a).states.ipaddr=="present_value")
local b=assert(m.fixture_decode(0,'''+portable.lua(raw)+''',false,"offline_synthetic"));assert(m.same(a,b))
local h,e=m.records({});assert(h==nil and e=="invalid_native_management_snapshot")
h,e=m.fixture_decode(0,"",false,"production");assert(h==nil and e=="native_reader_fixture_mode_refused")
''')

    def test_empty_vs_missing_or_changed_value_fails_equality(self):
        values=VALUES.copy();del values['8311_gateway']
        self.lua('local a=assert(m.fixture_decode(0,'+portable.lua(output(VALUES))+',false,"offline_synthetic"))\n'+
            'local b=assert(m.fixture_decode(1,'+portable.lua(output(values))+',false,"offline_synthetic"))\nassert(m.same(a,b)==false)')

    def test_native_entry_has_fixed_scoped_command_and_redacts_exception(self):
        self.lua('''package.preload["8311.webutil"]=function()return {capture=function(argv,limit)
assert(#argv==12 and limit==4096)
assert(argv[1]=="/usr/bin/timeout" and argv[2]=="-k" and argv[3]=="1" and argv[4]=="5")
assert(argv[5]=="/usr/sbin/fw_printenv" and argv[6]=="--")
assert(argv[7]=="8311_ipaddr" and argv[12]=="8311_lct_vlan")
return 0,'''+portable.lua(output(VALUES))+''',false end}end
local h=assert(m.read());assert(m.summary(h).basis=="native_scoped_reader")
package.loaded["8311.webutil"].capture=function()error("PRIVATE_EXCEPTION")end
local value,e=m.read();assert(value==nil and e=="native_management_read_internal_error")
''')


class RealNativeScopedReadTests(unittest.TestCase):
    def setUp(self):
        if not os.environ.get('AOTT_VENDOR_ROOTFS') or not shutil.which('qemu-mips-static'):
            self.skipTest('Private native runtime required')
        self.temp=tempfile.TemporaryDirectory(prefix='aott-scoped-native-',dir='/var/tmp')
        self.root=Path(self.temp.name);self.root.chmod(0o700)
        (self.root/'locks').mkdir(mode=0o700)
        self.config=self.root/'fw_env.config';self.config.write_text('a 0x0 0x4000 0x4000 1\nb 0x0 0x4000 0x4000 1\n');self.config.chmod(0o600)
        self.values={**VALUES,'fixture_unrelated':'DO_NOT_EXPORT'}
        self.write_images()

    def tearDown(self):self.temp.cleanup()

    def write_images(self,valid=True):
        for name,flag in (('a',1),('b',0)):
            p=self.root/name;p.write_bytes(image(self.values,flag,valid));p.chmod(0o600)
        self.before={name:hashlib.sha256((self.root/name).read_bytes()).hexdigest()for name in ('a','b')}

    def read(self):
        # Run the production reader entry point under vendor Lua. Only its
        # process launcher is redirected to the identical vendor binary over
        # the generated private config; all decoding is actual module code.
        script='''local vendor,repo,cfg,work=arg[1],arg[2],arg[3],arg[4]
package.path=repo.."/prototypes/configuration/?.lua;"..repo.."/overlay/usr/lib/lua/?.lua;"..vendor.."/usr/lib/lua/?.lua;"..vendor.."/usr/lib/lua/?/init.lua;"..package.path
package.cpath=vendor.."/usr/lib/lua/?.so;"..package.cpath
local web=require "8311.webutil";local original=web.capture
web.capture=function(argv,limit)
 assert(#argv==12 and argv[5]=="/usr/sbin/fw_printenv" and argv[6]=="--" and limit==4096)
 -- LuCI deliberately changes child cwd to /. The fixture launcher must
 -- restore its own private cwd before using the short relative lock path.
 local replacement={"/usr/bin/timeout","-k","1","5","/usr/bin/env","-C",work,"/usr/bin/qemu-mips-static","-L",vendor,
  vendor.."/usr/sbin/fw_printenv","-c",cfg,"-l","locks","--"}
 for i=7,#argv do replacement[#replacement+1]=argv[i]end
 return original(replacement,limit)
end
local m=require "8311.native_management_reader"
local h,why=m.read();local result=h and {summary=m.summary(h),records=m.records(h)}or {error=why}
print(require('luci.jsonc').stringify(result))
'''
        def no_core():resource.setrlimit(resource.RLIMIT_CORE,(0,0))
        r=subprocess.run(['qemu-mips-static','-L',str(VENDOR),str(VENDOR/'usr/bin/lua'),'-',str(VENDOR),str(ROOT),str(self.config),str(self.root)],
            input=script,cwd=self.root,capture_output=True,text=True,timeout=10,preexec_fn=no_core)
        self.assertEqual(r.returncode,0,r.stderr)
        self.assertNotIn('DO_NOT_EXPORT',r.stdout+r.stderr)
        self.assertEqual(self.before,{n:hashlib.sha256((self.root/n).read_bytes()).hexdigest()for n in ('a','b')})
        self.assertTrue((self.root/'locks/fw_printenv.lock').is_file())
        return json.loads(r.stdout)

    def test_real_native_output_preserves_present_empty_and_absence(self):
        del self.values['8311_lct_vlan'];self.write_images()
        result=self.read();self.assertNotIn('error',result)
        self.assertEqual(result['records']['gateway'],{'state':'value','value':''})
        self.assertEqual(result['records']['lct_vlan'],{'state':'unset'})
        self.assertEqual(result['summary']['present_empty'],1)
        self.assertEqual(result['summary']['unset'],1)
        self.assertFalse(result['summary']['write_authorized'])

    def test_all_present_and_all_missing_work_without_full_environment_export(self):
        self.assertEqual(self.read()['summary']['present'],6)
        self.values={'fixture_unrelated':'DO_NOT_EXPORT'};self.write_images()
        result=self.read();self.assertNotIn('error',result)
        self.assertEqual(result['summary']['unset'],6)

    def test_bad_crc_fallback_cannot_masquerade_as_unset_snapshot(self):
        self.write_images(valid=False)
        result=self.read();self.assertIn('error',result)
        self.assertNotIn('records',result)

    def test_multi_line_value_cannot_inject_another_key(self):
        self.values['8311_gateway']='\n8311_lct_vlan=999';self.write_images()
        result=self.read();self.assertIn('error',result);self.assertNotIn('records',result)


if __name__=='__main__':unittest.main()
