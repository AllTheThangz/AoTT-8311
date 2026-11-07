-- Native-MIPS C-014 executor fixture. All packages and paths synthetic.
local vendor=assert(arg[1]);local repo=assert(arg[2]);local directory=assert(arg[3])
local namespace=assert(arg[4]);local action=assert(arg[5]);local target=tonumber(arg[6]) or 123
local fail_at=tonumber(arg[7]);local inverse=arg[8]=="inverse"
package.path=repo.."/prototypes/configuration/?.lua;"..repo.."/overlay/usr/lib/lua/?.lua;"..
    vendor.."/usr/lib/lua/?.lua;"..vendor.."/usr/lib/lua/?/init.lua;"..package.path
package.cpath=vendor.."/usr/lib/lua/?.so;"..package.cpath
local model=require "8311.vlan_transition"
local web=require "8311.webutil"
local json=require "luci.jsonc"
local fs=require "nixio.fs"
local checks=0
local function eq(a,b,label) checks=checks+1;assert(a==b,"C014_LUA_FIXTURE:"..label) end
local function need(v,why) assert(v,why or "C014_LUA_FIXTURE:failed");return v end
local function sorted(t) local r={};for k in pairs(t) do r[#r+1]=k end;table.sort(r);return r end
local function encode(v)
    if type(v)~="table" then return type(v)..":"..tostring(v) end
    local r={"{"};for _,k in ipairs(sorted(v)) do r[#r+1]=encode(k);r[#r+1]=encode(v[k]) end
    r[#r+1]="}";return table.concat(r)
end
need(directory:match("^/var/tmp/aott%-c014%-lua%-test%-[a-f0-9]+$"),"fixture_directory_refused")
need(namespace:match("^aott_c014_[a-f0-9]+$"),"fixture_namespace_refused")
local packages={network=namespace.."_network",firewall=namespace.."_firewall"}
local config=directory.."/candidate"
local delta=directory.."/delta"
local cold=directory.."/cold"
local initial={}
local function directory_ok(path)
    local s=fs.lstat(path)
    need(s and s.type=="dir" and s.uid==0 and s.modedec==700,"unsafe_fixture_directory")
    if initial[path] then eq(s.ino,initial[path].ino,"directory_inode");eq(s["dev"],initial[path]["dev"],"directory_device")
    else initial[path]={ino=s.ino,dev=s["dev"]} end
end
local function file_ok(path,optional)
    local s=fs.lstat(path)
    if optional and not s then return end
    need(s and s.type=="reg" and s.uid==0 and s.modedec==600 and s.nlink==1 and s.size<=65536,
         "unsafe_fixture_file")
end
local function guards()
    for _,p in ipairs({directory,config,delta,cold}) do directory_ok(p) end
    for _,p in pairs(packages) do
        file_ok(config.."/"..p)
        file_ok(delta.."/"..p,true)
        eq(fs.lstat("/tmp/.uci/"..p),nil,"no_default_delta_collision")
    end
    -- Cold validation cannot accidentally see a staged change in that dir.
    for entry in fs.dir(cold) do
        need(entry=="." or entry=="..","cold_delta_not_empty")
    end
end
local function native(argv,commit,is_cold)
    guards()
    local args={"/usr/bin/timeout","-k","1","5","/usr/bin/qemu-mips-static","-L",vendor,
        vendor.."/sbin/uci","-c",config,commit and "-p" or "-P",is_cold and cold or delta}
    for _,v in ipairs(argv) do args[#args+1]=v end
    local code,output,overflow=web.capture(args,65536)
    guards()
    return code,output,overflow
end
local function snapshot_package(pkg,is_cold)
    local code,raw,overflow=native({"export",packages[pkg]},false,is_cold)
    eq(code,0,"export_exit");eq(overflow,false,"bounded_export")
    local parsed,why=model.parse_export(raw,packages[pkg]);return need(parsed,why)
end
local function snapshot(is_cold)
    return {network=snapshot_package("network",is_cold),firewall=snapshot_package("firewall",is_cold)}
end
local original=snapshot(true)
local calls=0
local adapter={disposable_fixture=true,snapshot=function() return snapshot(false) end,
    persisted_snapshot=function() return snapshot(true) end}
adapter.command=function(op)
    calls=calls+1
    local verb,operand=op[1],op[2]
    if fail_at and calls==fail_at then
        local code=native({"set",packages.network..".no_such_section.field=value"})
        return code==0
    end
    need(verb=="set" or verb=="delete" or verb=="add_list" or verb=="commit","unqualified_operation")
    local pkg,rest=operand:match("^([a-z]+)(.*)$")
    need(packages[pkg],"unqualified_package")
    if verb~="commit" then
        need(rest:sub(1,1)==".","unqualified_operand")
        local code,raw,overflow=native({verb,packages[pkg]..rest})
        return code==0 and raw=="" and overflow==false
    end
    eq(rest,"","commit_package_only")
    local expected=snapshot_package(pkg,false)
    local code,raw,overflow=native({"commit",packages[pkg]},true)
    if code~=0 or raw~="" or overflow~=false then return false end
    if encode(snapshot_package(pkg,true))~=encode(expected) then return false end
    local staged=delta.."/"..packages[pkg]
    if fs.lstat(staged) then file_ok(staged);need(fs.unlink(staged),"private_delta_cleanup") end
    return encode(snapshot_package(pkg,false))==encode(expected)
end
local function prepare(s,vid)
    local plan,why=model.prepare(s,vid,"eth0_0_1_lct","lan");return need(plan,why)
end
local function project(plan) return need(model.fixture_projection(plan,"offline_synthetic")) end
local function execute(plan)
    local receipt,why=model.verify_staged(plan,adapter,"offline_synthetic");return need(receipt,why)
end
if action=="plan" then
    local plan,why=model.prepare(original,target,"eth0_0_1_lct","lan")
    if not plan then print(json.stringify({error=why}));return end
    print(json.stringify(project(plan)));return
end
if inverse then
    local saved=fail_at;fail_at=nil
    execute(prepare(original,123));original=snapshot(true);calls=0;fail_at=saved;target=0
end
local plan=prepare(original,target)
if action=="failure" then
    local result,why=model.verify_staged(plan,adapter,"offline_synthetic")
    eq(result,nil,"injected_failure_refused")
    need(why=="candidate_mutation_failed" or why=="candidate_commit_failed","exact_mutation_failure")
    eq(calls,fail_at,"stop_at_first_failure")
    print("AOTT_C014_NATIVE_LUA_FAILURE_PASS");return
elseif action=="stale" then
    need(adapter.command({"set","network.untouched.proto=static"}),"stale_change")
    local used=calls
    local result,why=model.verify_staged(plan,adapter,"offline_synthetic")
    eq(result,nil,"stale_refused");eq(why,"stale_candidate_revision","stale_reason")
    eq(calls,used,"stale_no_writes")
elseif action=="no_op" then
    eq(target,0,"explicit_untagged_noop");execute(plan);eq(calls,0,"no_op_no_commits")
elseif action=="plan_tamper" then
    plan.operations={{"delete","network.lct"}}
    local projection=project(plan);projection.operations={{"delete","network.lct"}}
    projection.after.network.lct=nil
    local result=execute(plan)
    eq(result.contains_configuration_values,false,"redacted_receipt")
    need(snapshot(true).network.lct,"private_plan_unchanged")
elseif action=="bad_readback" then
    adapter.persisted_snapshot=function()
        local s=snapshot(true);s.network.lct_vlan.options.vid="999";return s
    end
    local result,why=model.verify_staged(plan,adapter,"offline_synthetic")
    eq(result,nil,"bad_cold_readback_refused");eq(why,"candidate_readback_mismatch","readback_reason")
elseif action=="exception" then
    adapter.snapshot=function() error("syntheticsecret",0) end
    local result,why=model.verify_staged(plan,adapter,"offline_synthetic")
    eq(result,nil,"exception_refused");eq(why,"candidate_internal_error","exception_not_echoed")
    eq(calls,0,"exception_no_writes")
elseif action=="roundtrip" then
    local first=execute(plan)
    eq(first.status,"SOURCE_LUA_UCI_CANDIDATE_VALIDATED","receipt")
    eq(first.live_promote_available,false,"no_live_promote")
    execute(prepare(snapshot(true),456))
    local tagged=snapshot(true);eq(tagged.network.lct_vlan.options.vid,"456","changed_tag")
    local prior=calls;execute(prepare(tagged,456));eq(calls,prior,"repeat_has_no_writes")
    execute(prepare(snapshot(true),0))
    eq(encode(snapshot(true)),encode(original),"exact_semantic_roundtrip")
elseif action=="guard" then
    local result,why=model.verify_staged(plan,adapter,"production")
    eq(result,nil,"production_refused");eq(why,"invalid_plan_handle","production_code")
    result,why=model.verify_staged({},adapter,"offline_synthetic")
    eq(result,nil,"forged_plan_refused");eq(calls,0,"guards_no_writes")
else error("unqualified_fixture_action") end
print("AOTT_C014_NATIVE_LUA_PASS action="..action.." checks="..checks.." native_mutations="..calls)
