-- Native-MIPS guarded staging fixture. Synthetic data, real UCI, no live apply.
local vendor=assert(arg[1]);local repo=assert(arg[2]);local directory=assert(arg[3])
local namespace=assert(arg[4]);local action=assert(arg[5]);local target=tonumber(arg[6]) or 123
local fail_at=tonumber(arg[7]);local inverse=arg[8]=="inverse"
package.path=repo.."/prototypes/configuration/?.lua;"..repo.."/overlay/usr/lib/lua/?.lua;"..
    vendor.."/usr/lib/lua/?.lua;"..vendor.."/usr/lib/lua/?/init.lua;"..package.path
package.cpath=vendor.."/usr/lib/lua/?.so;"..package.cpath
local model=require "8311.vlan_transition"
local staging=require "8311.vlan_stage_guard"
local stage_owner
local native_calls=0
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
need(directory:match("^/var/tmp/aott%-c014%-stage%-test%-[a-f0-9]+$"),"fixture_directory_refused")
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
    need(stage_owner and staging.status(stage_owner),"staging_owner_required")
    native_calls=native_calls+1
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

local function barrier(label)
    io.write(label.."\n");io.flush()
    eq(io.read("*l"),"continue","barrier_release")
end
local function report(result,why,mutations)
    print(json.stringify({status=result and result.status or "REJECTED",error=why,
        native_calls=native_calls,mutations=mutations or 0,
        no_live_apply=true,source_only_not_deployed=true}))
end
local owner,lease=staging.acquire(directory,"offline_synthetic")
if not owner then report(nil,lease,0);return end
stage_owner=owner
if action=="hold" then
    local again,why=staging.acquire(directory,"offline_synthetic")
    eq(again,nil,"nested_acquisition_refused")
    eq(why,"staging_already_owned_in_process","recursive_before_open")
    need(staging.status(owner),"outer_lock_still_owned")
    barrier("AOTT_C014_STAGE_LOCK_HELD")
    report(need(staging.close(owner)),nil,0);return
elseif action=="try" then
    report(need(staging.close(owner)),nil,0);return
elseif action=="double_close" then
    need(staging.close(owner))
    local again,why=staging.close(owner)
    eq(again,nil,"duplicate_release_denied");eq(why,"invalid_staging_handle","duplicate_release_code")
    report({status="SOURCE_DOUBLE_CLOSE_REFUSED"},nil,0);return
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

adapter.workspace_directory=directory
local plan=need(model.prepare(original,target,"eth0_0_1_lct","lan"))
local plain_snapshot=adapter.snapshot
local plain_command=adapter.command
local plain_persisted=adapter.persisted_snapshot
if action=="pending_pause" then
    adapter.snapshot=function()
        barrier("AOTT_C014_STAGE_PENDING")
        return plain_snapshot()
    end
elseif action=="mutation_pause" then
    adapter.command=function(op)
        local result=plain_command(op)
        if calls==1 then barrier("AOTT_C014_STAGE_FIRST_MUTATION") end
        return result
    end
elseif action=="readback_pause" then
    adapter.persisted_snapshot=function()
        local result=plain_persisted()
        barrier("AOTT_C014_STAGE_PERSISTED_READ")
        return result
    end
elseif action=="exception" then
    adapter.snapshot=function()error("SYNTHETIC_PRIVATE_ADAPTER_ERROR",0)end
elseif action=="nested" then
    adapter.snapshot=function()
        local ok,why=staging.close(owner)
        eq(ok,nil,"no_close_during_stage");eq(why,"staging_in_progress","close_reason")
        ok,why=staging.stage(owner,plan,adapter,"offline_synthetic")
        eq(ok,nil,"recursive_stage_refused");eq(why,"staging_in_progress","recursive_reason")
        ok,why=staging.acquire(directory,"offline_synthetic")
        eq(ok,nil,"recursive_open_refused");eq(why,"staging_already_owned_in_process","duplicate_reason")
        return plain_snapshot()
    end
elseif action=="wrong_workspace" then
    adapter.workspace_directory=directory.."/not_the_owner"
elseif action=="stale" then
    need(plain_command({"set","network.untouched.proto=static"}),"make_stale_fixture")
elseif action=="bad_readback" then
    adapter.persisted_snapshot=function()
        local result=plain_persisted();result.network.lct_vlan.options.vid="999";return result
    end
end
local n=require "nixio"
local actual_open,actual_rename=n.open,fs.rename
if action=="pending_sync_failure" or action=="final_sync_failure" then
    local phase=0
    n.open=function(path,...)
        local fd=actual_open(path,...)
        if fd and path==directory.."/stage.state.new" then
            phase=phase+1
            if (action=="pending_sync_failure" and phase==1) or
               (action=="final_sync_failure" and phase==2) then
                return {stat=function()return fd:stat()end,
                    writeall=function(_,bytes)return fd:writeall(bytes)end,
                    sync=function()return false end,
                    close=function()return fd:close()end}
            end
        end
        return fd
    end
elseif action=="marker_rename_failure" then
    fs.rename=function(from,to)
        if from==directory.."/stage.state.new" then return false end
        return actual_rename(from,to)
    end
end
local result,why=staging.stage(owner,plan,adapter,"offline_synthetic")
n.open,fs.rename=actual_open,actual_rename
if action=="validated_pause" then
    need(result,why)
    barrier("AOTT_C014_STAGE_VALIDATED")
end
if result then
    eq(result.no_live_apply,true,"no_promotion")
    eq(result.workspace_reusable,false,"single_use")
    eq(result.no_configuration_values_exported,true,"receipt_redacted")
    local retry,retry_why=staging.stage(owner,plan,adapter,"offline_synthetic")
    eq(retry,nil,"completed_workspace_single_use")
    eq(retry_why,"staging_workspace_already_used","completed_reason")
end
local released,release_why=staging.close(owner)
need(released,release_why)
report(result,why,calls)
