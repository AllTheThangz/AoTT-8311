-- C-012 source-only tests of the real LuCI schema and 8311.config writer.
-- All native dependencies are memory-only stubs. No ONU, UCI or flash calls.
local calls, saved, fail_mode, missing_readback = {}, {}, nil, false
local function copy(t)
    local out={}
    for k,v in pairs(t) do out[k]=v end
    return out
end

local function setter(kind)
    return function(args)
        calls[#calls+1]={kind=kind,id=args[1],value=args[2]}
        if fail_mode=="before" then return false end
        saved[(kind=="base" and "" or "8311_")..args[1]]=args[2]
        if fail_mode=="after" then return false end
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
for _,name in ipairs({
    "luci.template","luci.http","luci.dispatcher","luci.sys",
    "luci.ltn12","nixio.bit","luci.model.uci","8311.health","8311.monitoring",
    "8311.history_config","8311.history_live_snapshot","8311.management_preflight",
    "8311.effective_probe","8311.effective_device_probe",
    "8311.effective_pon_probe","8311.effective_vlan_probe",
    "8311.effective_hardware_probe","8311.effective_reporting_probe",
    "8311.uploads","8311.jobs"
}) do package.preload[name]=function() return {} end end

local config=assert(loadfile(assert(arg[1],"config path")))()
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
assert(count==54,"Unexpected real GUI field count: "..count)

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
        gateway="192.0.2.1", dns_server="192.0.2.20",
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
                assert(diff.applies and not diff.applies:find("verified",1,true),
                    item.id..": falsely reported verified runtime effect")
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
            local apply=config.apply(snap,planned)
            assert(apply.success and #apply.verified==1 and apply.verified[1]==item.id,
                item.id..": positive write/readback failed")
            assert(#calls==1,item.id..": native setter not called exactly once")
            assert(calls[1].kind==(item.base and "base" or "prefixed"),
                item.id..": wrong boot environment namespace")
            assert(saved[stored_key(item)]==planned.changes[1].raw,
                item.id..": readback differs from proposed stored value")
            mutation_count=mutation_count+1
        end
        checked=checked+1
        max_count=max_count+#planned.diff
    end
end
assert(checked==54 and mutation_count>=47,
       "Too few positive write cases: "..mutation_count.."/"..checked)
assert(sensitive_count==5,"Unexpected source secret markers: "..sensitive_count)

local function fresh()
    saved={["8311_gpon_sn"]="TEST00000000", ["8311_ipaddr"]="192.0.2.10"}
    calls={}
    fail_mode=nil
    missing_readback=false
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
fail_mode="after"
local result=config.apply(snap,plan)
assert(not result.success and result.durability_unknown and result.partial,
       "Postwrite failure must acknowledge unknown durability")
assert(#calls==1,"Postwrite failure retried unapproved writes")

snap,form=fresh()
form.hostname="good-lab-host"
form.ntp_servers="time.example"
plan=assert(config.prepare(snap,form))
-- First write succeeds, second fails before mutation. Preserve partial status.
local original_setter=package.loaded["8311.tools"].fw_setenv_8311
package.loaded["8311.tools"].fw_setenv_8311=function(args)
    if args[1]=="ntp_servers" then return false end
    return original_setter(args)
end
result=config.apply(snap,plan)
assert(not result.success and result.partial and result.durability_unknown,
       "Multi-field write failure falsely reported all-or-nothing")
assert(result.verified[1]=="hostname" and #result.verified==1,
       "Partial write receipt did not identify completed field")
assert(#calls==1 and saved["8311_ntp_servers"]==nil,
       "Failed second setter unexpectedly changed values")
package.loaded["8311.tools"].fw_setenv_8311=original_setter

snap,form=fresh()
form.hostname="good-lab-host"
plan=assert(config.prepare(snap,form))
missing_readback=true
result=config.apply(snap,plan)
assert(not result.success and result.durability_unknown,
       "Unavailable postwrite readback falsely reported saved")

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
assert(not result.success and result.durability_unknown and result.partial,
       "Incorrect native readback cannot be accepted as success")
assert(#result.verified==0 and #calls==1,
       "Mismatch must fail before additional writes or verified receipts")
package.loaded["8311.tools"].fw_setenv_8311=original_write

print(("C-012 native schema configuration fixtures: %d fields, %d positive writes, %d sensitive fields, 7 failure/guard cases PASS"):format(
    checked,mutation_count,sensitive_count))
