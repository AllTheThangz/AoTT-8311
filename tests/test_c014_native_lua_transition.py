"""C-014 portable Lua core and true MIPS Lua -> native UCI execution.
Python orchestrates tests only; transition planning/execution runs in Lua.
"""
import copy
import json
import os
from pathlib import Path
import secrets
import shutil
import subprocess
import unittest

import test_c014_native_uci_candidate as reference

ROOT=Path(__file__).resolve().parents[1]
MODULE=ROOT/"prototypes/configuration/8311/vlan_transition.lua"
FIXTURE=ROOT/"tests/c014_native_lua_fixture.lua"
VENDOR=reference.VENDOR


def lua(value):
    if value is None:
        return "nil"
    if isinstance(value,bool):
        return "true" if value else "false"
    if isinstance(value,str):
        return json.dumps(value,ensure_ascii=True)
    if isinstance(value,(int,float)):
        return repr(value)
    if isinstance(value,list):
        return "{"+",".join(lua(v) for v in value)+"}"
    if isinstance(value,dict):
        return "{"+",".join("["+lua(k)+"]="+lua(v) for k,v in value.items())+"}"
    raise TypeError("Unqualified synthetic fixture value")


class PortableLuaTransitionTests(unittest.TestCase):
    def run_lua(self,body):
        if not shutil.which("lua5.1"):
            self.skipTest("Host Lua 5.1 missing")
        prelude='package.path=arg[1].."/prototypes/configuration/?.lua;"..package.path\n'
        prelude+='local m=require "8311.vlan_transition"\n'
        prelude+='''local function equal(a,b)
 if type(a)~=type(b) then return false end
 if type(a)~="table" then return a==b end
 for k,v in pairs(a) do if not equal(v,b[k]) then return false end end
 for k in pairs(b) do if a[k]==nil then return false end end
 return true
end
'''
        p=subprocess.run(["lua5.1","-",str(ROOT)],input=prelude+body+
            '\nprint("AOTT_C014_PORTABLE_LUA_PASS")\n',capture_output=True,text=True,timeout=8)
        self.assertEqual(p.returncode,0,p.stderr)
        self.assertIn("AOTT_C014_PORTABLE_LUA_PASS",p.stdout)

    def test_lua51_syntax(self):
        for path in (MODULE,FIXTURE):
            result=subprocess.run(["luac5.1","-p",str(path)],capture_output=True,text=True,timeout=8)
            self.assertEqual(result.returncode,0,result.stderr)

    def test_portable_plan_matches_python_reference(self):
        initial=reference.state()
        tagged=reference.plan(initial,123)["after"]
        cases=[(initial,0),(initial,123),(tagged,123),(tagged,456),(tagged,0)]
        scalar=copy.deepcopy(initial)
        scalar["firewall"]["@zone[1]"]["options"]["network"]="lan lct"
        cases.extend([(scalar,123),(reference.plan(scalar,123)["after"],0)])
        absent=copy.deepcopy(initial)
        for key in ("gateway","dns"):
            del absent["network"]["lct"]["options"][key]
        cases.extend([(absent,123),(reference.plan(absent,123)["after"],0)])
        script=[]
        for snapshot,vlan in cases:
            expected=reference.plan(snapshot,vlan)
            expected={"after":expected["after"],"operations":[list(op) for op in expected["operations"]]}
            script.append('do local input='+lua(snapshot)+'\nlocal original='+lua(snapshot)+'\n'
                'local h,e=m.prepare(input,'+str(vlan)+',"eth0_0_1_lct","lan");assert(h,e)\n'
                'local output=m.fixture_projection(h,"offline_synthetic")\n'
                'assert(equal(output,'+lua(expected)+'),"reference_plan_disagreement")\n'
                'assert(equal(input,original),"caller_snapshot_mutated") end\n')
        self.run_lua("\n".join(script))

    def test_portable_refusal_matches_qualified_reference_cases(self):
        cases=[]
        for value in (None,True,"123",-1,4095,4096):
            cases.append((reference.state(),value))
        for name in ("mgmt","lct_vlan"):
            source=reference.state();source["network"][name]={"type":"interface","options":{"proto":"static"}}
            cases.append((source,0))
        source=reference.state();source["firewall"]["@zone[0]"]["options"]["network"].append("lct")
        cases.append((source,123))
        source=reference.state();source["network"]["lct"]["options"]["ip6assign"]="64"
        cases.append((source,123))
        source=reference.plan(reference.state(),123)["after"]
        source["network"]["external"]={"type":"route","options":{"interface":"mgmt"}}
        cases.append((source,0))
        script=[]
        for source,value in cases:
            with self.assertRaises(reference.VlanCandidateError):reference.plan(source,value)
            script.append('do local h,e=m.prepare('+lua(source)+','+lua(value)+',"eth0_0_1_lct","lan")\n'
                          'assert(h==nil and type(e)=="string","unsafe_state_accepted") end')
        self.run_lua("\n".join(script))

    def test_parser_matches_native_export_quoting(self):
        variants=["package fixture\nconfig interface 'lct'\n option label 'can'\\''t'\n",
            "package fixture\nconfig zone\n option name 'lan'\n list network 'lan'\n list network 'lct'\n",
            'package fixture\nconfig interface "quoted"\n option label "literal # comment text"\n',
            "package fixture\nconfig interface 'lct'\n option label '' # omitted comment\n"]
        script=[]
        for raw in variants:
            expected=reference.parse_export(raw,"fixture")
            script.append('do local value,e=m.parse_export('+lua(raw)+',"fixture");assert(value,e);'
                          'assert(equal(value,'+lua(expected)+'),"parser_disagreement") end')
        self.run_lua("\n".join(script))

    def test_double_quote_escapes_preserve_native_value_semantics(self):
        values=(r'"literal\path"', r'"dollar\$literal"', r'"quote\"inside"', r'"slash\\inside"')
        script=[]
        for value in values:
            raw="package fixture\nconfig interface lct\noption label "+value+"\n"
            expected=reference.parse_export(raw,"fixture")
            script.append('do local parsed,e=m.parse_export('+lua(raw)+',"fixture");assert(parsed,e);'
                          'assert(equal(parsed,'+lua(expected)+'),"escaped_value_changed") end')
        self.run_lua("\n".join(script))

    def test_error_metatable_is_not_evaluated_or_exposed(self):
        self.run_lua('local source='+lua(reference.state())+'''
local h=assert(m.prepare(source,0,"eth0_0_1_lct","lan"))
local touched=false
local adapter={disposable_fixture=true,
 snapshot=function() error(setmetatable({}, {__index=function()touched=true;error("PRIVATE",0)end}),0) end,
 persisted_snapshot=function()return source end,command=function()error("should_not_execute")end}
local r,e=m.verify_staged(h,adapter,"offline_synthetic")
assert(r==nil and e=="candidate_internal_error" and touched==false)
''')

    def test_parser_rejects_duplicates_malformed_and_excess_input(self):
        invalid=["", "package other\n", "package fixture\nconfig interface 'unterminated\n",
            "package fixture\nconfig interface lct\noption proto static\noption proto dhcp\n",
            "package fixture\nconfig interface lct\noption dns value\nlist dns other\n",
            "package fixture\nconfig interface lct\n"+"list dns x\n"*65,
            "x"*65537]
        self.run_lua("\n".join('do local value,e=m.parse_export('+lua(raw)+',"fixture");'
            'assert(value==nil and type(e)=="string","malformed_export_accepted") end' for raw in invalid))

    def test_invalid_typed_snapshots_and_metatables_fail_closed(self):
        source=lua(reference.state())
        self.run_lua('''local variants={
 function(s) s.network.lct.options.proto=true end,
 function(s) s.network.lct.options.dns={[1]="a",[3]="b"} end,
 function(s) s.network.lct.options.dns=s end,
 function(s) setmetatable(s.network.lct,{}) end,
 function(s) s.network.lct.options.ipaddr="SYNTHETIC_SECRET" end}
for _,mutate in ipairs(variants) do
 local s='''+source+'''
 mutate(s)
 local handle,why=m.prepare(s,123,"eth0_0_1_lct","lan")
 assert(handle==nil and type(why)=="string")
 assert(not why:find("SYNTHETIC_SECRET",1,true))
end
''')

    def test_plan_handles_are_private_and_adapter_errors_redacted(self):
        self.run_lua('local source='+lua(reference.state())+'''
local h=assert(m.prepare(source,0,"eth0_0_1_lct","lan"))
local projected=assert(m.fixture_projection(h,"offline_synthetic"))
projected.after.network.lct=nil
h.operations={{"delete","network.lct"}}
local count=0
local adapter={disposable_fixture=true,snapshot=function()return source end,
 persisted_snapshot=function()return source end,command=function()count=count+1;return true end}
local r,e=m.verify_staged(h,adapter,"offline_synthetic");assert(r,e)
assert(count==0 and r.contains_configuration_values==false)
adapter.snapshot=function() error("syntheticsecret",0) end
r,e=m.verify_staged(h,adapter,"offline_synthetic")
assert(r==nil and e=="candidate_internal_error")
r,e=m.verify_staged({},adapter,"offline_synthetic");assert(r==nil and e=="invalid_plan_handle")
r,e=m.verify_staged(h,adapter,"production");assert(r==nil and e=="invalid_plan_handle")
''')

    def test_planner_remains_dependency_free_and_deployed_executor_is_adapter_scoped(self):
        text=MODULE.read_text()
        for item in ("io.open", "io.popen", "os.execute", "nixio", "luci.model.uci", "subprocess", "socket"):
            self.assertNotIn(item,text)
        deployed=ROOT/"overlay/usr/lib/lua/8311/vlan_transition.lua"
        self.assertTrue(deployed.is_file())
        runtime=deployed.read_text()
        for item in ("io.open", "io.popen", "os.execute", "nixio", "luci.model.uci", "subprocess", "socket"):
            self.assertNotIn(item,runtime)
        self.assertIn('function M.redacted_summary(handle,mode)',runtime)
        self.assertIn('mode~="offline_synthetic" and mode~="production_runtime"',runtime)
        self.assertIn('production and adapter.production_runtime~=true',runtime)
        self.assertIn('production_applied=production',runtime)
        self.assertIn('contains_configuration_values=false',runtime)


