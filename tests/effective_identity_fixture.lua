-- Exercise actual controller, validators and fixed-key probes with synthetic
-- dependencies only. The existing C-012 bootstrap installs memory-only I/O.
local root=assert(arg[1],"repository root required")
package.path=root.."/overlay/usr/lib/lua/?.lua;"..package.path
arg={root.."/overlay/usr/lib/lua/8311/config.lua",
     root.."/overlay/usr/lib/lua/luci/controller/8311.lua"}
dofile(root.."/tests/c012_config_contract_fixture.lua")
local config=require "8311.config"
local controller=require "luci.controller.8311"
local state=require "8311.effective_identity_state"
local probe=require "8311.effective_identity_probe"
local checked=0
local function eq(a,b,label)
    checked=checked+1
    assert(a==b,"IDENTITY_CONTRACT_FAILED:"..label)
end
local function ok(value,label) eq(not not value,true,label) end
local schema={}
for _,group in ipairs(controller.fwenvs_8311()) do
    for _,item in ipairs(group.items) do schema[item.id]=item end
end
local covered={}
for _,mod in ipairs({"effective_state","effective_device_state","effective_pon_state",
                    "effective_vlan_state","effective_hardware_state","effective_reporting_state"}) do
    local model=require("8311."..mod)
    for _,id in ipairs(model.fields or model.management_fields) do
        eq(covered[id],nil,"no_existing_overlap_"..id)
        covered[id]=true
    end
