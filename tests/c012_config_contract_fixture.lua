-- C-012 source-only tests of the real LuCI schema and 8311.config writer.
-- All native dependencies are memory-only stubs. No ONU, UCI or flash calls.
local config_path=assert(arg[1],"config path")
local lua_root=assert(config_path:match("^(.*)/8311/config%.lua$"),"overlay Lua root unavailable")
package.path=lua_root.."/?.lua;"..package.path
local calls, saved, fail_mode, missing_readback = {}, {}, nil, false
local activation_fail=false
local activation_error_mode=nil
local activation_recovery_pending=false
local function copy(t)
    local out={}
    for k,v in pairs(t) do out[k]=v end
    return out
end

local function setter(kind)
    return function(args)
        calls[#calls+1]={kind=kind,id=args[1],value=args[2]}
        if fail_mode=="before" then return false end
        if fail_mode=="rollback_mismatch" and args[2]=="old-fixture-host" then
            saved[(kind=="base" and "" or "8311_")..args[1]]="drifted-after-rollback"
            return true
        end
        saved[(kind=="base" and "" or "8311_")..args[1]]=args[2]
        if fail_mode=="after" then return false end
        if fail_mode=="after_once" then fail_mode=nil; return false end
        if fail_mode=="postwrite_exception" then fail_mode=nil; error("untrusted setter error") end
        if fail_mode=="rollback_exception" and args[2]=="old-fixture-host" then
            error("untrusted rollback error")
        end
        return true
    end
end
package.preload["8311.tools"]=function()
    return {
        fwenv_read_all=function()
            if missing_readback then return nil,"fixture unavailable" end
            return copy(saved)
        end,
        fw_setenv=setter("base"),
        fw_setenv_8311=setter("prefixed"),
        fw_getenv=function() return "" end,
        iterator2array=function(iterator)
            local values={}
            while true do
                local value=iterator()
                if value==nil then break end
                values[#values+1]=value
            end
            return values
        end
    }
end
package.preload["luci.util"]=function()
    return {
        trim=function(x) return (x or ""):match("^%s*(.-)%s*$") end,
        exec=function(cmd)
            if cmd:find("zone.tab",1,true) then return "UTC\nAmerica/New_York\n" end
            if cmd:find("luci.languages",1,true) then
                if cmd:find("uci show",1,true) then return "en\n" end
                return "English"
            end
            return ""
        end,
        shellquote=function(x) return "'"..tostring(x).."'" end,
    }
end
package.preload["nixio.fs"]=function()
    return {glob=function()
        local values={"/etc/mibs/prx300_1U.ini","/etc/mibs/test_2U.ini"}
        local nextidx=0
        return function()
            nextidx=nextidx+1
            return values[nextidx]
        end
    end}
end
package.preload["luci.i18n"]=function() return {translate=function(s) return s end} end
package.preload["8311.webutil"]=function()
    return {
        digest_text=function() return "fixture-revision" end,
        read_json=function() return nil end,
        capture=function() return 0, "", false end,
    }
end
package.preload["base64"]=function()
    return {
        enc=function(s) return "ENC:"..s end,
        dec=function(s)
            assert(s:sub(1,4)=="ENC:","Invalid synthetic base64")
            return s:sub(5)
        end,
    }
end
package.preload["luci.jsonc"]=function() return {} end
package.preload["8311.mib_profile"]=function()
    return {
        inspect=function(path)
            if path~="/etc/mibs/prx300_1U.ini" and path~="/etc/mibs/test_2U.ini" then
                return nil,"fixture_mib_unknown"
            end
            return {
                schema=1,path=path,
                topology={slot_editable=true},
                applicability={
                    vendor_id=true,hw_ver=true,cp_hw_ver_sync=true,
                    equipment_id=true,software_reporting=true,
                    iphost_identity=true,pon_slot=true,
                },
                defaults={pon_slot="1"},
            }
        end,
        validate_for_configuration=function() return true end,
    }
end
package.preload["8311.config_activation"]=function()
    return {
        apply=function(changes)
            local route=require "8311.config_route"
            local order={}
            for _,change in ipairs(changes or {}) do
                if change.item and route.route(change.item.id)=="live" then
                    order[#order+1]=change.item.id
                end
            end
            if activation_error_mode and #order>0 then
                local mode=activation_error_mode
                activation_error_mode=nil
                if mode=="no_receipt" then
                    return nil,"live_activation_fixture_preflight_failed"
                elseif mode=="malformed_receipt" then
                    return true
                elseif mode=="exception" then
                    error("fixture sensitive detail should not enter a response")
                end
                error("Unsupported fixture activation error")
            end
            if activation_fail and #order>0 then
                activation_fail=false
                return {
                    schema=1,success=false,order=order,
                    rollback_attempted=true,rollback_succeeded=true,
                    error="synthetic_activation_failure",
                }
            end
            local states={}
            for _,id in ipairs(order) do
                states[id]={
                    configured_verified=true,
                    runtime_effect_proven=not activation_recovery_pending,
                    runtime_pending=activation_recovery_pending,
                }
            end
            activation_recovery_pending=false
            return {
                schema=1,success=true,order=order,fields=states,
                requires_new_authenticated_request=false,
                rollback_attempted=false,
            }
        end
    }
end
package.preload["8311.tls_import"]=function()
    return {receive=function() return nil,"fixture_tls_import_unavailable",503 end}
end
package.preload["8311.credential_activation"]=function()
    return {
        apply=function()
            return {
                schema=1,success=true,changed=true,credential_verified=true,
                contains_credential_material=false,
                observed_source="fixture_redacted_credential_readback",
            }
        end
    }
end
for _,name in ipairs({
    "luci.template","luci.http","luci.dispatcher","luci.sys",
    "luci.ltn12","nixio.bit","luci.model.uci","8311.health","8311.monitoring",
    "8311.history_config","8311.history_live_snapshot","8311.management_preflight",
    "8311.tls_candidate","8311.tls_activation",
    "8311.effective_probe","8311.effective_device_probe",
    "8311.effective_pon_probe","8311.effective_vlan_probe",
    "8311.effective_hardware_probe","8311.effective_reporting_probe",
    "8311.uploads","8311.jobs"
}) do package.preload[name]=function() return {} end end

local config=assert(loadfile(config_path))()
local config_route=require "8311.config_route"
package.loaded["8311.config"]=config
assert(loadfile(assert(arg[2],"controller path")))()
local controller=assert(package.loaded["luci.controller.8311"])
local canonical=assert(controller.fwenvs_8311)()
local fields, groups={},{}
for _,category in ipairs(canonical) do
    for _,item in ipairs(category.items) do
        assert(not fields[item.id],"Duplicate real schema ID "..item.id)
        fields[item.id]=item
        groups[item.id]=category.id
    end
end
local count=0
for _ in pairs(fields) do count=count+1 end
assert(count==55,"Unexpected real GUI field count: "..count)

-- This fixture uses only synthetic values; it never loads a real profile.
saved={["8311_gpon_sn"]="TEST00000000", ["8311_ipaddr"]="192.0.2.10"}
local function stored_key(item) return (item.base and "" or "8311_")..item.id end
local function baseline_form(snapshot)
    local f={complete="8311-v1",revision=snapshot.revision,mode="preview"}
    for _,item in ipairs(snapshot.items) do
        local val=item.value
        if item.type=="checkbox" or item.type=="checkbox_onoff" then
            val=(val=="1" or val=="on" or (val=="" and item.default)) and "1" or "0"
        elseif val=="" and item.default~=nil then
            val=tostring(item.default)
        end
        if item.type=="select" or item.type=="select_named" then
            if val=="" and item.default==nil and item.options[1] then
                local opt=item.options[1]
                val=type(opt)=="table" and opt.value or opt
            end
        end
        if item.id=="gpon_sn" then val="TEST00000000" end
        f[item.id]=val
    end
    return f
end

local function example_for(item, old)
    local custom={
        gpon_sn="TEST12345678", vendor_id="ABCD", reg_id_hex="AABB",
        ipaddr="192.0.2.20", netmask="255.255.255.".."128",
        lct_vlan="321", gateway="192.0.2.1", dns_server="192.0.2.20",
        ping_ip="192.0.2.20",
        root_pwhash="$6$aa$"..string.rep("A",86),
        iphost_mac=table.concat({"02","01","02","03","04","05"},":"),
        lct_mac=table.concat({"02","07","08","09","0A","0B"},":"),
        sfp_oui="AA:BB:CC", sfp_date="260101",
        omcc_version="0x82", ntp_servers="pool.ntp.org",
        ethtool_speed="speed 10000 duplex full autoneg on",
        fw_match_b64="V(.+)", mib_file="/etc/mibs/test_2U.ini",
        hostname="aott-fixture", iop_mask="19",
        internet_vlan="111", services_vlan="222",
        pon_slot="2"
    }
    if custom[item.id] then return custom[item.id] end
    if item.type=="checkbox" or item.type=="checkbox_onoff" then
        return old=="1" and "0" or "1"
    end
    if item.type=="number" then
        local max=tonumber(item.max) or 999
        local min=tonumber(item.min) or 0
        local n=tonumber(old) or min
        if n<max then return tostring(n+1) end
        return tostring(math.max(min,n-1))
    end
    if item.type=="select" or item.type=="select_named" then
        for _,v in ipairs(item.options or {}) do
            local value=type(v)=="table" and v.value or v
            if value~=old and value~=item.default then return value end
        end
        for _,v in ipairs(item.options or {}) do
            local value=type(v)=="table" and v.value or v
            if value~=old then return value end
        end
    end
    return item.id=="lo id" and "test" or "lab"
end

local checked, mutation_count, sensitive_count, max_count=0,0,0,0
local route_counts={live=0,management=0,boot=0,credential=0,pon=0}
for _,category in ipairs(canonical) do
    for _,field in ipairs(category.items) do
        saved={["8311_gpon_sn"]="TEST00000000", ["8311_ipaddr"]="192.0.2.10"}
        calls={}
        fail_mode=nil
        missing_readback=false
        local snap=assert(config.snapshot(canonical))
        local form=baseline_form(snap)
        local item=fields[field.id]
        local good=example_for(item,form[item.id])
        assert(type(good)=="string",item.id..": positive sample missing")
        local validation_error=config.validate(item,good)
        assert(not validation_error,item.id..": valid synthetic input rejected: "..tostring(validation_error))
        local bad=good.."\n"
        assert(config.validate(item,bad),item.id..": invalid input accepted")
        local form_bad=copy(form)
        form_bad[item.id]=bad
        local bad_plan,bad_errors,bad_status=config.prepare(snap,form_bad)
        assert(not bad_plan and bad_status==422 and bad_errors[item.id],
            item.id..": invalid input passed full-form validation")
        assert(#calls==0,item.id..": invalid preview called a native writer")
        -- Check schema-specific invalid values, not only generic control characters.
        local structural_bad
        if item.type=="checkbox" or item.type=="checkbox_onoff" then
            structural_bad="2"
        elseif item.type=="number" then
            structural_bad="-1"
        elseif item.type=="select" or item.type=="select_named" then
            structural_bad="__unsupported_enum__"
        elseif item.maxlength and tonumber(item.maxlength) then
            structural_bad=string.rep("X",tonumber(item.maxlength)+1)
        else
            structural_bad="INVALID\nSTRING"
        end
        assert(config.validate(item,structural_bad),
            item.id..": structurally invalid setting accepted")
        local form_good=copy(form)
        form_good[item.id]=good
        local planned,errors,status=config.prepare(snap,form_good)
        assert(planned,item.id..": valid full-form preview failed: "..tostring(errors and errors[item.id] or status))
        local planned_ids={}
        for _,change in ipairs(planned.changes) do
            planned_ids[change.item.id]=true
        end
        -- Defaults normalize to "unset", so a valid selection may be a no-op.
        assert(not planned_ids.gpon_sn or field.id=="gpon_sn",
            item.id..": unrelated PON identity mutation in preview")
        for _,diff in ipairs(planned.diff) do
            if diff.id==item.id then
                local route=config_route.route(item.id)
                assert(type(diff.applies)=="string" and #diff.applies>0,
                    item.id..": missing activation description")
                if route=="management" then
                    assert(diff.applies:find("Guarded live management transaction",1,true),
                        item.id..": timed management transaction not disclosed")
                elseif route=="live" then
                    assert(not diff.applies:find("no independent live-effect verifier",1,true),
                        item.id..": live verified field fell back to generic activation text")
                elseif route=="boot" then
                    assert(diff.applies:find("Guarded",1,true) and
                           diff.applies:find("reboot",1,true),
                        item.id..": guarded boot/recovery transaction not disclosed")
                elseif route=="credential" then
                    assert(diff.applies:find("Dedicated secret-safe root credential",1,true),
                        item.id..": credential transaction not disclosed")
                elseif route=="pon" then
                    assert(diff.applies:find("Guarded PON/OMCI transaction",1,true) and
                           diff.applies:find("OLT acceptance",1,true),
                        item.id..": optical rollback/qualification boundary not disclosed")
                else
                    error(item.id..": missing source-owned configuration route")
                end
            end
        end
        if item.secret then
            sensitive_count=sensitive_count+1
            for _,diff in ipairs(planned.diff) do
                if diff.id==item.id then
                    assert(diff.after=="[hidden]" and diff.before~="TEST00000000",
                        item.id..": secret appears in preview")
                    assert(not diff.after:find(good,1,true),item.id..": secret leaked")
                end
            end
        end
        if planned_ids[item.id] then
            assert(#planned.changes==1,item.id..": positive edit produced unrelated writes")
            local route=config_route.route(item.id)
            assert(planned.route==route,item.id..": preview route mismatch")
            local apply=config.apply(snap,planned)
            route_counts[route]=route_counts[route]+1
            if route=="management" or route=="boot" or route=="pon" then
                assert(not apply.success and apply.rejected_before_write and
                       apply.required_route==route,
                    item.id..": dedicated guarded route reached ordinary writer")
                assert(#calls==0,item.id..": guarded route wrote boot environment before its dedicated transaction")
                if route=="management" then assert(apply.management_transaction_required) end
                if route=="boot" then assert(apply.boot_transaction_required) end
                if route=="pon" then assert(apply.pon_transaction_required) end
            elseif route=="live" or route=="credential" then
                assert(apply.success and #apply.verified==1 and apply.verified[1]==item.id,
                    item.id..": positive write/readback failed")
                assert(#calls==1,item.id..": native setter not called exactly once")
                assert(calls[1].kind==(item.base and "base" or "prefixed"),
                    item.id..": wrong boot environment namespace")
                assert(saved[stored_key(item)]==planned.changes[1].raw,
                    item.id..": readback differs from proposed stored value")
                if route=="credential" then
                    assert(apply.activation and apply.activation.contains_credential_material==false,
                        item.id..": credential result was not explicitly redacted")
                end
                mutation_count=mutation_count+1
            else
                error(item.id..": unexpected route")
            end
        end
        checked=checked+1
        max_count=max_count+#planned.diff
    end
end
assert(checked==55 and mutation_count==23,
       "Unexpected ordinary live/credential write count: "..mutation_count.."/"..checked)
assert(route_counts.live==22 and route_counts.management==6 and
       route_counts.boot==4 and route_counts.credential==1 and
       route_counts.pon==22,
       ("Unexpected A-to-Z route partition: live=%d management=%d boot=%d credential=%d pon=%d"):format(
           route_counts.live,route_counts.management,route_counts.boot,
           route_counts.credential,route_counts.pon))
assert(sensitive_count==5,"Unexpected source secret markers: "..sensitive_count)

local function fresh()
    saved={["8311_gpon_sn"]="TEST00000000", ["8311_ipaddr"]="192.0.2.10"}
    calls={}
    fail_mode=nil
    missing_readback=false
    activation_fail=false
    activation_error_mode=nil
    activation_recovery_pending=false
    local s=assert(config.snapshot(canonical))
    local f=baseline_form(s)
    return s,f
end
local snap,form=fresh()
form.revision="stale"
local plan,errors,status=config.prepare(snap,form)
assert(not plan and status==409 and errors.revision,"Stale revision was accepted")

snap,form=fresh()
form.unrecognized="attack"
plan,errors,status=config.prepare(snap,form)
assert(not plan and status==422 and errors.request,"Unknown field was accepted")

snap,form=fresh()
form.hostname={}
plan,errors,status=config.prepare(snap,form)
assert(not plan and status==422 and errors.hostname,"Duplicate/array field was accepted")

snap,form=fresh()
form.hostname="good-lab-host"
form.ntp_servers="time.example"
plan,errors,status=config.prepare(snap,form)
assert(plan and #plan.changes==2,"Two-field plan was not recorded")
fail_mode="after_once"
local result=config.apply(snap,plan)
assert(not result.success and result.rollback_attempted and result.rollback_succeeded,
       "Postwrite failure was not restored")
assert(not result.durability_unknown and not result.partial and #result.verified==0,
       "Verified rollback was misclassified as unknown/partial")
assert(#calls==2,"Postwrite failure did not perform exactly one reverse restoration")
assert((saved["8311_hostname"] or "")=="",
       "Postwrite rollback did not restore original hostname override")

snap,form=fresh()
form.hostname="good-lab-host"
form.ntp_servers="time.example"
plan=assert(config.prepare(snap,form))
-- First write succeeds, second fails before mutation. Both attempted
-- fields must be restored in reverse order under the same environment lock.
local original_setter=package.loaded["8311.tools"].fw_setenv_8311
local failed_ntp_once=false
package.loaded["8311.tools"].fw_setenv_8311=function(args)
    if args[1]=="ntp_servers" and not failed_ntp_once then
        failed_ntp_once=true
        return false
    end
    return original_setter(args)
end
result=config.apply(snap,plan)
assert(not result.success and result.rollback_attempted and result.rollback_succeeded,
       "Multi-field persistence failure was not rolled back")
assert(not result.partial and not result.durability_unknown and #result.verified==0,
       "Verified multi-field rollback was reported as partial")
assert((saved["8311_hostname"] or "")=="" and
       (saved["8311_ntp_servers"] or "")=="",
       "Multi-field rollback did not restore original saved values")
assert(#calls==3,
       "Expected original hostname write plus reverse ntp/hostname restoration")
package.loaded["8311.tools"].fw_setenv_8311=original_setter

snap,form=fresh()
form.hostname="good-lab-host"
plan=assert(config.prepare(snap,form))
missing_readback=true
result=config.apply(snap,plan)
assert(not result.success and result.rollback_attempted and
       not result.rollback_succeeded and result.durability_unknown,
       "Unavailable rollback readback must remain durability-unknown")

-- A native setter may mutate storage and then throw. The outer writer
-- must still restore and read back every attempted startup value.
snap,form=fresh()
saved["8311_hostname"]="old-fixture-host"
snap=assert(config.snapshot(canonical))
form=baseline_form(snap)
form.hostname="new-fixture-host"
plan=assert(config.prepare(snap,form))
fail_mode="postwrite_exception"
result=config.apply(snap,plan)
assert(not result.success and result.rollback_attempted and
       result.rollback_succeeded and not result.durability_unknown,
       "Native post-write exception escaped verified rollback")
assert(saved["8311_hostname"]=="old-fixture-host" and #result.verified==0,
       "Native post-write exception leaked a newly saved startup value")

-- A restoration setter exception itself is contained, not presented as a
-- fully restored transaction or leaked into the user-visible receipt.
snap,form=fresh()
saved["8311_hostname"]="old-fixture-host"
snap=assert(config.snapshot(canonical))
form=baseline_form(snap)
form.hostname="new-fixture-host"
plan=assert(config.prepare(snap,form))
activation_error_mode="no_receipt"
fail_mode="rollback_exception"
result=config.apply(snap,plan)
assert(not result.success and not result.saved_rollback_succeeded and
       result.durability_unknown and result.runtime_state_unknown,
       "Rollback exception was incorrectly marked successful")
assert(not result.errors.request:find("untrusted rollback error",1,true),
       "Native rollback error string escaped to public response")
fail_mode=nil

-- A native setter that reports success but stores the wrong value must fail.
snap,form=fresh()
form.hostname="good-lab-host"
plan=assert(config.prepare(snap,form))
local original_write=package.loaded["8311.tools"].fw_setenv_8311
package.loaded["8311.tools"].fw_setenv_8311=function(args)
    calls[#calls+1]={kind="prefixed",id=args[1],value=args[2]}
    saved["8311_"..args[1]]="different-from-requested"
    return true
end
result=config.apply(snap,plan)
assert(not result.success and result.rollback_attempted and
       not result.rollback_succeeded and result.durability_unknown,
       "Incorrect native readback plus failed restoration cannot be accepted")
assert(#result.verified==0 and #calls==2,
       "Mismatch must attempt one restoration and retain no verified receipt")
package.loaded["8311.tools"].fw_setenv_8311=original_write

-- A live activation failure for a lower-risk field must restore the saved
-- boot-environment value so the rejected change cannot appear after reboot.
snap,form=fresh()
saved["8311_hostname"]="old-fixture-host"
snap=assert(config.snapshot(canonical))
form=baseline_form(snap)
form.hostname="new-fixture-host"
plan=assert(config.prepare(snap,form))
activation_fail=true
calls={}
result=config.apply(snap,plan)
assert(not result.success and result.activation_failed,
       "Synthetic live activation failure was reported as success")
assert(result.saved_rollback_attempted and result.saved_rollback_succeeded,
       "Saved environment rollback was not verified")
assert(result.runtime_rollback_succeeded==true,
       "Runtime rollback receipt was not preserved")
assert(saved["8311_hostname"]=="old-fixture-host",
       "Rejected live hostname change remained saved for next boot")
assert(#result.verified==0 and not result.partial and not result.durability_unknown,
       "Fully rolled-back activation failure was misclassified as partial/unknown")
activation_fail=false

-- A successful recovery function is not necessarily proof that a runtime
-- consumer was restored. Pending language/reload effects remain unknown.
snap,form=fresh()
saved["8311_hostname"]="old-fixture-host"
snap=assert(config.snapshot(canonical))
form=baseline_form(snap)
form.hostname="new-fixture-host"
plan=assert(config.prepare(snap,form))
activation_fail=true
activation_recovery_pending=true
result=config.apply(snap,plan)
assert(not result.success and result.saved_rollback_succeeded and
       result.runtime_rollback_succeeded==false,
       "Pending native recovery incorrectly marked fully verified")
assert(result.runtime_recovery and result.runtime_recovery.success and
       result.runtime_recovery.fields.hostname.runtime_pending,
       "Fixture must exercise successful-but-pending native recovery")
assert(result.partial and result.runtime_state_unknown and
       not result.durability_unknown and saved["8311_hostname"]=="old-fixture-host",
       "Saved recovery and unknown runtime were not reported separately")

-- P0-09: a nil activation receipt arrives only AFTER the boot environment
-- has already been saved. It must restore and read back all saved keys.
snap,form=fresh()
saved["8311_hostname"]="old-fixture-host"
snap=assert(config.snapshot(canonical))
form=baseline_form(snap)
form.hostname="new-fixture-host"
form.ntp_servers="time2.example"
plan=assert(config.prepare(snap,form))
assert(#plan.changes==2,"Fixture does not exercise full multi-field rollback")
activation_error_mode="no_receipt"
calls={}
result=config.apply(snap,plan)
assert(not result.success and result.activation_failed and result.saved_rollback_attempted,
       "Missing activation receipt did not mark transaction failure")
assert(result.saved_rollback_succeeded and result.persistence_rollback.succeeded,
       "Missing activation receipt did not verify boot-environment restoration")
assert(result.rollback_attempted and not result.rollback_succeeded and
       result.runtime_state_unknown and result.partial and not result.durability_unknown,
       "Saved readback was confused with proof of native runtime restoration")
assert(result.activation_error=="live_activation_fixture_preflight_failed",
       "Safe activation error identifier not retained")
assert(saved["8311_hostname"]=="old-fixture-host" and
       (saved["8311_ntp_servers"] or "")=="" and #result.verified==0,
       "Rejected multi-field activation left startup values installed")
assert(#calls==4,"Both persisted values must be restored in reverse order")

-- A thrown native Lua exception gets the same fail-closed restoration and
-- cannot leak its raw error message (which may contain secrets).
snap,form=fresh()
saved["8311_hostname"]="old-fixture-host"
snap=assert(config.snapshot(canonical))
form=baseline_form(snap)
form.hostname="new-fixture-host"
plan=assert(config.prepare(snap,form))
activation_error_mode="exception"
result=config.apply(snap,plan)
assert(not result.success and result.saved_rollback_succeeded and
       result.activation_error=="live_activation_exception",
       "Unhandled activation exception was not sanitized and rolled back")
assert(saved["8311_hostname"]=="old-fixture-host",
       "Unhandled activation exception left new boot value installed")
assert(not result.errors.request:find("sensitive detail",1,true),
       "Unhandled exception leaked sensitive details to result")

-- A malformed native activation response (truthy but not a receipt table)
-- must not throw after durable boot-environment persistence.
snap,form=fresh()
saved["8311_hostname"]="old-fixture-host"
snap=assert(config.snapshot(canonical))
form=baseline_form(snap)
form.hostname="new-fixture-host"
plan=assert(config.prepare(snap,form))
activation_error_mode="malformed_receipt"
result=config.apply(snap,plan)
assert(not result.success and result.saved_rollback_succeeded and
       result.activation_error=="live_activation_unavailable",
       "Malformed native activation receipt was accepted")
assert(saved["8311_hostname"]=="old-fixture-host" and result.runtime_state_unknown,
       "Malformed native activation receipt persisted an unverified setting")

-- A setter reporting success while failing restoration is NOT a successful
-- rollback, regardless of whether it returned true to the caller.
snap,form=fresh()
saved["8311_hostname"]="old-fixture-host"
snap=assert(config.snapshot(canonical))
form=baseline_form(snap)
form.hostname="new-fixture-host"
plan=assert(config.prepare(snap,form))
activation_error_mode="no_receipt"
fail_mode="rollback_mismatch"
result=config.apply(snap,plan)
assert(not result.success and not result.saved_rollback_succeeded and
       result.durability_unknown and result.runtime_state_unknown,
       "Failed post-activation saved readback must be classified as unknown")
assert(saved["8311_hostname"]=="drifted-after-rollback" and
       #result.verified==0,"Unverified restore was reported as a success")
fail_mode=nil

print(("C-012 native schema configuration fixtures: %d fields; routes live=%d management=%d boot=%d credential=%d pon=%d; %d ordinary verified writes; %d sensitive fields; rollback guards PASS"):format(
    checked,route_counts.live,route_counts.management,route_counts.boot,
    route_counts.credential,route_counts.pon,mutation_count,sensitive_count))