class NativeLuaExecutionTests(unittest.TestCase):
    def setUp(self):
        if (not os.environ.get("AOTT_VENDOR_ROOTFS") or os.geteuid()!=0 or
                not shutil.which("qemu-mips-static") or not (VENDOR/"sbin/uci").is_file()):
            self.skipTest("Extracted vendor MIPS environment and root-owned fixtures required")
        self.root=Path("/var/tmp/aott-c014-lua-test-"+secrets.token_hex(8))
        self.root.mkdir(mode=0o700)
        self.namespace="aott_c014_"+secrets.token_hex(8)
        for name in ("original","candidate","delta","cold"):
            (self.root/name).mkdir(mode=0o700)
        self.original={"network":reference.NETWORK.encode(),"firewall":reference.FIREWALL.encode()}
        for pkg,data in self.original.items():
            path=self.root/"original"/(self.namespace+"_"+pkg)
            path.write_bytes(data);path.chmod(0o600)
        self.reset()

    def tearDown(self):
        try:
            for pkg,data in self.original.items():
                self.assertEqual((self.root/"original"/(self.namespace+"_"+pkg)).read_bytes(),data)
        finally:shutil.rmtree(self.root)

    def reset(self,network=None,firewall=None):
        for name in ("candidate","delta","cold"):
            for path in (self.root/name).iterdir():
                self.assertFalse(path.is_symlink());self.assertTrue(path.is_file());path.unlink()
        for pkg,data in {"network":network or self.original["network"],
                         "firewall":firewall or self.original["firewall"]}.items():
            path=self.root/"candidate"/(self.namespace+"_"+pkg)
            path.write_bytes(data);path.chmod(0o600)

    def command(self,action,target=123,fail_at=0,inverse=False):
        return ["qemu-mips-static","-L",str(VENDOR),str(VENDOR/"usr/bin/lua"),
            str(FIXTURE),str(VENDOR),str(ROOT),str(self.root),self.namespace,action,
            str(target),str(fail_at),"inverse" if inverse else "forward"]

    def invoke(self,action,**kw):
        result=subprocess.run(self.command(action,**kw),cwd=ROOT,capture_output=True,text=True,timeout=40)
        self.assertEqual(result.returncode,0,result.stderr)
        return result.stdout

    def test_mips_lua_plan_matches_python_reference_and_actual_native_exports(self):
        output=json.loads(self.invoke("plan"))
        expected=reference.plan(reference.state(),123)
        self.assertEqual(output["after"],expected["after"])
        self.assertEqual(output["operations"],[list(x) for x in expected["operations"]])

    def test_real_native_lua_roundtrip_and_repeat_without_writes(self):
        self.assertIn("AOTT_C014_NATIVE_LUA_PASS action=roundtrip",self.invoke("roundtrip"))

    def test_noop_does_not_commit_any_package(self):
        before={p.name:p.read_bytes() for p in (self.root/"candidate").iterdir()}
        self.assertIn("native_mutations=0",self.invoke("no_op",target=0))
        self.assertEqual(before,{p.name:p.read_bytes() for p in (self.root/"candidate").iterdir()})

    def test_all_forward_mutation_and_commit_failures_stop(self):
        count=len(reference.plan(reference.state(),123)["operations"])+2
        for step in range(1,count+1):
            with self.subTest(step=step):
                self.reset()
                self.assertIn("AOTT_C014_NATIVE_LUA_FAILURE_PASS",self.invoke("failure",fail_at=step))

    def test_all_inverse_mutation_and_commit_failures_stop(self):
        tagged=reference.plan(reference.state(),123)["after"]
        count=len(reference.plan(tagged,0)["operations"])+2
        for step in range(1,count+1):
            with self.subTest(step=step):
                self.reset()
                self.assertIn("AOTT_C014_NATIVE_LUA_FAILURE_PASS",
                              self.invoke("failure",fail_at=step,inverse=True))

    def test_stale_candidate_has_no_additional_mutations(self):
        self.assertIn("action=stale",self.invoke("stale"))

    def test_private_plan_not_modified_through_projected_copy(self):
        self.assertIn("action=plan_tamper",self.invoke("plan_tamper"))

    def test_cold_readback_mismatch_refused(self):
        self.assertIn("action=bad_readback",self.invoke("bad_readback"))

    def test_adapter_exception_does_not_leak(self):
        output=self.invoke("exception")
        self.assertIn("action=exception",output)
        self.assertNotIn("syntheticsecret",output)

    def test_no_production_mode_or_forged_plan(self):
        self.assertIn("native_mutations=0",self.invoke("guard"))

    def test_scalar_zone_and_absent_route_dns_are_preserved(self):
        firewall=reference.FIREWALL.replace(" list network 'lan'\n list network 'lct'",
                                           " option network 'lan lct'").encode()
        network="\n".join(line for line in reference.NETWORK.splitlines()
                          if "option gateway" not in line and "list dns" not in line)+"\n"
        self.reset(network.encode(),firewall)
        self.assertIn("action=roundtrip",self.invoke("roundtrip"))

    def test_literal_quotes_backslashes_and_metacharacters_preserved(self):
        value="literal'quote\\path#${NOT_EXPANDED}"
        quoted="'"+value.replace("'", "'\\''")+"'"
        network=reference.NETWORK.replace("'resolver.example.invalid'",quoted).encode()
        self.reset(network=network)
        self.assertIn("action=roundtrip",self.invoke("roundtrip"))

    def test_unsafe_candidate_file_rejected_before_native_commands(self):
        path=self.root/"candidate"/(self.namespace+"_network")
        path.chmod(0o644)
        result=subprocess.run(self.command("roundtrip"),capture_output=True,text=True,timeout=10)
        self.assertNotEqual(result.returncode,0)
        self.assertIn("unsafe_fixture_file",result.stderr)
        self.assertEqual(list((self.root/"delta").iterdir()),[])


if __name__=="__main__":
    unittest.main()