end
local before=0
for _ in pairs(covered) do before=before+1 end
eq(before,46,"prior_coverage")
local fields=state.field_ids()
eq(#fields,9,"new_nine_fields")
for _,id in ipairs(fields) do
    ok(schema[id],"canonical_field_"..id)
    eq(state.limit(id),tonumber(schema[id].maxlength),"canonical_length_"..id)
    eq(covered[id],nil,"new_field_unique_"..id)
    covered[id]=true
end
local all=0
for id in pairs(covered) do all=all+1;ok(schema[id],"no_invented_field_"..id) end
eq(all,55,"full_stored_source_coverage")
for id in pairs(schema) do eq(covered[id],true,"all_schema_covered_"..id) end

local synthetic={gpon_sn="TEST".."10ABCDEF",vendor_id="TST9",reg_id_hex="A1B2",
    loid="SyntheticUser",lpwd="FakeOnlyPwd",iphost_mac=table.concat({"02","AA","BB","CC","DD","EE"},":"),
    iphost_hostname="fixture"..".invalid",iphost_domain="example"..".invalid",
    root_pwhash="$".."6".."$salt$"..string.rep("Q",86)}
local function no_leak(value)
    if type(value)=="table" then
        for k,v in pairs(value) do no_leak(k);no_leak(v) end
    elseif type(value)=="string" then
        for _,secret in pairs(synthetic) do
            ok(not value:find(secret,1,true),"no_source_value_exported")
        end
    end
end
local function observe(overrides)
    local calls={}
    local report=assert(probe.capture({environment=function(id,bound)
        eq(bound,state.limit(id)+2,"bounded_capture_"..id)
        calls[#calls+1]=id
        if overrides and overrides[id] then return unpack(overrides[id]) end
        return 0,synthetic[id].."\n",false
    end}))
    eq(#calls,9,"only_nine_calls")
    for i,id in ipairs(fields) do eq(calls[i],id,"fixed_order_"..id) end
    no_leak(report)
    return report
end
local report=observe()
eq(report.summary.valid_saved_override,9,"all_valid")
eq(report.summary.hardware_qualified,0,"no_hardware_claim")
eq(report.no_identity_exported,true,"redacted")
for _,id in ipairs(fields) do
    local row=report.fields[id]
    eq(row.source_status,"valid_saved_override","valid_"..id)
    eq(row.value_hash_exported,false,"no_hash_"..id)
    eq(row.value_length_exported,false,"no_length_"..id)
    eq(row.runtime_effect_proven,false,"no_effect_"..id)
    eq(row.authentication_success_proven,false,"no_auth_claim_"..id)
    eq(row.survives_reboot_proven,false,"no_persistence_"..id)
    eq(row.fallback_value_not_resolved,true,"fallback_unknown_"..id)
    eq(config.validate(schema[id],synthetic[id]),nil,"real_validator_"..id)
    local missing=observe({[id]={1,"",false}})
    eq(missing.fields[id].source_status,"unset","unset_"..id)
    local failed=observe({[id]={74,"",false}})
    eq(failed.fields[id].source_status,"unavailable","failed_not_unset_"..id)
    local overflow=observe({[id]={0,synthetic[id],true}})
    eq(overflow.fields[id].source_status,"unavailable","overflow_not_success_"..id)
    local multiline=observe({[id]={0,"a\nb\n",false}})
    eq(multiline.fields[id].source_status,"invalid_saved_override","embedded_newline_"..id)
    local oversized=observe({[id]={0,string.rep("X",state.limit(id)+3),false}})
    eq(oversized.fields[id].source_status,"invalid_saved_override","oversized_"..id)
    local changed=state.field_ids();changed[1]="not_a_key"
    eq(state.field_ids()[1],"gpon_sn","field_list_is_copy")
end
for id,value in pairs({gpon_sn="bad",vendor_id="LONGER",reg_id_hex="AAA",
                      iphost_mac="invalid",root_pwhash="plaintext_not_hash"}) do
    eq(observe({[id]={0,value.."\n",false}}).fields[id].source_status,
       "invalid_saved_override","bad_format_"..id)
end
local throwing=assert(probe.capture({environment=function() error("SYNTHETIC_ERROR_VALUE") end}))
eq(throwing.summary.unavailable,9,"exceptions_redacted")
no_leak(throwing)

local SID=string.rep("b",32)
local function acl() return {["access-group"]={["luci-access"]={"read","write"}}} end
local dispatcher=package.loaded["luci.dispatcher"]
local util=package.loaded["luci.util"]
local web=package.loaded["8311.webutil"]
local http=package.loaded["luci.http"]
local env_calls,access_calls=0,0
local fail_access,fail_get,wrong_sid,revoke=false,false,false,false
local function reset()
    dispatcher.context={authsession=SID,authuser="root",authacl=acl()}
    env_calls,access_calls=0,0
    fail_access,fail_get,wrong_sid,revoke=false,false,false,false
end
util.ubus=function(object,method,args)
    eq(object,"session","session_only")
    eq(args.ubus_rpc_session,SID,"trusted_sid_only")
    if method=="get" then
        if fail_get then return nil end
        return {ubus_rpc_session=wrong_sid and string.rep("c",32) or SID,
                values={username="root"}}
    end
    eq(method,"access","access_only")
    access_calls=access_calls+1
    if fail_access or (revoke and access_calls>1) then return {access=false} end
    return acl()
end
web.capture=function(argv,limit)
    env_calls=env_calls+1
    eq(#argv,7,"fixed_argv_size")
    eq(argv[1],"/usr/bin/timeout","timeout")
    eq(argv[4],"3","native_deadline")
    eq(argv[5],"/usr/sbin/fwenv_get","read_only_getter")
    eq(argv[6],"--8311","prefixed_only")
    local id=argv[7]
    ok(state.limit(id),"fixed_id")
    eq(limit,state.limit(id)+2,"fixed_maximum")
    return 0,synthetic[id].."\n",false
end
reset()
report=assert(probe.live_identity(dispatcher,util))
eq(env_calls,9,"authorized_nine_reads")
eq(access_calls,2,"reauthorized_before_response")
no_leak(report)
for _,bad in ipairs({"no_context","nonroot","empty_acl","bad_sid","expired","denied","wrong_sid","anonymous"}) do
    reset()
    if bad=="no_context" then dispatcher.context=nil
    elseif bad=="nonroot" then dispatcher.context.authuser="guest"
    elseif bad=="empty_acl" then dispatcher.context.authacl={}
    elseif bad=="bad_sid" then dispatcher.context.authsession="../../invalid"
    elseif bad=="expired" then fail_get=true
    elseif bad=="denied" then fail_access=true
    elseif bad=="wrong_sid" then wrong_sid=true
    elseif bad=="anonymous" then dispatcher.context.authsession=string.rep("0",32) end
    local data,why=probe.live_identity(dispatcher,util)
    eq(data,nil,"reject_"..bad);eq(why,"forbidden","generic_error_"..bad)
    eq(env_calls,0,"no_read_for_"..bad)
end
reset();revoke=true
local data,why=probe.live_identity(dispatcher,util)
eq(data,nil,"revoked_returns_no_data");eq(why,"forbidden","revoked_fixed_error")
eq(env_calls,9,"read_then_revocation")

-- Actual controller handler: methods, headers, authorization and errors.
local method,headers,response="GET",{},nil
http.getenv=function(key) eq(key,"REQUEST_METHOD","method_only");return method end
http.header=function(k,v) headers[k]=v end
web.reply=function(_,code,body) response={code=code,body=body};return response end
for _,verb in ipairs({"POST","HEAD","PUT"}) do
    reset();method=verb
    controller.action_effective_identity()
    eq(response.code,405,"readonly_method_"..verb)
    eq(env_calls,0,"wrong_method_reads_nothing")
end
reset();method="GET";fail_get=true
controller.action_effective_identity();eq(response.code,403,"controller_denies_expired")
reset();method="GET"
controller.action_effective_identity()
eq(response.code,200,"controller_returns_redacted")
eq(headers["Cache-Control"],"no-store, private","no_store")
eq(headers["X-Content-Type-Options"],"nosniff","nosniff")
no_leak(response.body)
print("AOTT_C011_IDENTITY_PASS covered=55 checks="..checked)
